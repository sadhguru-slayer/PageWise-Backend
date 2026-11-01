import os
import re
import uuid
import asyncio
from bs4 import BeautifulSoup
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import fitz  # PyMuPDF

from .config import EXPORTS_DIR


# ---------------------------------------------------------------------------
# PDF Generation — WeasyPrint (with PyMuPDF fallback)
# WeasyPrint renders exact CSS, typography, and active clickable hyperlinks
# with a tiny footprint (~30 MB RAM, 0 browser/GUI dependencies).
# ---------------------------------------------------------------------------

def _sync_render_pdf_weasyprint(html_content: str, file_path: str):
    import weasyprint
    weasyprint.HTML(string=html_content).write_pdf(file_path)


def _sync_render_pdf_pymupdf(html_content: str, file_path: str):
    """
    Fallback: Converts HTML resume content to a PDF using PyMuPDF's Story engine.
    """
    story = fitz.Story(html=html_content)

    # A4 page: 595 x 842 points (1 pt = 1/72 inch)
    mediabox = fitz.Rect(0, 0, 595, 842)
    where = fitz.Rect(0, 0, 595, 842)

    writer = fitz.DocumentWriter(file_path)

    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()

    writer.close()


def _sync_render_pdf(html_content: str, file_path: str):
    """
    Primary renderer: uses WeasyPrint for pixel-accurate layout and clickable links.
    Falls back to PyMuPDF if WeasyPrint is unavailable.
    """
    try:
        _sync_render_pdf_weasyprint(html_content, file_path)
    except Exception as e:
        print(f"WeasyPrint rendering failed ({e}), falling back to PyMuPDF.")
        _sync_render_pdf_pymupdf(html_content, file_path)


async def generate_pdf_from_html(html_content: str, base_filename: str = "resume") -> tuple[str, str, int]:
    """
    Generates a PDF from HTML resume content using WeasyPrint.
    Returns: (file_path, file_name, file_size)
    """
    safe_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', base_filename).strip() or "resume"
    unique_id = uuid.uuid4().hex[:8]
    file_name = f"{safe_name}_{unique_id}.pdf"
    file_path = os.path.join(EXPORTS_DIR, file_name)

    await asyncio.to_thread(_sync_render_pdf, html_content, file_path)

    file_size = os.path.getsize(file_path)
    return file_path, file_name, file_size


def _sync_render_image(html_content: str, file_path: str):
    """
    Renders high-res PNG image from the high-fidelity PDF rendered via WeasyPrint.
    """
    temp_pdf = file_path + ".tmp.pdf"
    try:
        _sync_render_pdf(html_content, temp_pdf)
        doc = fitz.open(temp_pdf)
        if len(doc) > 0:
            pix = doc[0].get_pixmap(dpi=200)
            pix.save(file_path)
        doc.close()
    finally:
        if os.path.exists(temp_pdf):
            try:
                os.remove(temp_pdf)
            except Exception:
                pass


async def generate_image_from_html(html_content: str, base_filename: str = "resume") -> tuple[str, str, int]:
    """
    Renders high-res PNG image from HTML content.
    Returns: (file_path, file_name, file_size)
    """
    safe_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', base_filename).strip() or "resume"
    unique_id = uuid.uuid4().hex[:8]
    file_name = f"{safe_name}_{unique_id}.png"
    file_path = os.path.join(EXPORTS_DIR, file_name)

    await asyncio.to_thread(_sync_render_image, html_content, file_path)

    file_size = os.path.getsize(file_path)
    return file_path, file_name, file_size


# ---------------------------------------------------------------------------
# HTML Export — Save standalone HTML file
# ---------------------------------------------------------------------------

async def generate_html_file(html_content: str, base_filename: str = "resume") -> tuple[str, str, int]:
    """
    Saves standalone clean HTML export.
    Returns: (file_path, file_name, file_size)
    """
    safe_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', base_filename).strip() or "resume"
    unique_id = uuid.uuid4().hex[:8]
    file_name = f"{safe_name}_{unique_id}.html"
    file_path = os.path.join(EXPORTS_DIR, file_name)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    file_size = os.path.getsize(file_path)
    return file_path, file_name, file_size


