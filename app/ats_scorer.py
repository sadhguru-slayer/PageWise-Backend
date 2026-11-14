"""
Deterministic ATS Scoring & Resume Audit Engine
-----------------------------------------------
Implements industry-standard applicant tracking system (ATS) heuristics
used by enterprise scanners (e.g. Jobscan, Resume Worded, Workday parseability).

Architecture:
- Python Deterministic Parsing: Scores header parseability, section structure,
  action verb density, quantified impact metrics, and keyword match ratios.
- AI Passively: AI generates suggestions, JD requirement decomposition, and
  qualitative feedback; Python computes the actual, legit ATS scores.
"""

import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple


# ─── Standard Action Verbs (Industry Standard ATS Dictionary) ──────────────────
STRONG_ACTION_VERBS = {
    # Leadership & Architecture
    "architected", "spearheaded", "orchestrated", "engineered", "pioneered",
    "founded", "directed", "steered", "mentored", "coached", "championed",
    "scaled", "overhauled", "restructured", "centralized", "governed",
    # Development & Implementation
    "developed", "built", "designed", "implemented", "deployed", "programmed",
    "coded", "configured", "integrated", "constructed", "created", "executed",
    "formulated", "established", "instituted", "launched", "migrated",
    # Optimization & Performance
    "optimized", "streamlined", "accelerated", "boosted", "maximized",
    "minimized", "reduced", "automated", "enhanced", "upgraded", "revamped",
    "refactored", "debugged", "troubleshot", "resolved", "consolidated",
    # Analysis & Research
    "analyzed", "benchmarked", "evaluated", "quantified", "audited", "surveyed",
    "modelled", "investigated", "diagnosed", "forecasted", "assessed",
    # Delivery & Operations
    "delivered", "maintained", "administered", "published", "secured",
    "monitored", "managed", "coordinated", "collaborated", "facilitated",
    # Present Tense (for current roles)
    "architect", "engineer", "lead", "scale", "develop", "build", "design",
    "implement", "deploy", "optimize", "automate", "enhance", "deliver",
    "manage", "maintain", "direct", "analyze", "integrate"
}

WEAK_PASSIVE_STARTERS = [
    r"\bresponsible for\b",
    r"\btasked with\b",
    r"\bworked on\b",
    r"\bhelped (?:to|with)\b",
    r"\bassisted (?:in|with)\b",
    r"\bduties included\b",
    r"\binvolved in\b",
    r"\bparticipated in\b",
    r"\bhandled daily\b",
]

# Common Technical Synonyms & Abbreviations for ATS Matching
TECH_ALIASES = {
    "k8s": "kubernetes",
    "kube": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "postgres": "postgresql",
    "pg": "postgresql",
    "mongo": "mongodb",
    "react": "reactjs",
    "react.js": "reactjs",
    "node": "nodejs",
    "node.js": "nodejs",
    "vue": "vuejs",
    "vue.js": "vuejs",
    "aws": "amazon web services",
    "gcp": "google cloud platform",
    "azure": "microsoft azure",
    "ci/cd": "cicd",
    "ci-cd": "cicd",
    "continuous integration": "cicd",
    "continuous deployment": "cicd",
    "rest": "restful",
    "rest api": "restful apis",
    "rest apis": "restful apis",
    "graphql": "graphql",
    "docker": "docker containerization",
    "containers": "containerization",
    "k8": "kubernetes",
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "nlp": "natural language processing",
    "llm": "large language models",
    "llms": "large language models",
}


def normalize_keyword(kw: str) -> str:
    """Normalizes keyword for robust matching (lowercase, strip punctuation, alias substitution)."""
    if not kw:
        return ""
    clean = re.sub(r"[^\w\s\-\/\.]", " ", str(kw).lower()).strip()
    clean = re.sub(r"\s+", " ", clean)
    return TECH_ALIASES.get(clean, clean)


def extract_bullet_texts(resume: Dict[str, Any]) -> List[str]:
    """Extracts all discrete bullet points across experience, education, projects, etc."""
    bullets = []
    sections = resume.get("sections_json") or resume.get("sections") or []
    if isinstance(sections, str):
        try:
            import json
            sections = json.loads(sections)
        except Exception:
            sections = []

    for sec in sections or []:
        if not isinstance(sec, dict):
            continue
        # 1. Structured items
        items = sec.get("items") or []
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    pts = it.get("points") or []
                    if isinstance(pts, list):
                        for p in pts:
                            if isinstance(p, str) and p.strip():
                                clean = re.sub(r"<[^>]+>", " ", p).strip()
                                if clean:
                                    bullets.append(clean)
        # 2. Rich text content fallback
        content_html = sec.get("contentHtml") or sec.get("content") or ""
        if isinstance(content_html, str) and content_html:
            li_matches = re.findall(r"<li[^>]*>(.*?)</li>", content_html, re.DOTALL | re.IGNORECASE)
            for li in li_matches:
                clean = re.sub(r"<[^>]+>", " ", li).strip()
                if clean:
                    bullets.append(clean)

    return bullets


