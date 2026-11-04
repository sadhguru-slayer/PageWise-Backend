import json
import re
from typing import Any, Dict, List, Optional

from .wiser_runtime import (
    async_generate_json,
    compact_previous_resumes,
    compact_resume,
    extract_plain_text,
    generate_json,
    load_prompt,
)


def _extract_text_corpus(current_resume: Any) -> str:
    """Extract plain text of entire current resume for factual verification."""
    if not current_resume:
        return ""
    if isinstance(current_resume, str):
        return extract_plain_text(current_resume)

    texts = []
    # Support dict or ORM objects
    if isinstance(current_resume, dict):
        header = current_resume.get("header_json") or current_resume.get("header") or {}
        sections = current_resume.get("sections_json") or current_resume.get("sections") or []
    else:
        header = getattr(current_resume, "header_json", None) or getattr(current_resume, "header", None) or {}
        sections = getattr(current_resume, "sections_json", None) or getattr(current_resume, "sections", None) or []

    if isinstance(header, str):
        try:
            header = json.loads(header)
        except Exception:
            header = {}
    if isinstance(header, dict):
        for v in header.values():
            if isinstance(v, str):
                texts.append(v)

    if isinstance(sections, str):
        try:
            sections = json.loads(sections)
        except Exception:
            sections = []
    if isinstance(sections, list):
        for sec in sections:
            if isinstance(sec, dict):
                raw = sec.get("content") or sec.get("contentHtml") or ""
                texts.append(extract_plain_text(raw))
            elif hasattr(sec, "content"):
                texts.append(extract_plain_text(getattr(sec, "content", "")))
    return " ".join(texts)