# ---------------------------------------------------------------------------
# DOCX Generation — python-docx
# Generates a styled Word document from structured resume JSON data.
# ---------------------------------------------------------------------------

def hex_to_rgb(hex_str: str) -> RGBColor:
    """Helper to convert hex color like '#3b82f6' to docx RGBColor."""
    try:
        hex_clean = hex_str.lstrip("#")
        if len(hex_clean) == 3:
            hex_clean = "".join([c * 2 for c in hex_clean])
        r = int(hex_clean[0:2], 16)
        g = int(hex_clean[2:4], 16)
        b = int(hex_clean[4:6], 16)
        return RGBColor(r, g, b)
    except Exception:
        return RGBColor(51, 51, 51)


def add_bottom_border(paragraph, color_hex="999999", size="12"):
    """Adds a bottom border line to a Word paragraph (for section titles)."""
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), size)
    bottom.set(qn('w:space'), '4')
    bottom.set(qn('w:color'), color_hex.lstrip('#'))
    pBdr.append(bottom)
    pPr.append(pBdr)


def parse_html_to_docx_runs(paragraph, html_text, base_font_size=10, base_font_name="Calibri"):
    """
    Recursively parses HTML text (bold, italic, underline, links, headings) into Word docx runs.
    """
    if not html_text:
        return

    soup = BeautifulSoup(html_text, "html.parser")

    def process_node(node, is_bold=False, is_italic=False, is_underline=False, is_link=False):
        for child in getattr(node, "children", []):
            if isinstance(child, str):
                text = str(child)
                if text:
                    run = paragraph.add_run(text)
                    run.font.name = base_font_name
                    run.font.size = Pt(base_font_size)
                    if is_bold:
                        run.bold = True
                    if is_italic:
                        run.italic = True
                    if is_underline or is_link:
                        run.underline = True
                    if is_link:
                        run.font.color.rgb = RGBColor(37, 99, 235)
            else:
                tag = child.name.lower() if child.name else ""
                child_bold = is_bold or (tag in ["strong", "b", "h1", "h2", "h3", "h4"])
                child_italic = is_italic or (tag in ["em", "i"])
                child_underline = is_underline or (tag == "u")
                child_link = is_link or (tag == "a")
                process_node(child, child_bold, child_italic, child_underline, child_link)

    process_node(soup)


