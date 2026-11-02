import os
import json
import re
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Ensure environment variables are loaded
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_root_dir = os.path.dirname(_backend_dir)
load_dotenv(os.path.join(_backend_dir, ".env"))
load_dotenv(os.path.join(_root_dir, ".env"))
load_dotenv()

def _get_gemini_client() -> genai.Client:
    api_key = (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("NEXT_PUBLIC_GEMINI_API_KEY")
    )
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not configured in the environment or .env file. "
            "Please ensure GEMINI_API_KEY is available."
        )
    return genai.Client(api_key=api_key.strip())


MODELS_TO_TRY = [
    "models/gemini-3.1-flash-lite",
    "models/gemini-3.1-flash-lite-preview",
    "models/gemini-3.5-flash",
    "models/gemini-3.5-flash-lite",
    "models/gemini-flash-latest",
    "models/gemini-3.8-flash",
]


def _clean_markdown_json(raw_text: str) -> str:
    """Strips markdown code fencing if present."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def analyze_jd_and_ats(
    job_description: str,
    current_resume: Dict[str, Any],
    previous_resumes: Optional[List[Dict[str, Any]]] = None,
    allow_bold_text: bool = False
) -> Dict[str, Any]:
    """
    Performs comprehensive Job Description (JD) matching, strict ATS checker analysis,
    and smart section/bullet enhancements using Wiser AI ('Wiser Job Help').
    """
    client = _get_gemini_client()

    # Prepare current resume text & structure
    header = current_resume.get("header_json") or current_resume.get("header") or {}
    sections = current_resume.get("sections_json") or current_resume.get("sections") or []

    # Summarize previous resumes context if available
    prev_context = []
    if previous_resumes:
        for p in previous_resumes:
            p_name = p.get("name", "Previous Resume")
            p_sections = p.get("sections_json") or p.get("sections") or []
            sec_snippets = []
            for s in p_sections:
                title = s.get("title", "")
                content = s.get("contentHtml") or s.get("content") or ""
                text_clean = re.sub(r'<[^>]+>', ' ', str(content))
                text_clean = re.sub(r'\s+', ' ', text_clean).strip()
                if text_clean:
                    sec_snippets.append(f"[{title}]: {text_clean[:350]}")
            if sec_snippets:
                prev_context.append(f"Resume '{p_name}':\n" + "\n".join(sec_snippets))

    previous_resumes_block = "\n\n".join(prev_context) if prev_context else "None provided."

    # Load prompt from separate prompt file
    prompt_file_path = os.path.join(os.path.dirname(__file__), "prompts", "jd_analyzer.prompt")
    with open(prompt_file_path, "r", encoding="utf-8") as pf:
        prompt_template = pf.read()

    if allow_bold_text:
        bold_rule = "Use bold <strong> tags sparingly for keywords and metrics in enhanced_html."
    else:
        bold_rule = "DO NOT include any <strong> or <b> tags in enhanced_html. Keep enhanced bullets clean and unbolded, as professional resumes do not use inline bold words."

    prompt = (
        prompt_template
        .replace("{{JOB_DESCRIPTION}}", job_description.strip())
        .replace("{{HEADER_JSON}}", json.dumps(header))
        .replace("{{SECTIONS_JSON}}", json.dumps(sections))
        .replace("{{PREVIOUS_RESUMES_BLOCK}}", previous_resumes_block)
        .replace("{{BOLD_RULE}}", bold_rule)
    )

    last_error = None
    response_text = ""
    used_model = None

    for model_name in MODELS_TO_TRY:
        try:
            print(f"[Wiser JD-ATS Help] Executing Wiser AI query...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            response_text = response.text.strip()
            if response_text:
                used_model = "Wiser AI"
                break
        except Exception as e:
            print(f"[Wiser JD-ATS Help] Attempt failed: {e}")
            last_error = e

    if not response_text:
        raise RuntimeError(f"Wiser AI analysis failed: {last_error}")

    response_text = _clean_markdown_json(response_text)

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as jde:
        print(f"[Wiser JD-ATS Help] JSON parse error: {jde}\nResponse text: {response_text[:300]}")
        raise ValueError(f"AI returned invalid JSON: {jde}")

    data["_ai_model"] = used_model
    return data


def analyze_standalone_ats(
    current_resume: Dict[str, Any],
    allow_bold_text: bool = False
) -> Dict[str, Any]:
    """
    Performs standalone 'Wiser ATS' audit on a resume without requiring a Job Description.
    Audits parseability, power action verbs, quantified metric density, and industry keyword depth.
    """
    client = _get_gemini_client()

    header = current_resume.get("header_json") or current_resume.get("header") or {}
    sections = current_resume.get("sections_json") or current_resume.get("sections") or []

    prompt_file_path = os.path.join(os.path.dirname(__file__), "prompts", "wiser_ats.prompt")
    with open(prompt_file_path, "r", encoding="utf-8") as pf:
        prompt_template = pf.read()

    if allow_bold_text:
        bold_rule = "Use bold <strong> tags sparingly for keywords and metrics in enhanced_html."
    else:
        bold_rule = "DO NOT include any <strong> or <b> tags in enhanced_html. Keep enhanced bullets clean and unbolded."

    prompt = (
        prompt_template
        .replace("{{HEADER_JSON}}", json.dumps(header))
        .replace("{{SECTIONS_JSON}}", json.dumps(sections))
        .replace("{{BOLD_RULE}}", bold_rule)
    )

    last_error = None
    response_text = ""
    used_model = None

    for model_name in MODELS_TO_TRY:
        try:
            print(f"[Wiser Standalone ATS] Executing Wiser AI query...")
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            response_text = response.text.strip()
            if response_text:
                used_model = "Wiser AI"
                break
        except Exception as e:
            print(f"[Wiser Standalone ATS] Attempt failed: {e}")
            last_error = e

    if not response_text:
        raise RuntimeError(f"Wiser AI standalone ATS analysis failed: {last_error}")

    response_text = _clean_markdown_json(response_text)

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as jde:
        print(f"[Wiser Standalone ATS] JSON parse error: {jde}\nResponse text: {response_text[:300]}")
        raise ValueError(f"AI returned invalid JSON: {jde}")

    data["_ai_model"] = used_model
    return data
