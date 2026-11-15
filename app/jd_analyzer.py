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
                if raw:
                    texts.append(extract_plain_text(raw))
                items = sec.get("items") or []
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict):
                            for key in ["title", "company", "role", "project_title", "institution", "summary", "name", "issuer", "category"]:
                                val = it.get(key)
                                if isinstance(val, str) and val.strip():
                                    texts.append(val.strip())
                            pts = it.get("points") or []
                            if isinstance(pts, list):
                                for p in pts:
                                    if isinstance(p, str) and p.strip():
                                        texts.append(p.strip())
                            skills = it.get("skills") or []
                            if isinstance(skills, list):
                                for s in skills:
                                    if isinstance(s, str) and s.strip():
                                        texts.append(s.strip())
            elif hasattr(sec, "content"):
                texts.append(extract_plain_text(getattr(sec, "content", "")))
    return " ".join(texts)


def _verify_and_sanitize_analysis(
    data: Dict[str, Any],
    current_resume: Any,
    job_description: Optional[str] = None,
    applied_bullet_ids: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Independent verification layer:
    1. Checks every AI suggestion against the source resume.
    2. Filters out suggestions targeting bullets that user has already removed or already enhanced.
    3. Flags any newly introduced numbers, metrics, or claims that have no basis in the source document.
    4. Deterministically reconciles matched vs missing keywords against source resume and JD text.
    5. Prevents stochastic score regression after user applies recommended enhancements.
    """
    if not isinstance(data, dict):
        return data

    source_corpus = _extract_text_corpus(current_resume)
    source_corpus_lower = source_corpus.lower()
    source_numbers = set(re.findall(r"\b(?:\$?\d+(?:\.\d+)?%?|\d+[kKmMbB]\+?)\b", source_corpus))

    applied_set = set(str(k) for k in (applied_bullet_ids or []))
    if not applied_set and isinstance(current_resume, dict):
        applied_set = set(str(k) for k in (current_resume.get("applied_bullet_ids") or current_resume.get("applied_suggestion_keys") or []))

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

            seen_targets = set()
            seen_enhanced = set()
            for sug in expanded_suggestions:
                orig = (sug.get("original_text") or "").strip()
                if orig.startswith("[ALREADY_ENHANCED]"):
                    orig = orig.replace("[ALREADY_ENHANCED]", "").strip()
                    sug["original_text"] = orig

                orig_clean = re.sub(r"<[^>]+>", " ", orig).strip().lower()

                raw_enh = (sug.get("enhanced_html") or "").strip()
                if "[ALREADY_ENHANCED]" in raw_enh:
                    raw_enh = raw_enh.replace("[ALREADY_ENHANCED]", "").strip()
                    sug["enhanced_html"] = raw_enh

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

                # Target identifier
                target_key = None
                item_id = sug.get("item_id") or sug.get("target_item_id")
                point_idx = sug.get("point_index")
                if item_id is not None and point_idx is not None:
                    target_key = f"{item_id}:{point_idx}"
                elif orig_clean:
                    target_key = f"text:{orig_clean[:60]}"

                # Filter out suggestions targeting bullets that user has ALREADY enhanced!
                if target_key and (
                    target_key in applied_set
                    or (item_id and str(item_id) in applied_set)
                    or (sug.get("id") and str(sug.get("id")) in applied_set)
                ):
                    print(f"[Wiser Filter] Discarding suggestion for already enhanced bullet ({target_key})")
                    continue

                # Deduplication check: at most one suggestion per target bullet point
                if target_key and target_key in seen_targets:
                    print(f"[Wiser Filter] Discarding duplicate suggestion targeting same bullet ({target_key})")
                    continue

                clean_enh = re.sub(r"<[^>]+>", " ", raw_enh).strip().lower()
                if clean_enh and clean_enh in seen_enhanced:
                    print(f"[Wiser Filter] Discarding duplicate enhancement text: {clean_enh[:40]}")
                    continue

                # Filter out cosmetic / bold-only / identical suggestions
                orig_no_tags = re.sub(r"<[^>]+>", " ", orig).strip().lower()
                enh_no_tags = re.sub(r"<[^>]+>", " ", raw_enh).strip().lower()
                orig_words = re.findall(r"\b\w+\b", orig_no_tags)
                enh_words = re.findall(r"\b\w+\b", enh_no_tags)
                if orig_words and orig_words == enh_words:
                    print(f"[Wiser Filter] Discarding cosmetic/bold-only suggestion with identical words: '{orig[:40]}...'")
                    continue

                if target_key:
                    seen_targets.add(target_key)
                if clean_enh:
                    seen_enhanced.add(clean_enh)

                valid_suggestions.append(sug)
                enhanced = raw_enh

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
                sug.setdefault("relevance_to_role", sug.get("relevance_to_role") or sug.get("reasoning") or "")

            sec["suggestions"] = valid_suggestions

    # ── Deterministic, Industry-Standard Python ATS Evaluation ──
    from .ats_scorer import compute_legit_ats_evaluation

    legit_ats = compute_legit_ats_evaluation(
        current_resume=current_resume if isinstance(current_resume, dict) else {},
        ai_data=data,
        job_description=job_description
    )
    data["ats_check"] = legit_ats

    return data


def _build_jd_prompt(
    job_description: str,
    current_resume: Dict[str, Any],
    previous_resumes: Optional[List[Dict[str, Any]]] = None,
    allow_bold_text: bool = True,
    applied_bullet_ids: Optional[Any] = None
) -> str:
    compact = compact_resume(current_resume, applied_bullet_ids=applied_bullet_ids)
    previous_resumes_block = compact_previous_resumes(previous_resumes, limit=2)
    prompt_template = load_prompt("jd_analyzer.prompt")

    if allow_bold_text:
        bold_rule = "Use bold <strong> tags sparingly for keywords and metrics in enhanced_html. NEVER suggest a bullet change whose only modification is wrapping existing terms in bold tags."
    else:
        bold_rule = "STRICT BAN ON BOLD TAGS: DO NOT include any <strong> or <b> tags in enhanced_html. Bullets must be clean plain text inside <li>...</li>."

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
    allow_bold_text: bool = True,
    applied_bullet_ids: Optional[Any] = None
) -> str:
    compact = compact_resume(current_resume, applied_bullet_ids=applied_bullet_ids)
    prompt_template = load_prompt("wiser_ats.prompt")

    if allow_bold_text:
        bold_rule = "Use bold <strong> tags sparingly for keywords and metrics in enhanced_html. NEVER suggest a bullet change whose only modification is wrapping existing terms in bold tags."
    else:
        bold_rule = "STRICT BAN ON BOLD TAGS: DO NOT include any <strong> or <b> tags in enhanced_html. Bullets must be clean plain text inside <li>...</li>."

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
    allow_bold_text: bool = True,
    applied_bullet_ids: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Non-blocking async Job Description matching + ATS check + bullet enhancements.
    """
    prompt = _build_jd_prompt(job_description, current_resume, previous_resumes, allow_bold_text, applied_bullet_ids=applied_bullet_ids)
    print("[Wiser JD-ATS Help] Executing async Wiser AI query...")
    data = await async_generate_json(prompt, temperature=0.0, task="jd")
    data["_ai_model"] = "Wiser AI"
    return _verify_and_sanitize_analysis(data, current_resume, job_description, applied_bullet_ids=applied_bullet_ids)


def analyze_jd_and_ats(
    job_description: str,
    current_resume: Dict[str, Any],
    previous_resumes: Optional[List[Dict[str, Any]]] = None,
    allow_bold_text: bool = True,
    applied_bullet_ids: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Synchronous Job Description matching + ATS check + bullet enhancements.
    """
    prompt = _build_jd_prompt(job_description, current_resume, previous_resumes, allow_bold_text, applied_bullet_ids=applied_bullet_ids)
    print("[Wiser JD-ATS Help] Executing sync Wiser AI query...")
    data = generate_json(prompt, temperature=0.0, task="jd")
    data["_ai_model"] = "Wiser AI"
    return _verify_and_sanitize_analysis(data, current_resume, job_description, applied_bullet_ids=applied_bullet_ids)


async def async_analyze_standalone_ats(
    current_resume: Dict[str, Any],
    allow_bold_text: bool = True,
    applied_bullet_ids: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Non-blocking async standalone ATS audit without a job description.
    """
    prompt = _build_ats_prompt(current_resume, allow_bold_text, applied_bullet_ids=applied_bullet_ids)
    print("[Wiser Standalone ATS] Executing async Wiser AI query...")
    data = await async_generate_json(prompt, temperature=0.0, task="jd")
    data["_ai_model"] = "Wiser AI"
    return _verify_and_sanitize_analysis(data, current_resume, applied_bullet_ids=applied_bullet_ids)


def analyze_standalone_ats(
    current_resume: Dict[str, Any],
    allow_bold_text: bool = True,
    applied_bullet_ids: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Synchronous standalone ATS audit without a job description.
    """
    prompt = _build_ats_prompt(current_resume, allow_bold_text, applied_bullet_ids=applied_bullet_ids)
    print("[Wiser Standalone ATS] Executing sync Wiser AI query...")
    data = generate_json(prompt, temperature=0.0, task="jd")
    data["_ai_model"] = "Wiser AI"
    return _verify_and_sanitize_analysis(data, current_resume, applied_bullet_ids=applied_bullet_ids)