def _verify_and_sanitize_analysis(
    data: Dict[str, Any],
    current_resume: Any,
    job_description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Independent verification layer:
    1. Checks every AI suggestion against the source resume.
    2. Filters out suggestions targeting bullets that user has already removed.
    3. Flags any newly introduced numbers, metrics, or claims that have no basis in the source document.
    4. Deterministically reconciles matched vs missing keywords against source resume and JD text.
    """
    if not isinstance(data, dict):
        return data

    source_corpus = _extract_text_corpus(current_resume)
    source_corpus_lower = source_corpus.lower()
    source_numbers = set(re.findall(r"\b(?:\$?\d+(?:\.\d+)?%?|\d+[kKmMbB]\+?)\b", source_corpus))

    enhancements = data.get("section_enhancements", [])
    if isinstance(enhancements, list):
        for sec in enhancements:
            if not isinstance(sec, dict):
                continue
            suggestions = sec.get("suggestions", [])
            if not isinstance(suggestions, list):
                continue
            valid_suggestions = []
            expanded_suggestions = []
            for raw_sug in suggestions:
                if not isinstance(raw_sug, dict):
                    continue
                raw_enhanced = raw_sug.get("enhanced_html") or ""
                # Check if model returned multiple <li> tags in one suggestion
                li_matches = re.findall(r"<li[^>]*>(.*?)</li>", raw_enhanced, re.DOTALL | re.IGNORECASE)
                if len(li_matches) > 1:
                    # Model merged multiple points into 1 suggestion! Split into discrete 1-to-1 suggestions
                    for sub_idx, li_content in enumerate(li_matches):
                        cloned = dict(raw_sug)
                        cloned["id"] = f"{raw_sug.get('id', 'sug')}-{sub_idx}"
                        cloned["enhanced_html"] = f"<li>{li_content.strip()}</li>"
                        expanded_suggestions.append(cloned)
                else:
                    expanded_suggestions.append(raw_sug)

            for sug in expanded_suggestions:
                orig = (sug.get("original_text") or "").strip()
                orig_clean = re.sub(r"<[^>]+>", " ", orig).strip().lower()

                # If suggestion targets an existing bullet, verify the bullet is actually in current resume.
                # If user removed this point, discard the suggestion so it does not resurrect.
                if orig_clean and len(orig_clean) >= 15:
                    orig_tokens = set(re.findall(r"\b\w{3,}\b", orig_clean))
                    if orig_tokens and not (orig_clean in source_corpus_lower):
                        matched_tokens = [tok for tok in orig_tokens if tok in source_corpus_lower]
                        overlap_ratio = len(matched_tokens) / len(orig_tokens) if orig_tokens else 0
                        if overlap_ratio < 0.40:
                            print(f"[Wiser Filter] Discarding suggestion for removed bullet: '{orig[:40]}...'")
                            continue

                valid_suggestions.append(sug)
                enhanced = (sug.get("enhanced_html") or "").strip()

                # Ensure bullet format (<li>) for experience and projects or list-like originals
                sec_title_lower = (sec.get("section_title") or "").lower()
                is_list_section = any(k in sec_title_lower for k in ["experience", "work", "employment", "project", "leadership", "volunteer", "activity"])
                looks_like_bullet = orig.startswith("<li") or orig.startswith("•") or orig.startswith("-") or orig.startswith("*")

                if (is_list_section or looks_like_bullet) and enhanced:
                    if enhanced.startswith("<p>") and enhanced.endswith("</p>"):
                        inner = enhanced[3:-4].strip()
                        enhanced = f"<li>{inner}</li>"
                        sug["enhanced_html"] = enhanced
                    elif not enhanced.startswith("<li"):
                        enhanced = f"<li>{enhanced}</li>"
                        sug["enhanced_html"] = enhanced

                clean_enhanced = re.sub(r"<[^>]+>", " ", enhanced).strip()

                # Extract metric tokens from suggestion
                enhanced_numbers = set(re.findall(r"\b(?:\$?\d+(?:\.\d+)?%?|\d+[kKmMbB]\+?)\b", clean_enhanced))
                orig_numbers = set(re.findall(r"\b(?:\$?\d+(?:\.\d+)?%?|\d+[kKmMbB]\+?)\b", orig))

                # New numbers not in the original bullet nor in the resume source
                new_metrics = (enhanced_numbers - orig_numbers) - source_numbers
                # Filter out single-digit generic numbers (like '1', '2')
                substantive_new_metrics = [m for m in new_metrics if not (len(m) == 1 and m.isdigit())]

                missing_info = sug.get("missing_information") or []
                if not isinstance(missing_info, list):
                    missing_info = []

                if substantive_new_metrics:
                    sug["verification_status"] = "needs_confirmation"
                    sug["factual_risk"] = "high"
                    sug["user_confirmation_required"] = True
                    sug["change_type"] = "factual_addition"
                    for m in substantive_new_metrics:
                        prompt_q = f"Confirm whether you achieved '{m}' or provide your actual figure."
                        if prompt_q not in missing_info:
                            missing_info.append(prompt_q)
                    sug["missing_information"] = missing_info
                else:
                    sug.setdefault("verification_status", "supported")
                    sug.setdefault("factual_risk", "low")
                    sug.setdefault("user_confirmation_required", False)
                    sug.setdefault("change_type", "wording")
                    sug.setdefault("missing_information", [])

                sug.setdefault("evidence_source", "current_resume" if orig else "role_clarification")

            sec["suggestions"] = valid_suggestions

    # Deterministic keyword reconciliation against actual resume and JD
    ats_check = data.get("ats_check")
    if isinstance(ats_check, dict):
        source_corpus_lower = source_corpus.lower()
        jd_lower = (job_description or "").lower() if job_description else ""

        raw_matched = ats_check.get("matched_keywords") or []
        raw_missing = ats_check.get("missing_keywords") or []
        raw_recommended = ats_check.get("recommended_keywords") or []

        reconciled_matched = []
        for kw in raw_matched:
            if isinstance(kw, str) and kw.strip():
                reconciled_matched.append(kw.strip())

        reconciled_missing = []
        for kw in raw_missing:
            if not isinstance(kw, str) or not kw.strip():
                continue
            k_clean = kw.strip()
            k_lower = k_clean.lower()
            pattern = rf"\b{re.escape(k_lower)}\b"

            # If keyword already exists in candidate's resume, it is NOT missing!
            if re.search(pattern, source_corpus_lower) or k_lower in source_corpus_lower:
                if k_clean not in reconciled_matched:
                    reconciled_matched.append(k_clean)
            else:
                # If JD is present, verify term is actually in the JD
                if jd_lower:
                    if re.search(pattern, jd_lower) or k_lower in jd_lower:
                        reconciled_missing.append(k_clean)
                else:
                    reconciled_missing.append(k_clean)

        reconciled_recommended = []
        for kw in raw_recommended:
            if not isinstance(kw, str) or not kw.strip():
                continue
            k_clean = kw.strip()
            k_lower = k_clean.lower()
            pattern = rf"\b{re.escape(k_lower)}\b"
            if re.search(pattern, source_corpus_lower) or k_lower in source_corpus_lower:
                if k_clean not in reconciled_matched:
                    reconciled_matched.append(k_clean)
            else:
                reconciled_recommended.append(k_clean)

        ats_check["matched_keywords"] = list(dict.fromkeys(reconciled_matched))
        if "missing_keywords" in ats_check:
            ats_check["missing_keywords"] = list(dict.fromkeys(reconciled_missing))
        if "recommended_keywords" in ats_check:
            ats_check["recommended_keywords"] = list(dict.fromkeys(reconciled_recommended))

        ats_check.setdefault(
            "evaluation_disclosure",
            "This assessment evaluates common resume quality, parseability, and role alignment. It is not an employer's proprietary ATS score and does not guarantee interview shortlisting."
        )

    return data


def _build_jd_prompt(
    job_description: str,
    current_resume: Dict[str, Any],
    previous_resumes: Optional[List[Dict[str, Any]]] = None,
    allow_bold_text: bool = True
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
    allow_bold_text: bool = True
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
    allow_bold_text: bool = True
) -> Dict[str, Any]:
    """
    Non-blocking async Job Description matching + ATS check + bullet enhancements.
    """
    prompt = _build_jd_prompt(job_description, current_resume, previous_resumes, allow_bold_text)
    print("[Wiser JD-ATS Help] Executing async Wiser AI query...")
    data = await async_generate_json(prompt, temperature=0.0, task="jd")
    data["_ai_model"] = "Wiser AI"
    return _verify_and_sanitize_analysis(data, current_resume, job_description)


def analyze_jd_and_ats(
    job_description: str,
    current_resume: Dict[str, Any],
    previous_resumes: Optional[List[Dict[str, Any]]] = None,
    allow_bold_text: bool = True
) -> Dict[str, Any]:
    """
    Synchronous Job Description matching + ATS check + bullet enhancements.
    """
    prompt = _build_jd_prompt(job_description, current_resume, previous_resumes, allow_bold_text)
    print("[Wiser JD-ATS Help] Executing sync Wiser AI query...")
    data = generate_json(prompt, temperature=0.0, task="jd")
    data["_ai_model"] = "Wiser AI"
    return _verify_and_sanitize_analysis(data, current_resume, job_description)


async def async_analyze_standalone_ats(
    current_resume: Dict[str, Any],
    allow_bold_text: bool = True
) -> Dict[str, Any]:
    """
    Non-blocking async standalone ATS audit without a job description.
    """
    prompt = _build_ats_prompt(current_resume, allow_bold_text)
    print("[Wiser Standalone ATS] Executing async Wiser AI query...")
    data = await async_generate_json(prompt, temperature=0.0, task="jd")
    data["_ai_model"] = "Wiser AI"
    return _verify_and_sanitize_analysis(data, current_resume)


def analyze_standalone_ats(
    current_resume: Dict[str, Any],
    allow_bold_text: bool = True
) -> Dict[str, Any]:
    """
    Synchronous standalone ATS audit without a job description.
    """
    prompt = _build_ats_prompt(current_resume, allow_bold_text)
    print("[Wiser Standalone ATS] Executing sync Wiser AI query...")
    data = generate_json(prompt, temperature=0.0, task="jd")
    data["_ai_model"] = "Wiser AI"
    return _verify_and_sanitize_analysis(data, current_resume)
