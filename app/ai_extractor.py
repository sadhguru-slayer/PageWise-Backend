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


def _build_parse_prompt(extracted_text: str, allow_bold_text: bool = True) -> str:
    prompt_template = load_prompt("resume_parser.prompt")

    if allow_bold_text:
        bold_rule = "Use bold <strong> tags sparingly for job titles and primary metrics where helpful."
    else:
        bold_rule = "DO NOT use any bold tags (<strong> or <b>) anywhere in contentHtml. Keep all text plain and unbolded as standard professional resumes avoid embedded bold tags."

    text = extracted_text or ""
    if len(text) > 20000:
        text = text[:20000] + "\n[truncated]"

    prompt = prompt_template.replace("{{BOLD_RULE}}", bold_rule)
    prompt += f"\n\nExtracted Resume Text:\n{text}\n"
    return prompt


def _clean_url(u: str) -> str:
    if not u:
        return ""
    return re.sub(r"^https?://(www\.)?", "", str(u).strip().lower().rstrip("/"))


def _clean_date_str(val: str) -> str:
    if not val or not isinstance(val, str):
        return ""
    cleaned = val.strip().strip("()[]{}—–- ,")
    # Clean up '(present' or 'present)'
    cleaned = re.sub(r"^\(?(present)\)?$", r"\1", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _synthesize_section_html(sec: dict) -> str:
    """Generates clean HTML representation from structured items for backwards compatibility."""
    sec_type = (sec.get("type") or "").lower()
    items = sec.get("items") or []
    if not items and sec.get("contentHtml"):
        return sec.get("contentHtml")

    blocks = []
    if sec_type == "experience":
        for it in items:
            title = it.get("title") or ""
            company = it.get("company") or ""
            start = it.get("start_date") or ""
            end = it.get("end_date") or ""
            loc = it.get("location") or ""
            date_range = f"{start} – {end}" if start and end else (start or end)
            meta = " | ".join(filter(None, [company, loc, date_range]))
            headline = f"<strong>{title}</strong>" if title else ""
            if meta:
                headline += f" — {meta}"
            blocks.append(f"<p>{headline}</p>")
            if it.get("summary"):
                blocks.append(f"<p>{it['summary']}</p>")
            if it.get("tech_stack"):
                stack = ", ".join(it["tech_stack"]) if isinstance(it["tech_stack"], list) else str(it["tech_stack"])
                blocks.append(f"<p><strong>Tech Stack:</strong> {stack}</p>")
            if it.get("points") and isinstance(it["points"], list):
                lis = "".join(f"<li>{p}</li>" for p in it["points"] if p)
                if lis:
                    blocks.append(f"<ul>{lis}</ul>")

    elif sec_type == "education":
        for it in items:
            inst = it.get("institution") or ""
            deg = it.get("degree") or ""
            start = it.get("start_date") or ""
            end = it.get("end_date") or ""
            gpa = it.get("gpa") or ""
            date_range = f"{start} – {end}" if start and end else (start or end)
            headline = f"<strong>{inst}</strong>"
            if date_range:
                headline += f" ({date_range})"
            blocks.append(f"<p>{headline}</p>")
            deg_line = deg
            if gpa:
                deg_line += f" | GPA: {gpa}"
            if deg_line:
                blocks.append(f"<p>{deg_line}</p>")
            if it.get("points") and isinstance(it["points"], list):
                lis = "".join(f"<li>{p}</li>" for p in it["points"] if p)
                if lis:
                    blocks.append(f"<ul>{lis}</ul>")

    elif sec_type == "projects":
        for it in items:
            p_title = it.get("project_title") or ""
            role = it.get("role") or ""
            headline = f"<strong>{p_title}</strong>"
            if role:
                headline += f" | {role}"
            blocks.append(f"<p>{headline}</p>")
            if it.get("tech_stack"):
                stack = ", ".join(it["tech_stack"]) if isinstance(it["tech_stack"], list) else str(it["tech_stack"])
                blocks.append(f"<p><strong>Technologies:</strong> {stack}</p>")
            if it.get("summary"):
                blocks.append(f"<p>{it['summary']}</p>")
            if it.get("points") and isinstance(it["points"], list):
                lis = "".join(f"<li>{p}</li>" for p in it["points"] if p)
                if lis:
                    blocks.append(f"<ul>{lis}</ul>")

    elif sec_type == "skills":
        for it in items:
            cat = it.get("category") or "Technical Skills"
            s_list = it.get("skills") or []
            skills_str = ", ".join(s_list) if isinstance(s_list, list) else str(s_list)
            blocks.append(f"<p><strong>{cat}:</strong> {skills_str}</p>")

    else:
        return sec.get("contentHtml") or ""

    return "".join(blocks)


def _post_process_parsed_data(parsed_data: dict) -> dict:
    hdr = parsed_data.get("header", {}) or {}
    sections = parsed_data.get("sections", []) or []

    # Map candidate header contact channels
    hdr_custom_links = hdr.get("customLinks", []) or []
    seen_urls = set()

    for l in hdr_custom_links:
        if isinstance(l, dict) and l.get("url"):
            seen_urls.add(_clean_url(l["url"]))

    # Primary links in header
    for k in ["website", "linkedin", "github"]:
        val = hdr.get(k)
        if val:
            seen_urls.add(_clean_url(val))

    # Detect dedicated portfolio / links section
    portfolio_sec_idx = None
    for idx, sec in enumerate(sections):
        title = (sec.get("title") or "").strip().lower()
        if re.search(r"^(portfolio|links|portfolio links|websites|profiles|social links|online presence|portfolio & links)$", title):
            portfolio_sec_idx = idx
            break

    # Deduplication: single source of truth
    if portfolio_sec_idx is not None:
        p_sec = sections[portfolio_sec_idx]
        p_links = p_sec.get("links", []) or []

        # If items are present in p_sec (structured)
        if not p_links and isinstance(p_sec.get("items"), list):
            for it in p_sec["items"]:
                if isinstance(it, dict) and it.get("url"):
                    p_links.append({"label": it.get("label") or it.get("name") or "Portfolio", "url": it["url"]})

        # Calculate distinct non-duplicate links
        distinct_portfolio_links = []
        for l in p_links:
            u = l.get("url") if isinstance(l, dict) else str(l)
            cu = _clean_url(u)
            if cu and cu not in seen_urls:
                distinct_portfolio_links.append(l if isinstance(l, dict) else {"label": "Link", "url": u})
                seen_urls.add(cu)

        # Decision rule:
        # If <= 3 total links: keep them in header.customLinks and drop the standalone links section.
        # If >= 4 links: keep them in the dedicated section, do NOT duplicate in header.customLinks.
        if len(distinct_portfolio_links) <= 3:
            for l in distinct_portfolio_links:
                hdr_custom_links.append({
                    "id": f"l-{uuid.uuid4().hex[:6]}",
                    "label": l.get("label") or "Link",
                    "url": l.get("url") or ""
                })
            hdr["customLinks"] = hdr_custom_links
            sections.pop(portfolio_sec_idx)
        else:
            # Dedicated section kept; clear custom links from header to prevent 2x repetition
            hdr["customLinks"] = []
            p_sec["links"] = distinct_portfolio_links

    # Reconstruct formatted contact line
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

    # Normalize each section: clean dates, map items, synthesize HTML
    for idx, sec in enumerate(sections):
        if "id" not in sec or not sec["id"]:
            sec["id"] = f"sec-{uuid.uuid4().hex[:6]}"
        sec["order"] = idx
        if "visible" not in sec:
            sec["visible"] = True

        sec_type = (sec.get("type") or "").lower()
        if not sec_type:
            title_lower = (sec.get("title") or "").lower()
            if "experience" in title_lower or "employment" in title_lower or "work" in title_lower:
                sec_type = "experience"
            elif "education" in title_lower or "academic" in title_lower:
                sec_type = "education"
            elif "project" in title_lower:
                sec_type = "projects"
            elif "skill" in title_lower or "technolog" in title_lower:
                sec_type = "skills"
            elif "certif" in title_lower:
                sec_type = "certifications"
            elif "summary" in title_lower or "objective" in title_lower or "about" in title_lower:
                sec_type = "summary"
            else:
                sec_type = "custom"
            sec["type"] = sec_type

        # Clean dates & fields within items
        items = sec.get("items")
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                if not it.get("id"):
                    it["id"] = f"item-{uuid.uuid4().hex[:6]}"

                # Clean dates
                if "start_date" in it:
                    it["start_date"] = _clean_date_str(it["start_date"])
                if "end_date" in it:
                    it["end_date"] = _clean_date_str(it["end_date"])

                # Clean tech_stack: ensure list of strings
                if "tech_stack" in it:
                    if isinstance(it["tech_stack"], str):
                        it["tech_stack"] = [s.strip() for s in re.split(r"[,•|/]", it["tech_stack"]) if s.strip()]
                    elif isinstance(it["tech_stack"], list):
                        it["tech_stack"] = [str(s).strip() for s in it["tech_stack"] if str(s).strip()]
                    else:
                        it["tech_stack"] = []

                # Clean links: ensure list of dicts with url
                if "links" in it and isinstance(it["links"], list):
                    clean_links = []
                    for l in it["links"]:
                        if isinstance(l, dict) and l.get("url"):
                            clean_links.append({
                                "label": str(l.get("label") or "Link").strip(),
                                "url": str(l["url"]).strip()
                            })
                        elif isinstance(l, str) and l.strip():
                            clean_links.append({
                                "label": "Link",
                                "url": l.strip()
                            })
                    it["links"] = clean_links

        # Synthesize contentHtml from structured items or keep raw html
        html_content = _synthesize_section_html(sec)
        sec["content"] = html_content
        sec["contentHtml"] = html_content

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

    parsed_data["sections"] = sections
    return parsed_data


async def async_parse_resume_with_wiser_ai(extracted_text: str, allow_bold_text: bool = True) -> dict:
    """
    Non-blocking async parser using Wiser AI engine.
    """
    prompt = _build_parse_prompt(extracted_text, allow_bold_text=allow_bold_text)
    print("[Wiser AI] Attempting async resume parsing with structured schema engine...")
    parsed_data = await async_generate_json(prompt, temperature=0.1)
    print("[Wiser AI] Successfully parsed resume!")
    return _post_process_parsed_data(parsed_data)


def parse_resume_with_wiser_ai(extracted_text: str, allow_bold_text: bool = True) -> dict:
    """
    Synchronous fallback parser using Wiser AI engine.
    """
    prompt = _build_parse_prompt(extracted_text, allow_bold_text=allow_bold_text)
    print("[Wiser AI] Attempting sync resume parsing with structured schema engine...")
    parsed_data = generate_json(prompt, temperature=0.1)
    print("[Wiser AI] Successfully parsed resume!")
    return _post_process_parsed_data(parsed_data)


# Backward-compatible alias
parse_resume_with_gemini = parse_resume_with_wiser_ai