def generate_docx_from_resume_data(
    name: str,
    header: dict,
    settings: dict,
    sections: list
) -> tuple[str, str, int]:
    """
    Generates a professionally styled Microsoft Word document (.docx) from resume JSON data.
    Preserves margins, fonts, colors, sections, bullet points, and headers.
    Returns: (file_path, file_name, file_size)
    """
    doc = Document()

    # Document margins
    page_margin_pt = settings.get("pageMargin", 36)  # default 36pt = 0.5 inch
    margin_inches = max(0.3, page_margin_pt / 72.0)
    for section in doc.sections:
        section.top_margin = Inches(margin_inches)
        section.bottom_margin = Inches(margin_inches)
        section.left_margin = Inches(margin_inches)
        section.right_margin = Inches(margin_inches)

    font_family = settings.get("fontFamily", "Calibri")
    primary_color_hex = settings.get("primaryColor", "#1e293b")
    primary_rgb = hex_to_rgb(primary_color_hex)
    body_size_pt = settings.get("bodyFontSize", 10)

    # ─── HEADER ───────────────────────────────────────────────────────────────
    full_name = header.get("name", "Your Name")
    name_size = header.get("nameFontSize", 22)
    alignment_str = header.get("alignment", "center")

    name_para = doc.add_paragraph()
    if alignment_str == "center":
        name_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif alignment_str == "right":
        name_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    else:
        name_para.alignment = WD_ALIGN_PARAGRAPH.LEFT

    name_para.paragraph_format.space_after = Pt(2)
    name_para.paragraph_format.space_before = Pt(0)
    name_run = name_para.add_run(full_name)
    name_run.font.name = font_family
    name_run.font.size = Pt(name_size)
    name_run.bold = True
    name_run.font.color.rgb = primary_rgb

    # Contact line
    contact_parts = []
    if header.get("contactLine"):
        contact_parts.append(header["contactLine"])
    else:
        if header.get("location"):
            contact_parts.append(header["location"])
        if header.get("email"):
            contact_parts.append(header["email"])
        if header.get("phone"):
            contact_parts.append(header["phone"])
        if header.get("website"):
            contact_parts.append(header["website"])
        if header.get("linkedin"):
            contact_parts.append(f"linkedin.com/in/{header['linkedin']}")
        if header.get("github"):
            contact_parts.append(f"github.com/{header['github']}")

    # Custom links
    for link in header.get("customLinks", []):
        if link.get("label") and link.get("url"):
            contact_parts.append(f"{link['label']}: {link['url']}")

    if contact_parts:
        contact_para = doc.add_paragraph()
        if alignment_str == "center":
            contact_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif alignment_str == "right":
            contact_para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        else:
            contact_para.alignment = WD_ALIGN_PARAGRAPH.LEFT

        contact_para.paragraph_format.space_after = Pt(8)
        contact_run = contact_para.add_run("  •  ".join(contact_parts))
        contact_run.font.name = font_family
        contact_run.font.size = Pt(body_size_pt - 0.5)
        contact_run.font.color.rgb = RGBColor(100, 116, 139)

    # ─── SECTIONS ─────────────────────────────────────────────────────────────
    title_size_pt = settings.get("sectionTitleSize", 12)
    title_bold = settings.get("sectionTitleBold", True)
    title_uppercase = settings.get("sectionTitleUppercase", True)
    show_border = settings.get("sectionDivider", True)

    sorted_sections = sorted(sections, key=lambda s: s.get("order", 0))

    for sec in sorted_sections:
        if not sec.get("visible", True):
            continue

        sec_title = sec.get("title", "Section")
        if title_uppercase:
            sec_title = sec_title.upper()

        title_para = doc.add_paragraph()
        title_para.paragraph_format.space_before = Pt(8)
        title_para.paragraph_format.space_after = Pt(3)

        title_run = title_para.add_run(sec_title)
        title_run.font.name = font_family
        title_run.font.size = Pt(title_size_pt)
        title_run.bold = title_bold
        title_run.font.color.rgb = primary_rgb

        if show_border:
            border_hex = primary_color_hex.lstrip("#")
            add_bottom_border(title_para, color_hex=border_hex, size="8")

        # Section Content / HTML
        content_html = sec.get("contentHtml") or sec.get("content") or ""
        if content_html:
            soup = BeautifulSoup(content_html, "html.parser")

            elements = soup.find_all(["p", "ul", "ol"])
            if not elements and soup.get_text().strip():
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.line_spacing = 1.15
                parse_html_to_docx_runs(p, content_html, base_font_size=body_size_pt, base_font_name=font_family)
            else:
                for el in elements:
                    if el.name in ["ul", "ol"]:
                        for li in el.find_all("li"):
                            lp = doc.add_paragraph(style='List Bullet')
                            lp.paragraph_format.space_before = Pt(0)
                            lp.paragraph_format.space_after = Pt(1.5)
                            lp.paragraph_format.line_spacing = 1.15
                            parse_html_to_docx_runs(lp, str(li), base_font_size=body_size_pt, base_font_name=font_family)
                    elif el.name == "p":
                        text = el.get_text().strip()
                        if text:
                            p = doc.add_paragraph()
                            p.paragraph_format.space_before = Pt(0)
                            p.paragraph_format.space_after = Pt(2)
                            p.paragraph_format.line_spacing = 1.15
                            parse_html_to_docx_runs(p, str(el), base_font_size=body_size_pt, base_font_name=font_family)

    safe_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', name).strip() or "resume"
    unique_id = uuid.uuid4().hex[:8]
    file_name = f"{safe_name}_{unique_id}.docx"
    file_path = os.path.join(EXPORTS_DIR, file_name)

    doc.save(file_path)
    file_size = os.path.getsize(file_path)
    return file_path, file_name, file_size
