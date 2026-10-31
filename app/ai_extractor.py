import os
import json
import uuid
import pymupdf
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables (such as GEMINI_API_KEY) from .env in backend/ or root
# without inspecting or modifying the .env file directly.
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
root_dir = os.path.dirname(backend_dir)
load_dotenv(os.path.join(backend_dir, ".env"))
load_dotenv(os.path.join(root_dir, ".env"))
load_dotenv()


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


def parse_resume_with_gemini(extracted_text: str) -> dict:
    """
    Uses Google GenAI SDK (google-genai) with Gemini Flash models to parse raw resume text
    into a structured Resume Header and individual Sections.
    """
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not configured in the environment or .env file. "
            "Please ensure GEMINI_API_KEY is added to your .env file."
        )

    client = genai.Client(api_key=api_key)

    prompt = f"""
You are an expert ATS resume parser. Your task is to analyze the following raw text extracted from a resume PDF and convert it into a structured, high-fidelity JSON object.

Output MUST be valid JSON adhering strictly to this schema:
{{
  "header": {{
    "name": "Candidate Full Name",
    "email": "candidate@example.com",
    "phone": "+1 ...",
    "location": "City, State / Country",
    "linkedin": "full URL or username",
    "github": "full URL or username",
    "website": "portfolio or website URL",
    "contactLine": "email • phone • location",
    "customLinks": [
      {{ "id": "l-1", "label": "Portfolio", "url": "https://..." }}
    ]
  }},
  "sections": [
    {{
      "id": "sec-1",
      "title": "Professional Summary",
      "visible": true,
      "order": 0,
      "contentHtml": "<p>High impact summary...</p>"
    }},
    {{
      "id": "sec-2",
      "title": "Work Experience",
      "visible": true,
      "order": 1,
      "contentHtml": "<p><strong>Job Title</strong> — Company Name (2021 – Present)</p><ul><li>Key achievement with quantifiable metric</li><li>Another responsibility or accomplishment</li></ul>"
    }},
    {{
      "id": "sec-3",
      "title": "Education",
      "visible": true,
      "order": 2,
      "contentHtml": "<p><strong>Degree Name</strong> — University Name (Year)</p>"
    }},
    {{
      "id": "sec-4",
      "title": "Skills",
      "visible": true,
      "order": 3,
      "contentHtml": "<p><strong>Languages:</strong> Python, JavaScript, TypeScript</p><p><strong>Frameworks:</strong> React, Next.js, FastAPI</p>"
    }}
  ]
}}

Formatting Guidelines:
1. Divide the resume cleanly into distinct standard sections: Summary/Objective, Work Experience, Education, Projects, Skills, Certifications, Awards, etc.
2. In `contentHtml`, format content using rich, clean, semantic HTML:
   - Wrap job/degree/project titles in `<p><strong>Title / Degree</strong> — Company / School (Date)</p>`.
   - Wrap hyperlinked text in clickable tags: `<a href="https://..." target="_blank" rel="noopener noreferrer">label or link</a>`.
   - Use bold `<strong>` for tech stacks, skills, or key metrics: `<p><strong>Languages:</strong> Python, JavaScript...</p>`.
   - Wrap bullet points in `<ul><li>Accomplishment with <strong>metric</strong></li></ul>`.
   - Use separate `<p>` tags for distinct paragraphs or subsections.
   - Do NOT omit any information from the extracted resume.
3. Crucial Hyperlink Requirements:
   - Inspect the 'DETECTED PDF HYPERLINKS & URIs' section below carefully.
   - Attach these detected URLs to their corresponding anchors, project titles, demos, and profiles.
   - In `header`, extract candidate name, contact info, and links accurately. Ensure `linkedin`, `github`, and `website` contain full URLs if detected.
4. Ensure each section has a unique `id` (e.g. sec-1, sec-2) and incremental `order` (0, 1, 2...).
5. Return JSON ONLY without markdown wrapping or conversational commentary.

Extracted Resume Text:
{extracted_text}
"""

    candidate_models = [
        "models/gemini-3.5-flash",
        "models/gemini-3.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "models/gemini-flash-latest",
    ]
    last_error = None
    response = None

    for model_name in candidate_models:
        try:
            print(f"[Gemini AI] Attempting resume parsing with model: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            if response and response.text:
                print(f"[Gemini AI] Successfully parsed resume with {model_name}!")
                break
        except Exception as e:
            print(f"[Gemini AI] Model {model_name} failed: {e}")
            last_error = e

    if not response or not response.text:
        raise RuntimeError(f"All Gemini models failed to parse resume: {last_error}")

    raw_response_text = response.text.strip()
    parsed_data = json.loads(raw_response_text)

    # Standardize header with clickable hyperlinks
    hdr = parsed_data.get("header", {})
    contact_parts = []
    if hdr.get("location"):
        contact_parts.append(str(hdr["location"]).strip())
    if hdr.get("email"):
        email = str(hdr["email"]).strip()
        contact_parts.append(f'<a href="mailto:{email}" target="_blank" rel="noopener noreferrer">{email}</a>')
    if hdr.get("phone"):
        contact_parts.append(str(hdr["phone"]).strip())
    if hdr.get("website"):
        url = str(hdr["website"]).strip()
        full_url = url if url.startswith("http") else f"https://{url}"
        contact_parts.append(f'<a href="{full_url}" target="_blank" rel="noopener noreferrer">Portfolio</a>')
    if hdr.get("linkedin"):
        li = str(hdr["linkedin"]).strip()
        full_li = li if li.startswith("http") else f"https://linkedin.com/in/{li.replace('linkedin.com/in/', '')}"
        contact_parts.append(f'<a href="{full_li}" target="_blank" rel="noopener noreferrer">LinkedIn</a>')
    if hdr.get("github"):
        gh = str(hdr["github"]).strip()
        full_gh = gh if gh.startswith("http") else f"https://github.com/{gh.replace('github.com/', '')}"
        contact_parts.append(f'<a href="{full_gh}" target="_blank" rel="noopener noreferrer">GitHub</a>')

    for link in hdr.get("customLinks", []):
        if link.get("label") and link.get("url"):
            contact_parts.append(f'<a href="{link["url"]}" target="_blank" rel="noopener noreferrer">{link["label"]}</a>')

    if contact_parts:
        hdr["contactLine"] = " · ".join(contact_parts)
    elif not hdr.get("contactLine"):
        hdr["contactLine"] = ""
    
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

    # Ensure sections have unique string IDs and both 'content' & 'contentHtml'
    for idx, sec in enumerate(parsed_data.get("sections", [])):
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
