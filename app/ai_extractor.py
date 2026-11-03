import os
import re
import uuid
import pymupdf

from .wiser_runtime import async_generate_json, generate_json, load_prompt


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    Extracts text and hyperlink annotations from raw PDF bytes using PyMuPDF.
    Preserves multi-page content, sequential structure, and explicit link URIs.
    """
    import re
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    pages_text = []
    all_detected_links = []

    for idx, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            pages_text.append(f"--- PAGE {idx + 1} ---\n{text}")

        # Extract PDF Link Annotations (URIs attached to anchors/icons)
        try:
            links = page.get_links()
            for l in links:
                uri = l.get("uri")
                if uri:
                    uri = uri.strip()
                    rect = l.get("from")
                    anchor = ""
                    if rect:
                        anchor = page.get_text("text", clip=rect).strip()
                    all_detected_links.append((anchor, uri))
        except Exception as e:
            print(f"[PyMuPDF] Notice: could not get page links: {e}")

    doc.close()
    combined_text = "\n\n".join(pages_text).strip()

    if not combined_text:
        raise ValueError("The uploaded PDF does not contain extractable text or is a scanned image.")

    # Deduplicate detected links
    unique_links = []
    seen = set()
    for anchor, uri in all_detected_links:
        key = (anchor, uri)
        if key not in seen:
            seen.add(key)
            unique_links.append((anchor, uri))

    # Also detect plain text URLs in the document
    text_urls = re.findall(r'(?:https?://|www\.|linkedin\.com/in/|github\.com/)[^\s)\]>]+', combined_text, re.IGNORECASE)
    for u in text_urls:
        clean_u = u.strip().rstrip(".,;")
        if clean_u:
            full_u = clean_u if clean_u.startswith("http") else f"https://{clean_u}"
            if ("", full_u) not in seen and (clean_u, full_u) not in seen:
                seen.add(("", full_u))
                unique_links.append(("", full_u))

    if unique_links:
        links_block = ["--- DETECTED PDF HYPERLINKS & URIs ---"]
        for anchor, uri in unique_links:
            if anchor:
                links_block.append(f"- Anchor: \"{anchor}\" -> URL: {uri}")
            else:
                links_block.append(f"- URL: {uri}")
        combined_text += "\n\n" + "\n".join(links_block)

    return combined_text


def _build_parse_prompt(extracted_text: str, allow_bold_text: bool = False) -> str:
    prompt_template = load_prompt("resume_parser.prompt")

    if allow_bold_text:
        bold_rule = "Use bold <strong> tags sparingly for job titles and primary metrics where helpful."
    else:
        bold_rule = "DO NOT use any bold tags (<strong> or <b>) anywhere in contentHtml. Keep all text plain and unbolded as standard professional resumes avoid embedded bold tags."

    text = extracted_text or ""
    if len(text) > 18000:
        text = text[:18000] + "\n[truncated]"

    prompt = prompt_template.replace("{{BOLD_RULE}}", bold_rule)
    prompt += f"\n\nExtracted Resume Text:\n{text}\n"
    return prompt


def _clean_url(u: str) -> str:
    if not u:
        return ""
    return re.sub(r"^https?://(www\.)?", "", str(u).strip().lower().rstrip("/"))


def _post_process_parsed_data(parsed_data: dict) -> dict:
    hdr = parsed_data.get("header", {})
    sections = parsed_data.get("sections", [])

    # Check for portfolio / links section
    portfolio_sec_idx = None
    for idx, sec in enumerate(sections):
        title = (sec.get("title") or "").strip().lower()
        if re.search(r"^(portfolio|links|portfolio links|websites|profiles|social links|online presence)$", title):
            portfolio_sec_idx = idx
            break

    portfolio_links = []
    if portfolio_sec_idx is not None:
        p_sec = sections[portfolio_sec_idx]
        portfolio_links = p_sec.get("links", []) or []

    hdr_custom_links = hdr.get("customLinks", []) or []

    # Count distinct portfolio links
    all_portfolio_urls = []
    for l in portfolio_links + hdr_custom_links:
        u = l.get("url") if isinstance(l, dict) else str(l)
        cu = _clean_url(u)
        if cu and cu not in all_portfolio_urls:
            all_portfolio_urls.append(cu)

    total_p_links_count = len(all_portfolio_urls)
    has_portfolio_section = portfolio_sec_idx is not None

    # Decision:
    # If <= 3 portfolio links: put them in Header, remove the portfolio section
    # If >= 4 portfolio links: keep the Section, do NOT duplicate in Header
    keep_in_header = not has_portfolio_section or (total_p_links_count <= 3)

    if has_portfolio_section:
        if keep_in_header:
            existing_urls = {_clean_url(l.get("url")) for l in hdr_custom_links if isinstance(l, dict)}
            for l in portfolio_links:
                if isinstance(l, dict):
                    cu = _clean_url(l.get("url"))
                    if cu and cu not in existing_urls:
                        hdr_custom_links.append(l)
                        existing_urls.add(cu)
            hdr["customLinks"] = hdr_custom_links
            sections.pop(portfolio_sec_idx)
        else:
            hdr["customLinks"] = []

    seen_keys = set()
    contact_parts = []

    if hdr.get("location"):
        contact_parts.append(str(hdr["location"]).strip())

    if hdr.get("email"):
        email = str(hdr["email"]).strip()
        seen_keys.add(_clean_url(email))
        contact_parts.append(f'<a href="mailto:{email}" target="_blank" rel="noopener noreferrer">{email}</a>')

    if hdr.get("phone"):
        contact_parts.append(str(hdr["phone"]).strip())

    if hdr.get("website"):
        url = str(hdr["website"]).strip()
        cu = _clean_url(url)
        if cu and cu not in seen_keys:
            seen_keys.add(cu)
            full_url = url if url.startswith("http") else f"https://{url}"
            contact_parts.append(f'<a href="{full_url}" target="_blank" rel="noopener noreferrer">Portfolio</a>')

    if hdr.get("linkedin"):
        li = str(hdr["linkedin"]).strip()
        cu = _clean_url(li)
        if cu and cu not in seen_keys:
            seen_keys.add(cu)
            clean_li = re.sub(r"^https?://(www\.)?linkedin\.com/in/", "", li, flags=re.IGNORECASE)
            full_li = f"https://linkedin.com/in/{clean_li}"
            contact_parts.append(f'<a href="{full_li}" target="_blank" rel="noopener noreferrer">LinkedIn</a>')

    if hdr.get("github"):
        gh = str(hdr["github"]).strip()
        cu = _clean_url(gh)
        if cu and cu not in seen_keys:
            seen_keys.add(cu)
            clean_gh = re.sub(r"^https?://(www\.)?github\.com/", "", gh, flags=re.IGNORECASE)
            full_gh = f"https://github.com/{clean_gh}"
            contact_parts.append(f'<a href="{full_gh}" target="_blank" rel="noopener noreferrer">GitHub</a>')

    if keep_in_header:
        for link in hdr.get("customLinks", []):
            if isinstance(link, dict) and link.get("url"):
                raw_url = link["url"]
                cu = _clean_url(raw_url)
                if cu and cu not in seen_keys:
                    seen_keys.add(cu)
                    label = link.get("label") or "Portfolio"
                    full_u = raw_url if raw_url.startswith("http") else f"https://{raw_url}"
                    contact_parts.append(f'<a href="{full_u}" target="_blank" rel="noopener noreferrer">{label}</a>')

    hdr["contactLine"] = " · ".join(contact_parts)

    if "alignment" not in hdr:
        hdr["alignment"] = "center"
    if "showDivider" not in hdr:
        hdr["showDivider"] = True
    if "nameFontSize" not in hdr:
        hdr["nameFontSize"] = 22
    if "divider" not in hdr or not hdr["divider"]:
        hdr["divider"] = {
            "color": "#d1d5db",
            "thickness": 1,
            "marginTop": 5,
            "marginBottom": 5,
            "style": "solid",
        }
    parsed_data["header"] = hdr
    parsed_data["sections"] = sections

    # Ensure sections have unique string IDs and both 'content' & 'contentHtml'
    for idx, sec in enumerate(sections):
        if "id" not in sec or not sec["id"]:
            sec["id"] = f"sec-{uuid.uuid4().hex[:6]}"
        sec["order"] = idx
        if "visible" not in sec:
            sec["visible"] = True

        raw_html = sec.get("contentHtml") or sec.get("content") or ""
        sec["content"] = raw_html
        sec["contentHtml"] = raw_html
        sec["headingAlign"] = sec.get("headingAlign", "left")
        sec["headingBold"] = True
        sec["headingUppercase"] = True
        sec["showDividerAfterHeading"] = True
        sec["headingDividerThickness"] = 1
        sec["headingDividerStyle"] = "solid"
        sec["headingDividerMarginTop"] = 2
        sec["headingDividerMarginBottom"] = 3
        if "links" not in sec:
            sec["links"] = []

    return parsed_data


async def async_parse_resume_with_wiser_ai(extracted_text: str, allow_bold_text: bool = False) -> dict:
    """
    Non-blocking async parser using Wiser AI engine.
    """
    prompt = _build_parse_prompt(extracted_text, allow_bold_text=allow_bold_text)
    print("[Wiser AI] Attempting async resume parsing with engine...")
    parsed_data = await async_generate_json(prompt, temperature=0.1)
    print("[Wiser AI] Successfully parsed resume!")
    return _post_process_parsed_data(parsed_data)


def parse_resume_with_wiser_ai(extracted_text: str, allow_bold_text: bool = False) -> dict:
    """
    Synchronous fallback parser using Wiser AI engine.
    """
    prompt = _build_parse_prompt(extracted_text, allow_bold_text=allow_bold_text)
    print("[Wiser AI] Attempting sync resume parsing with engine...")
    parsed_data = generate_json(prompt, temperature=0.1)
    print("[Wiser AI] Successfully parsed resume!")
    return _post_process_parsed_data(parsed_data)


# Backward-compatible alias
parse_resume_with_gemini = parse_resume_with_wiser_ai
