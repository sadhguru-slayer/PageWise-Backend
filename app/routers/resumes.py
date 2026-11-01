import json
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Resume, User, ResumeTemplate, ExportedResume, AIUsageLog
from ..schemas import (
    ResumeCreate, ResumeUpdate, ResumeSummary, ResumeDetail,
    JDAnalyzeRequest, ATSAnalyzeRequest, ResumeCloneRequest,
    TemplateCreate, TemplateOut, UsageStats
)
from ..auth import get_current_user

router = APIRouter(prefix="/api/resumes", tags=["Resumes"])


def serialize_json_field(val) -> str:
    """Helper to ensure a field is stored as a valid JSON string."""
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    if isinstance(val, str):
        return val
    return "{}"


def parse_json_field(val, default):
    """Helper to safely parse JSON text into Python object."""
    if not val:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


@router.get("", response_model=List[ResumeSummary])
def list_resumes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lists all active resumes belonging strictly to the currently authenticated user."""
    resumes = (
        db.query(Resume)
        .filter(Resume.user_id == current_user.id, Resume.is_deleted == False)
        .order_by(Resume.updated_at.desc())
        .all()
    )

    result = []
    for r in resumes:
        sec_list = parse_json_field(r.sections_json, [])
        sec_count = len(sec_list) if isinstance(sec_list, list) else 0
        result.append(
            ResumeSummary(
                id=r.id,
                user_id=r.user_id,
                name=r.name,
                created_at=r.created_at,
                updated_at=r.updated_at,
                section_count=sec_count,
                target_job_title=r.target_job_title,
                target_company=r.target_company,
                target_ats_score=r.target_ats_score,
            )
        )
    return result


@router.post("", response_model=ResumeDetail, status_code=status.HTTP_201_CREATED)
def create_resume(
    payload: ResumeCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Creates a new resume for the currently authenticated user."""
    new_resume = Resume(
        user_id=current_user.id,
        name=payload.name or "Untitled Resume",
        header_json=serialize_json_field(payload.header_json),
        settings_json=serialize_json_field(payload.settings_json),
        sections_json=serialize_json_field(payload.sections_json),
    )
    db.add(new_resume)
    db.commit()
    db.refresh(new_resume)

    return ResumeDetail(
        id=new_resume.id,
        user_id=new_resume.user_id,
        name=new_resume.name,
        header_json=parse_json_field(new_resume.header_json, {}),
        settings_json=parse_json_field(new_resume.settings_json, {}),
        sections_json=parse_json_field(new_resume.sections_json, []),
        created_at=new_resume.created_at,
        updated_at=new_resume.updated_at,
    )


@router.get("/{resume_id}", response_model=ResumeDetail)
def get_resume(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieves a single resume by ID, ensuring user ownership."""
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False)
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found or access denied")

    return ResumeDetail(
        id=resume.id,
        user_id=resume.user_id,
        name=resume.name,
        header_json=parse_json_field(resume.header_json, {}),
        settings_json=parse_json_field(resume.settings_json, {}),
        sections_json=parse_json_field(resume.sections_json, []),
        created_at=resume.created_at,
        updated_at=resume.updated_at,
        target_job_title=resume.target_job_title,
        target_company=resume.target_company,
        target_job_description=resume.target_job_description,
        target_ats_score=resume.target_ats_score,
        jd_analysis_json=parse_json_field(resume.jd_analysis_json, {}),
    )


@router.put("/{resume_id}", response_model=ResumeDetail)
def update_resume(
    resume_id: int,
    payload: ResumeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Updates an existing resume, ensuring user ownership."""
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False)
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found or access denied")

    if payload.name:
        resume.name = payload.name
    if payload.header_json is not None:
        resume.header_json = serialize_json_field(payload.header_json)
    if payload.settings_json is not None:
        resume.settings_json = serialize_json_field(payload.settings_json)
    if payload.sections_json is not None:
        resume.sections_json = serialize_json_field(payload.sections_json)
    # Job targeting metadata
    if payload.target_job_title is not None:
        resume.target_job_title = payload.target_job_title
    if payload.target_company is not None:
        resume.target_company = payload.target_company
    if payload.target_job_description is not None:
        resume.target_job_description = payload.target_job_description
    if payload.target_ats_score is not None:
        resume.target_ats_score = payload.target_ats_score

    db.commit()
    db.refresh(resume)

    return ResumeDetail(
        id=resume.id,
        user_id=resume.user_id,
        name=resume.name,
        header_json=parse_json_field(resume.header_json, {}),
        settings_json=parse_json_field(resume.settings_json, {}),
        sections_json=parse_json_field(resume.sections_json, []),
        created_at=resume.created_at,
        updated_at=resume.updated_at,
        target_job_title=resume.target_job_title,
        target_company=resume.target_company,
        target_job_description=resume.target_job_description,
        target_ats_score=resume.target_ats_score,
        jd_analysis_json=parse_json_field(resume.jd_analysis_json, {}),
    )