def extract_full_text(resume: Dict[str, Any]) -> str:
    """Extracts full textual corpus of the resume."""
    parts = []
    header = resume.get("header_json") or resume.get("header") or {}
    if isinstance(header, dict):
        for v in header.values():
            if isinstance(v, str):
                parts.append(v)

    sections = resume.get("sections_json") or resume.get("sections") or []
    if isinstance(sections, list):
        for sec in sections:
            if isinstance(sec, dict):
                parts.append(sec.get("title") or "")
                raw = sec.get("content") or sec.get("contentHtml") or ""
                if isinstance(raw, str):
                    parts.append(re.sub(r"<[^>]+>", " ", raw))
                items = sec.get("items") or []
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict):
                            for k in ["title", "company", "role", "project_title", "institution", "summary", "name", "issuer", "category"]:
                                v = it.get(k)
                                if isinstance(v, str):
                                    parts.append(v)
                            for pt in it.get("points") or []:
                                if isinstance(pt, str):
                                    parts.append(pt)
                            for s in it.get("skills") or []:
                                if isinstance(s, str):
                                    parts.append(s)
    return " ".join(parts).lower()


# ─── Pillar 1: Structure & Parseability Audit ──────────────────────────────────
def audit_structure_and_parseability(resume: Dict[str, Any]) -> Tuple[int, List[str]]:
    """
    Evaluates document hierarchy, contact information, standard headings, and dates.
    Returns (score: 0-100, suggestions: List[str]).
    """
    score = 0
    feedback = []
    header = resume.get("header_json") or resume.get("header") or {}
    if not isinstance(header, dict):
        header = {}

    # 1. Contact Information Checks (Max 35 pts)
    # Name (+10)
    name = (header.get("name") or header.get("fullName") or "").strip()
    if len(name) >= 2:
        score += 10
    else:
        feedback.append("Missing full candidate name in resume header.")

    # Email (+10)
    email = (header.get("email") or "").strip()
    if email and re.search(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$", email):
        score += 10
    else:
        feedback.append("Valid professional email address not detected.")

    # Phone (+5)
    phone = (header.get("phone") or "").strip()
    if phone and len(re.sub(r"\D", "", phone)) >= 7:
        score += 5
    else:
        feedback.append("Contact phone number missing or incomplete.")

    # Location (+5)
    location = (header.get("location") or header.get("city") or header.get("address") or "").strip()
    if len(location) >= 3:
        score += 5
    else:
        feedback.append("Geographic location/city missing from header.")

    # Links (+5)
    links = (header.get("links") or header.get("linkedin") or header.get("github") or header.get("website") or "")
    if links:
        score += 5
    else:
        feedback.append("LinkedIn or portfolio link recommended in header.")

    # 2. Standard Section Headings (Max 35 pts)
    sections = resume.get("sections_json") or resume.get("sections") or []
    sec_titles = []
    for s in sections or []:
        if isinstance(s, dict):
            sec_titles.append((s.get("title") or "").lower().strip())

    combined_titles = " ".join(sec_titles)
    has_exp = any(k in combined_titles for k in ["experience", "work", "employment", "career", "history"])
    has_edu = any(k in combined_titles for k in ["education", "academic", "university", "college", "degree"])
    has_skills = any(k in combined_titles for k in ["skill", "technolog", "competenc", "stack"])
    has_proj_or_summary = any(k in combined_titles for k in ["project", "summary", "portfolio", "about", "profile"])

    if has_exp:
        score += 15
    else:
        feedback.append("Work Experience section heading not recognized.")

    if has_edu:
        score += 10
    else:
        feedback.append("Education section heading not recognized.")

    if has_skills:
        score += 5
    else:
        feedback.append("Dedicated Skills section heading missing.")

    if has_proj_or_summary:
        score += 5

    # 3. Bullet & Date Organization (Max 30 pts)
    bullets = extract_bullet_texts(resume)
    total_bullets = len(bullets)

    if total_bullets >= 4 and total_bullets <= 28:
        score += 15
    elif total_bullets > 0:
        score += 8
    else:
        feedback.append("Few or no discrete bullet points detected in experience or projects.")

    # Date presence check in structured items
    items_count = 0
    items_with_dates = 0
    for s in sections or []:
        if isinstance(s, dict):
            for it in s.get("items") or []:
                if isinstance(it, dict):
                    items_count += 1
                    if (it.get("start_date") or it.get("end_date") or it.get("date")):
                        items_with_dates += 1

    if items_count > 0:
        date_ratio = items_with_dates / items_count
        score += int(date_ratio * 15)
        if date_ratio < 0.60:
            feedback.append("Ensure reverse-chronological employment dates are clearly specified.")
    else:
        score += 10

    return min(max(score, 20), 100), feedback


# ─── Pillar 2: Content Specificity & Action Verbs Audit ────────────────────────
def audit_content_and_impact(resume: Dict[str, Any]) -> Tuple[int, int, List[str]]:
    """
    Evaluates action verb strength and quantifiable metric density in bullet points.
    Returns (specificity_score: 0-100, impact_score: 0-100, feedback: List[str]).
    """
    bullets = extract_bullet_texts(resume)
    feedback = []
    if not bullets:
        return 50, 40, ["Add bullet points detailing measurable achievements in your positions."]

    total = len(bullets)
    action_verb_count = 0
    metric_count = 0
    passive_phrase_count = 0

    metric_regex = re.compile(
        r"(?:\$?\d+(?:\.\d+)?%?|\b\d+[kKmMbB]\+?|\b\d+\s*(?:users?|customers?|clients?|requests?|transactions?|ms|seconds?|hours?|days?|engineers?|teams?|projects?)\b|\b(?:increased|decreased|reduced|saved|grew|accelerated)\b[^\n\.\,]*?\b\d+)",
        re.IGNORECASE
    )

    for b in bullets:
        clean = b.strip()
        words = re.findall(r"\b[A-Za-z\-]+\b", clean)
        if not words:
            continue
        first_word = words[0].lower()

        # Action verb check
        if first_word in STRONG_ACTION_VERBS:
            action_verb_count += 1
        elif len(words) > 1 and words[1].lower() in STRONG_ACTION_VERBS:
            # Handles adverb prefixes like "Successfully designed" or "Consistently led"
            action_verb_count += 1

        # Passive phrase check
        b_lower = clean.lower()
        if any(re.search(pat, b_lower) for pat in WEAK_PASSIVE_STARTERS):
            passive_phrase_count += 1

        # Metrics & quantifiable impact check
        if metric_regex.search(clean):
            metric_count += 1

    # Compute Action Verb Score (0 - 100)
    verb_ratio = action_verb_count / total
    passive_ratio = passive_phrase_count / total

    # 80%+ action verbs is exemplary
    specificity_raw = int((verb_ratio * 90) + 15 - (passive_ratio * 30))
    specificity_score = min(max(specificity_raw, 30), 100)

    if verb_ratio < 0.60:
        feedback.append(f"Only {int(verb_ratio * 100)}% of bullets begin with strong action verbs. Use verbs like 'Engineered', 'Optimized', or 'Orchestrated'.")
    if passive_phrase_count > 0:
        feedback.append(f"Detected {passive_phrase_count} passive phrases (e.g. 'Responsible for'). Replace with direct ownership verbs.")

    # Compute Quantified Impact Score (0 - 100)
    # Industry standard: 40-50% quantified bullets is considered top tier; 70%+ is exceptional
    metric_ratio = metric_count / total
    if metric_ratio >= 0.60:
        impact_score = 92
    elif metric_ratio >= 0.45:
        impact_score = 84
    elif metric_ratio >= 0.30:
        impact_score = 74
    elif metric_ratio >= 0.15:
        impact_score = 62
    elif metric_ratio > 0:
        impact_score = 50
    else:
        impact_score = 35

    if metric_ratio < 0.35:
        feedback.append(f"Only {int(metric_ratio * 100)}% of bullets have measurable metrics. Add figures like '% improved', '$ saved', or volume handled.")

    return specificity_score, impact_score, feedback


# ─── Pillar 3: Experience Relevance & Depth Audit ─────────────────────────────
def audit_experience_relevance(
    resume: Dict[str, Any],
    matched_keywords: List[str],
    target_title: str = ""
) -> int:
    """
    Evaluates depth, title relevance, and skills embedded within experience bullets.
    Industry standard (Jobscan/Workday): Skills demonstrated in work history
    are weighted far higher than bare mentions in a skills list.
    """
    sections = resume.get("sections_json") or resume.get("sections") or []
    if isinstance(sections, str):
        try:
            import json
            sections = json.loads(sections)
        except Exception:
            sections = []

    exp_bullets = []
    exp_titles = []
    for s in sections or []:
        if isinstance(s, dict):
            sec_title = (s.get("title") or "").lower()
            if any(k in sec_title for k in ["experience", "work", "employment", "career", "history"]):
                for it in s.get("items") or []:
                    if isinstance(it, dict):
                        role = it.get("role") or it.get("title") or ""
                        if role:
                            exp_titles.append(role.lower())
                        for pt in it.get("points") or []:
                            if isinstance(pt, str):
                                exp_bullets.append(pt.lower())

    if not exp_bullets and not exp_titles:
        return 45

    # 1. Experience depth (items count & bullets count) - max 35 pts
    depth_pts = min(len(exp_bullets) * 3, 20) + min(len(exp_titles) * 5, 15)

    # 2. Keywords embedded in experience bullets (skills in context) - max 45 pts
    exp_corpus = " ".join(exp_bullets)
    if matched_keywords:
        in_exp_count = sum(1 for kw in matched_keywords if kw.lower() in exp_corpus)
        kw_ratio = in_exp_count / len(matched_keywords)
        kw_pts = int(kw_ratio * 45)
    else:
        kw_pts = 25

    # 3. Title alignment (if target_title provided) - max 20 pts
    title_pts = 10
    if target_title:
        target_words = [w for w in re.findall(r"\w+", target_title.lower()) if len(w) > 3]
        if target_words:
            matched_title_words = sum(1 for w in target_words if any(w in et for et in exp_titles))
            title_pts = int((matched_title_words / len(target_words)) * 20)
        else:
            title_pts = 15
    else:
        title_pts = 15

    return min(max(depth_pts + kw_pts + title_pts, 35), 95)


# ─── Pillar 4: Deterministic Keyword Reconciliation ────────────────────────────
def match_and_reconcile_keywords(
    raw_matched: List[str],
    raw_missing: List[str],
    raw_recommended: List[str],
    resume_corpus_lower: str,
    jd_lower: str = ""
) -> Tuple[List[str], List[str], List[str], int]:
    """
    Performs deterministic regex matching with word boundaries and alias expansion.
    Returns (reconciled_matched, reconciled_missing, reconciled_recommended, keyword_score: 0-100).
    """
    all_terms = list(dict.fromkeys(raw_matched + raw_missing + raw_recommended))
    reconciled_matched = []
    reconciled_missing = []
    reconciled_recommended = []

    def term_in_text(term: str, text: str) -> bool:
        t_clean = term.strip().lower()
        if not t_clean:
            return False
        # Exact substring or word boundary pattern
        pattern = rf"(?:\b|_){re.escape(t_clean)}(?:\b|_)"
        if re.search(pattern, text):
            return True
        # Check alias (e.g. k8s in text when term is kubernetes or vice-versa)
        norm = normalize_keyword(t_clean)
        if norm != t_clean and re.search(rf"(?:\b|_){re.escape(norm)}(?:\b|_)", text):
            return True
        # Check reverse alias
        for alias_k, alias_v in TECH_ALIASES.items():
            if alias_v == t_clean and re.search(rf"(?:\b|_){re.escape(alias_k)}(?:\b|_)", text):
                return True
        return False

    for term in all_terms:
        if not isinstance(term, str) or not term.strip():
            continue
        t_clean = term.strip()

        # If present in resume corpus, it is MATCHED
        if term_in_text(t_clean, resume_corpus_lower):
            if t_clean not in reconciled_matched:
                reconciled_matched.append(t_clean)
        else:
            # Not in resume: check if it belongs in missing (from JD) or recommended
            if jd_lower and term_in_text(t_clean, jd_lower):
                if t_clean not in reconciled_missing:
                    reconciled_missing.append(t_clean)
            else:
                if t_clean not in reconciled_recommended and t_clean not in reconciled_missing:
                    reconciled_recommended.append(t_clean)

    # Compute deterministic keyword score
    total_jd_keywords = len(reconciled_matched) + len(reconciled_missing)
    if total_jd_keywords > 0:
        match_ratio = len(reconciled_matched) / total_jd_keywords
        # Calibrate keyword score: 80% match is 88 score, 50% match is 60 score
        keyword_score = int(match_ratio * 100)
    else:
        keyword_score = 75

    return (
        list(dict.fromkeys(reconciled_matched)),
        list(dict.fromkeys(reconciled_missing)),
        list(dict.fromkeys(reconciled_recommended)),
        keyword_score
    )


# ─── Master Deterministic ATS Scorer ──────────────────────────────────────────
def compute_legit_ats_evaluation(
    current_resume: Dict[str, Any],
    ai_data: Dict[str, Any],
    job_description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Computes accurate, explainable, and reproducible ATS evaluation:
    1. Structure & Parseability: Deterministically computed from header and section hierarchy.
    2. Content Specificity: Deterministically computed from action verbs and passive voice analysis.
    3. Quantified Impact: Deterministically computed from metrics density (% of quantified bullets).
    4. Keyword Coverage: Deterministically computed from regex match ratio against resume text.
    5. Overall Score: Mathematically calculated as weighted average (no random numbers or artificial ratchets).
    """
    corpus_lower = extract_full_text(current_resume)
    jd_lower = (job_description or "").strip().lower()

    # 1. Structure audit
    structure_score, structure_feedback = audit_structure_and_parseability(current_resume)

    # 2. Specificity & Impact audit
    specificity_score, impact_score, content_feedback = audit_content_and_impact(current_resume)

    # 3. Keyword matching & reconciliation
    raw_ats = ai_data.get("ats_check") or {}
    raw_matched = raw_ats.get("matched_keywords") or []
    raw_missing = raw_ats.get("missing_keywords") or []
    raw_rec = raw_ats.get("recommended_keywords") or []

    matched_kw, missing_kw, rec_kw, keyword_score = match_and_reconcile_keywords(
        raw_matched, raw_missing, raw_rec, corpus_lower, jd_lower
    )

    is_jd_mode = bool(job_description and len(job_description.strip()) >= 30)

    if is_jd_mode:
        # JD Mode Weighting:
        # - Keyword Match (35%)
        # - Role Experience Relevance (25%) (Computed from experience bullets, depth & title fit)
        # - Content Specificity & Action Verbs (20%)
        # - Structure & Parseability (20%)
        job_an = ai_data.get("job_analysis") or {}
        target_title = str(job_an.get("title") or "")
        exp_relevance = audit_experience_relevance(current_resume, matched_kw, target_title)

        category_scores = {
            "keyword_alignment": keyword_score,
            "relevant_experience": exp_relevance,
            "content_specificity": specificity_score,
            "structure_parseability": structure_score,
        }

        overall_score = round(
            0.35 * keyword_score +
            0.25 * exp_relevance +
            0.20 * specificity_score +
            0.20 * structure_score
        )
    else:
        # Standalone ATS Mode Weighting:
        # - Structure & Parseability (30%)
        # - Content Specificity (30%)
        # - Core Competencies (25%)
        # - Quantified Impact (15%)
        comp_score = min(max(keyword_score, 50), 95) if (matched_kw or rec_kw) else 70

        category_scores = {
            "structure_parseability": structure_score,
            "content_specificity": specificity_score,
            "core_competencies": comp_score,
            "evidence_of_impact": impact_score,
        }

        overall_score = round(
            0.30 * structure_score +
            0.30 * specificity_score +
            0.25 * comp_score +
            0.15 * impact_score
        )

    # Calibrate overall score within realistic range [25, 96]
    # No resume gets 98 or 99 unless it hits near-perfect across all categories
    overall_score = min(max(overall_score, 25), 96)

    # Calibrated grade
    if overall_score >= 85:
        grade = "Strong"
    elif overall_score >= 70:
        grade = "Good"
    elif overall_score >= 50:
        grade = "Needs Improvement" if not is_jd_mode else "Needs Work"
    else:
        grade = "Significant Gaps"

    # Compile legit improvements list
    improvements = []
    improvements.extend(structure_feedback[:2])
    improvements.extend(content_feedback[:2])
    if missing_kw and is_jd_mode:
        improvements.append(f"Consider highlighting missing skills if you have experience with them: {', '.join(missing_kw[:4])}.")

    # Deduplicate improvements while keeping concise
    final_improvements = list(dict.fromkeys(improvements))[:4]
    if not final_improvements:
        final_improvements = raw_ats.get("improvements") or ["Maintain current accomplishments and quantify newly added project results."]

    return {
        "overall_score": overall_score,
        "grade": grade,
        "category_scores": category_scores,
        "matched_keywords": matched_kw,
        "missing_keywords": missing_kw,
        "recommended_keywords": rec_kw,
        "improvements": final_improvements,
        "evaluation_disclosure": (
            "This assessment evaluates common resume quality, parseability, and role alignment. "
            "It is mathematically calculated from verifiable document structure, keyword density, and action verbs."
        ),
    }
