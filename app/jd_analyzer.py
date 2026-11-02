import json
from typing import Any, Dict, List, Optional

from .wiser_runtime import (
    async_generate_json,
    compact_previous_resumes,
    compact_resume,
    generate_json,
    load_prompt,
)


def _build_jd_prompt(
    job_description: str,
    current_resume: Dict[str, Any],
    previous_resumes: Optional[List[Dict[str, Any]]] = None,
    allow_bold_text: bool = False
) -> str:
    compact = compact_resume(current_resume)
    previous_resumes_block = compact_previous_resumes(previous_resumes, limit=2)
    prompt_template = load_prompt("jd_analyzer.prompt")

    if allow_bold_text:
        bold_rule = "Use bold <strong> tags sparingly for keywords and metrics in enhanced_html."
    else:
        bold_rule = "DO NOT include any <strong> or <b> tags in enhanced_html. Keep enhanced bullets clean and unbolded, as professional resumes do not use inline bold words."

    jd_text = (job_description or "").strip()
    if len(jd_text) > 12000:
        jd_text = jd_text[:12000] + "\n[truncated]"

    return (
        prompt_template
        .replace("{{JOB_DESCRIPTION}}", jd_text)
        .replace("{{HEADER_JSON}}", json.dumps(compact.get("header_json") or {}))
        .replace("{{SECTIONS_JSON}}", json.dumps(compact.get("sections_json") or []))
        .replace("{{PREVIOUS_RESUMES_BLOCK}}", previous_resumes_block)
        .replace("{{BOLD_RULE}}", bold_rule)
    )


def _build_ats_prompt(
    current_resume: Dict[str, Any],
    allow_bold_text: bool = False
) -> str:
    compact = compact_resume(current_resume)
    prompt_template = load_prompt("wiser_ats.prompt")

    if allow_bold_text:
        bold_rule = "Use bold <strong> tags sparingly for keywords and metrics in enhanced_html."
    else:
        bold_rule = "DO NOT include any <strong> or <b> tags in enhanced_html. Keep enhanced bullets clean and unbolded."

    return (
        prompt_template
        .replace("{{HEADER_JSON}}", json.dumps(compact.get("header_json") or {}))
        .replace("{{SECTIONS_JSON}}", json.dumps(compact.get("sections_json") or []))
        .replace("{{BOLD_RULE}}", bold_rule)
    )


async def async_analyze_jd_and_ats(
    job_description: str,
    current_resume: Dict[str, Any],
    previous_resumes: Optional[List[Dict[str, Any]]] = None,
    allow_bold_text: bool = False
) -> Dict[str, Any]:
    """
    Non-blocking async Job Description matching + ATS check + bullet enhancements.
    """
    prompt = _build_jd_prompt(job_description, current_resume, previous_resumes, allow_bold_text)
    print("[Wiser JD-ATS Help] Executing async Wiser AI query...")
    data = await async_generate_json(prompt, temperature=0.2)
    data["_ai_model"] = "Wiser AI"
    return data


def analyze_jd_and_ats(
    job_description: str,
    current_resume: Dict[str, Any],
    previous_resumes: Optional[List[Dict[str, Any]]] = None,
    allow_bold_text: bool = False
) -> Dict[str, Any]:
    """
    Synchronous Job Description matching + ATS check + bullet enhancements.
    """
    prompt = _build_jd_prompt(job_description, current_resume, previous_resumes, allow_bold_text)
    print("[Wiser JD-ATS Help] Executing sync Wiser AI query...")
    data = generate_json(prompt, temperature=0.2)
    data["_ai_model"] = "Wiser AI"
    return data


async def async_analyze_standalone_ats(
    current_resume: Dict[str, Any],
    allow_bold_text: bool = False
) -> Dict[str, Any]:
    """
    Non-blocking async standalone ATS audit without a job description.
    """
    prompt = _build_ats_prompt(current_resume, allow_bold_text)
    print("[Wiser Standalone ATS] Executing async Wiser AI query...")
    data = await async_generate_json(prompt, temperature=0.2)
    data["_ai_model"] = "Wiser AI"
    return data


def analyze_standalone_ats(
    current_resume: Dict[str, Any],
    allow_bold_text: bool = False
) -> Dict[str, Any]:
    """
    Synchronous standalone ATS audit without a job description.
    """
    prompt = _build_ats_prompt(current_resume, allow_bold_text)
    print("[Wiser Standalone ATS] Executing sync Wiser AI query...")
    data = generate_json(prompt, temperature=0.2)
    data["_ai_model"] = "Wiser AI"
    return data