@router.delete("/{resume_id}", status_code=status.HTTP_200_OK)
def delete_resume(
    resume_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft-deletes a resume by ID, preserving resource quota history."""
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False)
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found or access denied")

    resume.is_deleted = True
    resume.deleted_at = datetime.utcnow()
    db.commit()
    return {"message": "Resume deleted successfully", "id": resume_id}


@router.post("/parse-pdf")
async def parse_pdf_resume(
    file: UploadFile = File(...),
    create_resume: bool = Form(False),
    resume_name: str = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Extracts text from an uploaded resume PDF using PyMuPDF and uses
    Google GenAI (Gemini) to parse it into structured sections and header.
    """
    from ..ai_extractor import extract_text_from_pdf, parse_resume_with_gemini
    import traceback

    print(f"[parse-pdf] Received uploaded file: '{file.filename}', user: {current_user.email}")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported for import.")

    try:
        content = await file.read()
        print(f"[parse-pdf] Read {len(content)} bytes from PDF. Extracting text...")
        extracted_text = extract_text_from_pdf(content)
        print(f"[parse-pdf] Extracted {len(extracted_text)} characters of text from PDF.")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Failed to extract text from PDF: {str(e)}")

    try:
        print("[parse-pdf] Sending extracted text to Gemini AI...")
        user_prefs = parse_json_field(current_user.preferences_json, {})
        allow_bold = bool(user_prefs.get("allow_bold_text", False))
        parsed_data = parse_resume_with_gemini(extracted_text, allow_bold_text=allow_bold)
        print("[parse-pdf] Gemini AI parsing completed successfully.")
    except ValueError as ve:
        print(f"[parse-pdf] Configuration/Validation Error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as ge:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Gemini AI extraction failed: {str(ge)}")

    if create_resume:
        name = resume_name or parsed_data.get("header", {}).get("name") or "Imported Resume"
        default_settings = {
            "marginTop": 15,
            "marginBottom": 15,
            "marginLeft": 15,
            "marginRight": 15,
            "bodyFont": "Georgia, serif",
            "bodyFontSize": 8.5,
            "headingColor": "#111827",
            "sectionSpacing": 1,
            "accentColor": "#1a56db",
            "lineHeight": 1.2,
        }
        new_resume = Resume(
            user_id=current_user.id,
            name=f"{name} (Imported)",
            header_json=serialize_json_field(parsed_data.get("header", {})),
            settings_json=serialize_json_field(default_settings),
            sections_json=serialize_json_field(parsed_data.get("sections", [])),
        )
        db.add(new_resume)
        db.commit()
        db.refresh(new_resume)

        return {
            "success": True,
            "created_resume_id": new_resume.id,
            "header": parsed_data.get("header", {}),
            "sections": parsed_data.get("sections", []),
            "resume": ResumeDetail(
                id=new_resume.id,
                user_id=new_resume.user_id,
                name=new_resume.name,
                header_json=parse_json_field(new_resume.header_json, {}),
                settings_json=parse_json_field(new_resume.settings_json, {}),
                sections_json=parse_json_field(new_resume.sections_json, []),
                created_at=new_resume.created_at,
                updated_at=new_resume.updated_at,
            )
        }

    return {
        "success": True,
        "header": parsed_data.get("header", {}),
        "sections": parsed_data.get("sections", []),
    }


@router.post("/analyze-jd")
def analyze_job_description(
    payload: JDAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Analyzes a Job Description (JD) against the user's current resume and
    their historical resumes archive. Performs strict ATS scoring and generates
    Canva-like bullet enhancements.
    """
    from ..jd_analyzer import analyze_jd_and_ats

    if not payload.job_description or not payload.job_description.strip():
        raise HTTPException(status_code=400, detail="Job description text is required.")

    # 1. Fetch current resume
    current_resume_dict = None
    if payload.current_resume_override and isinstance(payload.current_resume_override, dict):
        current_resume_dict = payload.current_resume_override
    elif payload.resume_id:
        target_resume = (
            db.query(Resume)
            .filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id)
            .first()
        )
        if target_resume:
            current_resume_dict = {
                "id": target_resume.id,
                "name": target_resume.name,
                "header_json": parse_json_field(target_resume.header_json, {}),
                "settings_json": parse_json_field(target_resume.settings_json, {}),
                "sections_json": parse_json_field(target_resume.sections_json, []),
            }

    if not current_resume_dict:
        # Fallback to user's most recent resume if exists
        latest_resume = (
            db.query(Resume)
            .filter(Resume.user_id == current_user.id)
            .order_by(Resume.updated_at.desc())
            .first()
        )
        if latest_resume:
            current_resume_dict = {
                "id": latest_resume.id,
                "name": latest_resume.name,
                "header_json": parse_json_field(latest_resume.header_json, {}),
                "settings_json": parse_json_field(latest_resume.settings_json, {}),
                "sections_json": parse_json_field(latest_resume.sections_json, []),
            }
        else:
            current_resume_dict = {"header_json": {}, "sections_json": []}

    # 2. Fetch user's previous resumes for richer context & cross-resume suggestions
    previous_resumes_list = []
    if payload.include_all_user_resumes:
        user_resumes = (
            db.query(Resume)
            .filter(Resume.user_id == current_user.id)
            .order_by(Resume.updated_at.desc())
            .all()
        )
        for ur in user_resumes:
            if payload.resume_id and ur.id == payload.resume_id:
                continue
            previous_resumes_list.append({
                "id": ur.id,
                "name": ur.name,
                "header_json": parse_json_field(ur.header_json, {}),
                "sections_json": parse_json_field(ur.sections_json, []),
            })

    try:
        user_prefs = parse_json_field(current_user.preferences_json, {})
        allow_bold = bool(user_prefs.get("allow_bold_text", False))
        analysis_result = analyze_jd_and_ats(
            job_description=payload.job_description,
            current_resume=current_resume_dict,
            previous_resumes=previous_resumes_list,
            allow_bold_text=allow_bold
        )

        # Automatically store summarized JD & ATS analysis in the target resume if resume_id is provided
        if payload.resume_id:
            res_to_update = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False).first()
            if res_to_update:
                job_an = analysis_result.get("job_analysis", {})
                ats_ck = analysis_result.get("ats_check", {})
                res_to_update.target_job_title = job_an.get("title") or res_to_update.target_job_title
                res_to_update.target_company = job_an.get("company") or res_to_update.target_company
                res_to_update.target_ats_score = ats_ck.get("overall_score")
                
                # Store concise summary version of JD (not raw giant bloat)
                jd_summary = job_an.get("summary") or (payload.job_description[:300] + "...")
                res_to_update.target_job_description = jd_summary
                res_to_update.jd_analysis_json = json.dumps(analysis_result)
                db.commit()

        # Record Wiser AI Usage Log (Job Help)
        ai_model_name = analysis_result.pop("_ai_model", "gemini-flash")
        job_an = analysis_result.get("job_analysis", {})
        ats_ck = analysis_result.get("ats_check", {})
        meta = {
            "job_title": job_an.get("title"),
            "company": job_an.get("company"),
            "ats_score": ats_ck.get("overall_score"),
        }
        log_entry = AIUsageLog(
            user_id=current_user.id,
            resume_id=payload.resume_id,
            action_type="wiser_job_help",
            ai_model=ai_model_name,
            meta_json=json.dumps(meta),
        )
        db.add(log_entry)
        db.commit()

        return {
            "success": True,
            "data": analysis_result
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as ge:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"JD & ATS analysis failed: {str(ge)}")


@router.post("/analyze-ats")
def analyze_standalone_resume_ats(
    payload: ATSAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Performs standalone 'Wiser ATS' audit on a resume without requiring a Job Description.
    Audits keyword positioning, action verbs, quantified impact, and structural parseability.
    """
    from ..jd_analyzer import analyze_standalone_ats

    # 1. Fetch current resume
    current_resume_dict = None
    if payload.current_resume_override and isinstance(payload.current_resume_override, dict):
        current_resume_dict = payload.current_resume_override
    elif payload.resume_id:
        target_resume = (
            db.query(Resume)
            .filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False)
            .first()
        )
        if target_resume:
            current_resume_dict = {
                "id": target_resume.id,
                "name": target_resume.name,
                "header_json": parse_json_field(target_resume.header_json, {}),
                "settings_json": parse_json_field(target_resume.settings_json, {}),
                "sections_json": parse_json_field(target_resume.sections_json, []),
            }

    if not current_resume_dict:
        latest_resume = (
            db.query(Resume)
            .filter(Resume.user_id == current_user.id, Resume.is_deleted == False)
            .order_by(Resume.updated_at.desc())
            .first()
        )
        if latest_resume:
            current_resume_dict = {
                "id": latest_resume.id,
                "name": latest_resume.name,
                "header_json": parse_json_field(latest_resume.header_json, {}),
                "settings_json": parse_json_field(latest_resume.settings_json, {}),
                "sections_json": parse_json_field(latest_resume.sections_json, []),
            }
        else:
            current_resume_dict = {"header_json": {}, "sections_json": []}

    try:
        user_prefs = parse_json_field(current_user.preferences_json, {})
        allow_bold = bool(user_prefs.get("allow_bold_text", False))
        analysis_result = analyze_standalone_ats(
            current_resume=current_resume_dict,
            allow_bold_text=allow_bold
        )

        ai_model_name = analysis_result.pop("_ai_model", "gemini-flash")
        ats_ck = analysis_result.get("ats_check", {})
        inferred = analysis_result.get("inferred_domain", {})

        # If resume_id provided, update target_ats_score on the resume
        if payload.resume_id:
            res_to_update = db.query(Resume).filter(
                Resume.id == payload.resume_id,
                Resume.user_id == current_user.id,
                Resume.is_deleted == False
            ).first()
            if res_to_update and ats_ck.get("overall_score") is not None:
                res_to_update.target_ats_score = ats_ck.get("overall_score")
                db.commit()

        # Log AI action for Wiser usage tracking
        meta = {
            "inferred_domain": inferred.get("title"),
            "ats_score": ats_ck.get("overall_score"),
        }
        log_entry = AIUsageLog(
            user_id=current_user.id,
            resume_id=payload.resume_id,
            action_type="wiser_ats_check",
            ai_model=ai_model_name,
            meta_json=json.dumps(meta),
        )
        db.add(log_entry)
        db.commit()

        return {
            "success": True,
            "data": analysis_result
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as ge:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Wiser ATS analysis failed: {str(ge)}")



# ─── Clone Resume (for Job-Targeted versions) ──────────────────────────────────

@router.post("/{resume_id}/clone", response_model=ResumeDetail, status_code=status.HTTP_201_CREATED)
def clone_resume(
    resume_id: int,
    payload: ResumeCloneRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Deep-clones a resume into a new job-targeted version.
    The source resume remains untouched.
    """
    source = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False)
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source resume not found or access denied")

    # Build a descriptive name
    if payload.new_name:
        new_name = payload.new_name
    elif payload.target_company and payload.target_job_title:
        new_name = f"{source.name} — {payload.target_company} ({payload.target_job_title})"
    elif payload.target_job_title:
        new_name = f"{source.name} — {payload.target_job_title}"
    else:
        new_name = f"{source.name} (Copy)"

    cloned = Resume(
        user_id=current_user.id,
        name=new_name,
        header_json=source.header_json,
        settings_json=source.settings_json,
        sections_json=source.sections_json,
        target_job_title=payload.target_job_title,
        target_company=payload.target_company,
        target_job_description=payload.target_job_description,
        target_ats_score=payload.target_ats_score,
        jd_analysis_json=source.jd_analysis_json,
    )
    db.add(cloned)
    db.commit()
    db.refresh(cloned)

    return ResumeDetail(
        id=cloned.id,
        user_id=cloned.user_id,
        name=cloned.name,
        header_json=parse_json_field(cloned.header_json, {}),
        settings_json=parse_json_field(cloned.settings_json, {}),
        sections_json=parse_json_field(cloned.sections_json, []),
        created_at=cloned.created_at,
        updated_at=cloned.updated_at,
        target_job_title=cloned.target_job_title,
        target_company=cloned.target_company,
        target_job_description=cloned.target_job_description,
        target_ats_score=cloned.target_ats_score,
        jd_analysis_json=parse_json_field(cloned.jd_analysis_json, {}),
    )


# ─── User Template CRUD ────────────────────────────────────────────────────────

templates_router = APIRouter(prefix="/api/templates", tags=["Templates"])


@templates_router.get("", response_model=List[TemplateOut])
def list_templates(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lists all active user-saved style templates (excluding soft-deleted)."""
    return (
        db.query(ResumeTemplate)
        .filter(ResumeTemplate.user_id == current_user.id, ResumeTemplate.is_deleted == False)
        .order_by(ResumeTemplate.created_at.desc())
        .all()
    )


@templates_router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
def save_template(
    payload: TemplateCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Saves the current resume's style as a reusable named template."""
    tmpl = ResumeTemplate(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        settings_json=serialize_json_field(payload.settings_json),
        header_style_json=serialize_json_field(payload.header_style_json),
        section_defaults_json=serialize_json_field(payload.section_defaults_json),
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)

    return TemplateOut(
        id=tmpl.id,
        user_id=tmpl.user_id,
        name=tmpl.name,
        description=tmpl.description,
        settings_json=parse_json_field(tmpl.settings_json, {}),
        header_style_json=parse_json_field(tmpl.header_style_json, {}),
        section_defaults_json=parse_json_field(tmpl.section_defaults_json, {}),
        created_at=tmpl.created_at,
    )


@templates_router.delete("/{template_id}", status_code=status.HTTP_200_OK)
def delete_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft-deletes a user-saved template, keeping lifetime usage counts."""
    tmpl = (
        db.query(ResumeTemplate)
        .filter(ResumeTemplate.id == template_id, ResumeTemplate.user_id == current_user.id, ResumeTemplate.is_deleted == False)
        .first()
    )
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    tmpl.is_deleted = True
    tmpl.deleted_at = datetime.utcnow()
    db.commit()
    return {"message": "Template deleted", "id": template_id}


# ─── Usage Stats ───────────────────────────────────────────────────────────────

@router.get("/usage-stats", response_model=UsageStats)
def get_usage_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns aggregated usage statistics and Wiser AI metrics for the authenticated user."""
    # Active resources currently in workspace
    active_resumes = db.query(Resume).filter(Resume.user_id == current_user.id, Resume.is_deleted == False).count()
    active_templates = db.query(ResumeTemplate).filter(ResumeTemplate.user_id == current_user.id, ResumeTemplate.is_deleted == False).count()
    active_exports = db.query(ExportedResume).filter(ExportedResume.user_id == current_user.id, ExportedResume.is_deleted == False).count()
    targeted_count = (
        db.query(Resume)
        .filter(Resume.user_id == current_user.id, Resume.is_deleted == False, Resume.target_job_title.isnot(None))
        .count()
    )

    # Lifetime total resources created (including soft-deleted)
    total_resumes = db.query(Resume).filter(Resume.user_id == current_user.id).count()
    total_templates = db.query(ResumeTemplate).filter(ResumeTemplate.user_id == current_user.id).count()
    total_exports = db.query(ExportedResume).filter(ExportedResume.user_id == current_user.id).count()

    # Wiser AI layer metrics (subscriptions & quota enforcement)
    wiser_job_helps = db.query(AIUsageLog).filter(AIUsageLog.user_id == current_user.id, AIUsageLog.action_type == "wiser_job_help").count()
    wiser_ats_checks = db.query(AIUsageLog).filter(AIUsageLog.user_id == current_user.id, AIUsageLog.action_type == "wiser_ats_check").count()
    wiser_total = db.query(AIUsageLog).filter(AIUsageLog.user_id == current_user.id).count()

    # Graceful fallback for historical accounts created before AIUsageLog table
    if wiser_job_helps == 0 and targeted_count > 0:
        wiser_job_helps = targeted_count
        wiser_total = targeted_count

    return UsageStats(
        resume_count=active_resumes,
        total_resumes_generated=total_resumes,
        template_count=active_templates,
        total_templates_created=total_templates,
        export_count=active_exports,
        total_exports_generated=total_exports,
        targeted_resume_count=targeted_count,
        jd_analyses_count=wiser_job_helps,
        wiser_job_helps_count=wiser_job_helps,
        wiser_ats_checks_count=wiser_ats_checks,
        wiser_total_invocations=wiser_total,
    )



# ─── Legacy Backward Compatibility Router (/api/resume/*) ──────────────────────
legacy_router = APIRouter(prefix="/api/resume", tags=["Legacy"])

@legacy_router.get("/list")
def legacy_list_resumes(db: Session = Depends(get_db)):
    """Provides backward-compatibility for cached client tabs calling /api/resume/list."""
    resumes = db.query(Resume).order_by(Resume.updated_at.desc()).limit(20).all()
    out = []
    for r in resumes:
        out.append({
            "id": r.id,
            "name": r.name,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
            "createdAt": r.created_at.isoformat() if r.created_at else None,
            "headerJson": parse_json_field(r.header_json, {}),
            "settingsJson": parse_json_field(r.settings_json, {}),
            "sectionsJson": parse_json_field(r.sections_json, []),
        })
    return {"resumes": out}

