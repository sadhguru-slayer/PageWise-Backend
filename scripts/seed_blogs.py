import sys
from datetime import datetime
import json

sys.path.insert(0, 'backend')
from app.database import SessionLocal
from app.models import BlogPost

def seed():
    db = SessionLocal()
    existing_count = db.query(BlogPost).count()
    if existing_count == 0:
        articles = [
            {
                'slug': 'engineering-resume-benchmark-ats-vs-humans',
                'title': 'The Engineering Resume Benchmark: What ATS Actually Sees vs What Humans See',
                'summary': 'A technical autopsy of how modern Applicant Tracking Systems (Workday, Greenhouse, Lever) parse resumes, why standard PDF generators fail, and how to calibrate visual hierarchy.',
                'cover_image_url': 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?q=80&w=1200&auto=format&fit=crop',
                'author_name': 'Sadguru Chenu',
                'author_role': 'Founder & Lead Architect',
                'tags_json': json.dumps(["ATS Optimization", "Engineering Careers", "Technical Resumes"]),
                'reading_time_minutes': 6,
                'is_published': True,
                'published_at': datetime.utcnow(),
                'content_html': """
<p>Most software engineers assume applicant tracking systems (ATS) are intelligent algorithms that understand nuance. In reality, modern ATS parsers like Workday, Greenhouse, and Taleo rely on strict structural extractors. When you feed them multi-column PDFs with complex layering, they scramble your work history into garbled fragments.</p>

<h2>1. The Geometry Trap: Columns vs Linear Streams</h2>
<p>When an ATS parses an uploaded PDF, it does not look at the rendered image. Instead, it inspects the underlying PDF content stream. If your resume uses float-based multi-column CSS or absolute positioning without semantic tags, the text stream interleaves words across columns. Your bullet point about distributed systems merges into your list of tools from the sidebar.</p>
<p><strong>The Fix:</strong> True linear document streaming with calibrated millimeter grid layouts that preserve deterministic flow order.</p>

<h2>2. Vector Font Embedding vs Glyph Replacement</h2>
<p>Many resume builders render text to canvas or convert fonts into raster images or odd ligatures. When an automated parser inspects a character code like <code>fi</code> or <code>fl</code>, poorly encoded fonts return non-ASCII replacement characters. To an ATS keyword matcher, <em>'configured Kubernetes'</em> turns into an unindexed word.</p>

<h2>3. Grounded Impact Metrics</h2>
<p>Human hiring managers scan for scope, latency, and business outcomes within 6 seconds. Wiser AI enforces the Google XYZ formula: <em>'Accomplished [X] as measured by [Y] by doing [Z]'</em>. Never fabricate fake numbers—quantify the true scope of your systems.</p>
"""
            },
            {
                'slug': 'single-page-vs-multi-page-resume-rules',
                'title': 'Single-Page vs Multi-Page Resumes: Definitive Rules for Tech & Leadership',
                'summary': 'When should you compress your experience into a single A4 page, and when is a multi-page architecture mandatory? A guide based on real recruitment data.',
                'cover_image_url': 'https://images.unsplash.com/photo-1486312338219-ce68d2c6f44d?q=80&w=1200&auto=format&fit=crop',
                'author_name': 'PageWise Editorial',
                'author_role': 'Career Intelligence',
                'tags_json': json.dumps(["Resume Formatting", "Career Strategy", "A4 Layout"]),
                'reading_time_minutes': 5,
                'is_published': True,
                'published_at': datetime.utcnow(),
                'content_html': """
<p>The golden rule for tech resumes has long been preached: <em>'Keep it strictly to one page.'</em> But in engineering and technical leadership, arbitrary single-page compression often does more harm than good.</p>

<h2>When 1 Page is Required</h2>
<ul>
  <li><strong>0 to 4 years of experience:</strong> University graduates, junior engineers, and career switchers should strictly remain on a single calibrated A4 sheet. Every millimeter must deliver dense, high-signal information.</li>
  <li><strong>Targeted Specialist Applications:</strong> When applying to a specific role where only your most recent 2 projects are directly relevant.</li>
</ul>

<h2>When 2 Pages are Preferred</h2>
<ul>
  <li><strong>5+ years with significant system complexity:</strong> If you designed distributed architectures, managed cross-functional migrations, or hold patents and publications, squeezing this into 1 page drops font size below 9pt, destroying readability.</li>
  <li><strong>Staff, Principal, & Engineering Management:</strong> Hiring committees expect detail on team size, infrastructure budgets, and multi-year architectural roadmaps.</li>
</ul>

<h2>The Millimeter Danger: The Dreaded Spillover</h2>
<p>The worst mistake is a 1.1-page resume: three stray bullet points spilling onto page 2 with vast whitespace. PageWise solves this with real-time A4 visual geometry, showing you exact page breaks as you type.</p>
"""
            },
            {
                'slug': 'why-pdf-exporters-break-ats-and-how-to-fix-it',
                'title': 'Why Most Web PDF Exporters Break ATS (And How Native Vector Generation Solves It)',
                'summary': 'Deep dive into HTML canvas rasterization vs headless browser print drivers vs true vector PDF pipelines.',
                'cover_image_url': 'https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?q=80&w=1200&auto=format&fit=crop',
                'author_name': 'Sadguru Chenu',
                'author_role': 'Founder & Lead Architect',
                'tags_json': json.dumps(["PDF Architecture", "ATS Optimization", "Deep Dive"]),
                'reading_time_minutes': 7,
                'is_published': True,
                'published_at': datetime.utcnow(),
                'content_html': """
<p>Have you ever exported a resume from a generic website builder, uploaded it to a job portal, and had the auto-fill form output gibberish or nothing at all?</p>

<h2>The html2canvas Shortcut</h2>
<p>Under the hood, 80% of online resume builders use a client-side JavaScript library called <code>html2canvas</code>. It screenshots your HTML DOM and wraps the resulting PNG image inside a PDF envelope. To human eyes on a screen, it looks like a document. To an ATS machine reader, it is a blank picture with zero text.</p>

<h2>Native Word (.docx) & Calibrated Vector PDFs</h2>
<p>At PageWise, we engineered an isolated document rendering pipeline. We generate clean vector text objects conforming to PDF/A standards and native OpenXML Microsoft Word (.docx) files. When parsed by Workday or Taleo, text nodes are extracted in 100% semantic order.</p>
"""
            }
        ]
        for art in articles:
            p = BlogPost(**art)
            db.add(p)
        db.commit()
        print('Seeded 3 starter blog posts!')
    else:
        print(f'Already have {existing_count} blog posts in database.')
    db.close()

if __name__ == '__main__':
    seed()
