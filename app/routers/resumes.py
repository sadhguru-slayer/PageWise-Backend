import asyncio
import json
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Resume, User, ResumeTemplate, ExportedResume, AIUsageLog
from ..schemas import (
    ResumeCreate, ResumeUpdate, ResumeSummary, ResumeDetail,
    JDAnalyzeRequest, ATSAnalyzeRequest, ResumeCloneRequest,
    TemplateCreate, TemplateOut, UsageStats
)
from ..auth import get_current_user, get_current_user_optional
from ..services.subscription import (
    enforce_resume_limit,
    enforce_wiser_ai_limit,
    enforce_template_limit,
    enforce_template_access,
    is_template_unlocked_for_tier,
    increment_wiser_ai_usage,
    get_user_active_workspace_ids,
    enforce_resume_edit_permission,
    require_resume_quota,
    require_template_quota,
    require_wiser_job_help_quota,
    require_wiser_ats_quota,
    get_or_create_subscription,
    TIER_LEVELS,
)

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
        .order_by(Resume.is_primary.desc(), Resume.updated_at.desc())
        .all()
    )

    active_ids = get_user_active_workspace_ids(db, current_user)

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
                is_primary=bool(r.is_primary),
                is_locked=(r.id not in active_ids),
                parent_resume_id=r.parent_resume_id,
            )
        )
    return result


@router.post("", response_model=ResumeDetail, status_code=status.HTTP_201_CREATED)
def create_resume(
    payload: ResumeCreate,
    current_user: User = Depends(require_resume_quota),
    db: Session = Depends(get_db)
):
    """Creates a new resume for the currently authenticated user."""
    enforce_resume_limit(db, current_user)

    if payload.template_key or payload.template_id:
        enforce_template_access(db, current_user, payload.template_key or payload.template_id)

    existing_count = (
        db.query(Resume)
        .filter(Resume.user_id == current_user.id, Resume.is_deleted == False)
        .count()
    )

    new_resume = Resume(
        user_id=current_user.id,
        name=payload.name or "Untitled Resume",
        header_json=serialize_json_field(payload.header_json),
        settings_json=serialize_json_field(payload.settings_json),
        sections_json=serialize_json_field(payload.sections_json),
        is_primary=(existing_count == 0),
    )
    db.add(new_resume)
    db.commit()
    db.refresh(new_resume)

    active_ids = get_user_active_workspace_ids(db, current_user)

    return ResumeDetail(
        id=new_resume.id,
        user_id=new_resume.user_id,
        name=new_resume.name,
        header_json=parse_json_field(new_resume.header_json, {}),
        settings_json=parse_json_field(new_resume.settings_json, {}),
        sections_json=parse_json_field(new_resume.sections_json, []),
        created_at=new_resume.created_at,
        updated_at=new_resume.updated_at,
        is_primary=bool(new_resume.is_primary),
        is_locked=(new_resume.id not in active_ids),
        parent_resume_id=new_resume.parent_resume_id,
    )


# ─── Usage Stats (Mounted BEFORE /{resume_id} to prevent path collision) ───────

def resolve_date_range(period: str, start_date_str: Optional[str] = None, end_date_str: Optional[str] = None):
    now = datetime.utcnow()
    start_dt = None
    end_dt = None
    label = "All Time"

    if start_date_str:
        try:
            start_dt = datetime.fromisoformat(start_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
    if end_date_str:
        try:
            end_dt = datetime.fromisoformat(end_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass

    if start_dt or end_dt:
        label = "Custom Range"
        return start_dt, end_dt, label

    p = (period or "all").lower().strip()
    if p in ("this_billing", "this_month", "current"):
        # 1st of current month at 00:00:00 UTC
        start_dt = datetime(now.year, now.month, 1)
        end_dt = now
        label = "This Billing Cycle"
    elif p in ("prev_billing", "prev_month", "last_month"):
        # 1st of previous month to end of previous month
        first_of_this_month = datetime(now.year, now.month, 1)
        last_day_prev_month = first_of_this_month - timedelta(days=1)
        start_dt = datetime(last_day_prev_month.year, last_day_prev_month.month, 1)
        end_dt = datetime(last_day_prev_month.year, last_day_prev_month.month, last_day_prev_month.day, 23, 59, 59)
        label = "Previous Billing Cycle"
    elif p in ("last_3_months", "3_months", "90_days"):
        start_dt = now - timedelta(days=90)
        end_dt = now
        label = "Last 3 Months"
    else:  # "all"
        start_dt = None
        end_dt = None
        label = "All Time"

    return start_dt, end_dt, label


@router.get("/usage-stats", response_model=UsageStats)
def get_usage_stats(
    period: str = "all",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns aggregated usage statistics and Wiser AI metrics for the authenticated user,
    supporting duration filters ('this_billing', 'prev_billing', 'last_3_months', 'all', or custom dates).
    """
    start_dt, end_dt, period_label = resolve_date_range(period, start_date, end_date)

    # Base query for AI Usage Logs
    ai_log_q = db.query(AIUsageLog).filter(AIUsageLog.user_id == current_user.id)
    resume_q = db.query(Resume).filter(Resume.user_id == current_user.id)
    tmpl_q = db.query(ResumeTemplate).filter(ResumeTemplate.user_id == current_user.id)
    export_q = db.query(ExportedResume).filter(ExportedResume.user_id == current_user.id)

    # Lifetime total counts (protects against quota abuse — never reduced by date filters or deletes)
    total_resumes = resume_q.count()
    total_templates = tmpl_q.count()
    total_exports = export_q.count()
    lifetime_wiser_invocations = ai_log_q.count()

    # Active in workspace (excluding soft-deleted)
    active_resumes = db.query(Resume).filter(Resume.user_id == current_user.id, Resume.is_deleted == False).count()
    active_templates = db.query(ResumeTemplate).filter(ResumeTemplate.user_id == current_user.id, ResumeTemplate.is_deleted == False).count()
    active_exports = db.query(ExportedResume).filter(ExportedResume.user_id == current_user.id, ExportedResume.is_deleted == False).count()
    targeted_count = db.query(Resume).filter(
        Resume.user_id == current_user.id,
        Resume.is_deleted == False,
        Resume.target_job_title.isnot(None)
    ).count()

    # Filter by period timeframe
    if start_dt:
        ai_log_q = ai_log_q.filter(AIUsageLog.created_at >= start_dt)
        resume_q = resume_q.filter(Resume.created_at >= start_dt)
        tmpl_q = tmpl_q.filter(ResumeTemplate.created_at >= start_dt)
        export_q = export_q.filter(ExportedResume.created_at >= start_dt)
    if end_dt:
        ai_log_q = ai_log_q.filter(AIUsageLog.created_at <= end_dt)
        resume_q = resume_q.filter(Resume.created_at <= end_dt)
        tmpl_q = tmpl_q.filter(ResumeTemplate.created_at <= end_dt)
        export_q = export_q.filter(ExportedResume.created_at <= end_dt)

    wiser_job_helps = ai_log_q.filter(AIUsageLog.action_type == "wiser_job_help").count()
    wiser_ats_checks = ai_log_q.filter(AIUsageLog.action_type == "wiser_ats_check").count()
    wiser_total = ai_log_q.count()

    period_resumes = resume_q.count()
    period_templates = tmpl_q.count()
    period_exports = export_q.count()

    # Graceful fallback for historical accounts created before AIUsageLog table
    if period == "all" and wiser_job_helps == 0 and targeted_count > 0:
        wiser_job_helps = targeted_count

    if wiser_total < (wiser_job_helps + wiser_ats_checks):
        wiser_total = wiser_job_helps + wiser_ats_checks

    if lifetime_wiser_invocations < wiser_total:
        lifetime_wiser_invocations = wiser_total

    return UsageStats(
        period=period,
        period_label=period_label,
        period_start=start_dt,
        period_end=end_dt,
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
        lifetime_wiser_invocations=lifetime_wiser_invocations,
        period_resumes_created=period_resumes,
        period_templates_created=period_templates,
        period_exports_generated=period_exports,
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

    active_ids = get_user_active_workspace_ids(db, current_user)

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
        is_primary=bool(resume.is_primary),
        is_locked=(resume.id not in active_ids),
        parent_resume_id=resume.parent_resume_id,
    )


@router.put("/{resume_id}", response_model=ResumeDetail)
def update_resume(
    resume_id: int,
    payload: ResumeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Updates an existing resume, ensuring user ownership and plan active workspace permission."""
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False)
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found or access denied")

    # Strictly verify that this resume is within allowed active workspaces for user's tier
    enforce_resume_edit_permission(db, current_user, resume_id)

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

    active_ids = get_user_active_workspace_ids(db, current_user)

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
        is_primary=bool(resume.is_primary),
        is_locked=(resume.id not in active_ids),
        parent_resume_id=resume.parent_resume_id,
    )


@router.post("/{resume_id}/set-primary", response_model=ResumeDetail)
@router.put("/{resume_id}/set-primary", response_model=ResumeDetail)
def set_primary_resume(
    resume_id: int,
    payload: Optional[dict] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Sets the specified resume as the user's primary/master resume.
    Unsets primary status for all other resumes of this user.
    """
    resume = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False)
        .first()
    )
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found or access denied")

    # Unset is_primary for all other user resumes
    db.query(Resume).filter(Resume.user_id == current_user.id, Resume.is_deleted == False).update({"is_primary": False})

    # Set selected resume as primary and bump recency so it stays in the active slot
    resume.is_primary = True
    resume.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(resume)

    active_ids = get_user_active_workspace_ids(db, current_user)

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
        is_primary=True,
        is_locked=(resume.id not in active_ids),
        parent_resume_id=resume.parent_resume_id,
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
    target_resume_id: Optional[int] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Extracts text from an uploaded resume PDF using PyMuPDF and uses
    Wiser AI engine to parse it into structured sections and header.
    Can create a new resume or update any existing resume content.
    """
    from ..ai_extractor import extract_text_from_pdf, async_parse_resume_with_wiser_ai
    import traceback

    print(f"[parse-pdf] Received uploaded file: '{file.filename}', user: {current_user.email}, target_resume_id: {target_resume_id}")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported for import.")

    # 1. Enforce Wiser AI quota/credits
    enforce_wiser_ai_limit(db, current_user, action_type="wiser_pdf_import")

    # 2. Check resume target / limits
    target_resume = None
    if target_resume_id:
        target_resume = (
            db.query(Resume)
            .filter(Resume.id == target_resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False)
            .first()
        )
        if not target_resume:
            raise HTTPException(status_code=404, detail="Selected target resume not found.")
        enforce_resume_edit_permission(db, current_user, target_resume.id)
    elif create_resume:
        enforce_resume_limit(db, current_user)

    try:
        content = await file.read()
        print(f"[parse-pdf] Read {len(content)} bytes from PDF. Extracting text asynchronously...")
        extracted_text = await asyncio.to_thread(extract_text_from_pdf, content)
        print(f"[parse-pdf] Extracted {len(extracted_text)} characters of text from PDF.")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Failed to extract text from PDF: {str(e)}")

    try:
        print("[parse-pdf] Sending extracted text to Wiser AI...")
        user_prefs = parse_json_field(current_user.preferences_json, {})
        allow_bold = bool(user_prefs.get("allow_bold_text", False))
        parsed_data = await async_parse_resume_with_wiser_ai(extracted_text, allow_bold_text=allow_bold)
        print("[parse-pdf] Wiser AI parsing completed successfully.")
    except ValueError as ve:
        print(f"[parse-pdf] Configuration/Validation Error: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as ge:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Wiser AI extraction failed: {str(ge)}")

    # Deduct / increment Wiser AI usage counter
    increment_wiser_ai_usage(db, current_user, action_type="wiser_pdf_import")

    # Record AI Usage Audit Log
    try:
        ai_log = AIUsageLog(
            user_id=current_user.id,
            resume_id=target_resume.id if target_resume else None,
            action_type="wiser_pdf_import",
            ai_model="Wiser AI Engine",
            tokens_used=len(extracted_text) // 4,
            meta_json=json.dumps({"filename": file.filename})
        )
        db.add(ai_log)
        db.commit()
    except Exception as log_err:
        print(f"[parse-pdf] Notice: Could not record AIUsageLog: {log_err}")

    # Case 1: Update existing target resume
    if target_resume:
        target_resume.header_json = serialize_json_field(parsed_data.get("header", {}))
        target_resume.sections_json = serialize_json_field(parsed_data.get("sections", []))
        target_resume.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(target_resume)

        active_ids = get_user_active_workspace_ids(db, current_user)
        return {
            "success": True,
            "updated_resume_id": target_resume.id,
            "header": parsed_data.get("header", {}),
            "sections": parsed_data.get("sections", []),
            "resume": ResumeDetail(
                id=target_resume.id,
                user_id=target_resume.user_id,
                name=target_resume.name,
                header_json=parse_json_field(target_resume.header_json, {}),
                settings_json=parse_json_field(target_resume.settings_json, {}),
                sections_json=parse_json_field(target_resume.sections_json, []),
                created_at=target_resume.created_at,
                updated_at=target_resume.updated_at,
                is_primary=bool(target_resume.is_primary),
                is_locked=(target_resume.id not in active_ids),
                parent_resume_id=target_resume.parent_resume_id,
            )
        }

    # Case 2: Create brand new resume
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

        active_ids = get_user_active_workspace_ids(db, current_user)

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
                is_primary=bool(new_resume.is_primary),
                is_locked=(new_resume.id not in active_ids),
                parent_resume_id=new_resume.parent_resume_id,
            )
        }

    # Case 3: Parse-only (client will handle in-memory state)
    return {
        "success": True,
        "header": parsed_data.get("header", {}),
        "sections": parsed_data.get("sections", []),
    }


@router.post("/analyze-jd")
async def analyze_job_description(
    payload: JDAnalyzeRequest,
    current_user: User = Depends(require_wiser_job_help_quota),
    db: Session = Depends(get_db)
):
    """
    Analyzes a Job Description (JD) against the user's current resume and
    their historical resumes archive. Performs strict ATS scoring and generates
    Canva-like bullet enhancements.
    """
    from ..jd_analyzer import async_analyze_jd_and_ats

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

    # 2. Optional archive context — cap at 2 recent resumes to keep Wiser latency low
    previous_resumes_list = []
    if payload.include_all_user_resumes:
        user_resumes = (
            db.query(Resume)
            .filter(Resume.user_id == current_user.id, Resume.is_deleted == False)
            .order_by(Resume.updated_at.desc())
            .limit(3)
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
            if len(previous_resumes_list) >= 2:
                break

    try:
        user_prefs = parse_json_field(current_user.preferences_json, {})
        allow_bold = bool(user_prefs.get("allow_bold_text", False))
        analysis_result = await async_analyze_jd_and_ats(
            job_description=payload.job_description,
            current_resume=current_resume_dict,
            previous_resumes=previous_resumes_list,
            allow_bold_text=allow_bold
        )

        # Persist analysis only on editable (unlocked) workspaces
        valid_res_id = None
        if payload.resume_id:
            res_to_update = db.query(Resume).filter(Resume.id == payload.resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False).first()
            if res_to_update:
                valid_res_id = res_to_update.id
                active_ids = get_user_active_workspace_ids(db, current_user)
                if res_to_update.id in active_ids:
                    job_an = analysis_result.get("job_analysis", {})
                    ats_ck = analysis_result.get("ats_check", {})
                    res_to_update.target_job_title = job_an.get("title") or res_to_update.target_job_title
                    res_to_update.target_company = job_an.get("company") or res_to_update.target_company
                    res_to_update.target_ats_score = ats_ck.get("overall_score")
                    jd_summary = job_an.get("summary") or (payload.job_description[:300] + "...")
                    res_to_update.target_job_description = jd_summary
                    res_to_update.jd_analysis_json = json.dumps(analysis_result)
                    db.commit()

        # Record Wiser AI Usage Log (Job Help)
        analysis_result.pop("_ai_model", None)
        ai_model_name = "Wiser AI Engine"
        job_an = analysis_result.get("job_analysis", {})
        ats_ck = analysis_result.get("ats_check", {})
        meta = {
            "job_title": job_an.get("title"),
            "company": job_an.get("company"),
            "ats_score": ats_ck.get("overall_score"),
        }
        log_entry = AIUsageLog(
            user_id=current_user.id,
            resume_id=valid_res_id,
            action_type="wiser_job_help",
            ai_model=ai_model_name,
            meta_json=json.dumps(meta),
        )
        db.add(log_entry)
        db.commit()

        increment_wiser_ai_usage(db, current_user, action_type="wiser_job_help")

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
async def analyze_standalone_resume_ats(
    payload: ATSAnalyzeRequest,
    current_user: User = Depends(require_wiser_ats_quota),
    db: Session = Depends(get_db)
):
    """
    Performs standalone 'Wiser ATS' audit on a resume without requiring a Job Description.
    Audits keyword positioning, action verbs, quantified impact, and structural parseability.
    """
    from ..jd_analyzer import async_analyze_standalone_ats

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
        analysis_result = await async_analyze_standalone_ats(
            current_resume=current_resume_dict,
            allow_bold_text=allow_bold
        )

        analysis_result.pop("_ai_model", None)
        ai_model_name = "Wiser AI Engine"
        ats_ck = analysis_result.get("ats_check", {})
        inferred = analysis_result.get("inferred_domain", {})

        # If resume_id provided, update target_ats_score on the resume
        valid_res_id = None
        if payload.resume_id:
            res_to_update = db.query(Resume).filter(
                Resume.id == payload.resume_id,
                Resume.user_id == current_user.id,
                Resume.is_deleted == False
            ).first()
            if res_to_update:
                valid_res_id = res_to_update.id
                if ats_ck.get("overall_score") is not None:
                    res_to_update.target_ats_score = ats_ck.get("overall_score")
                    db.commit()

        # Log AI action for Wiser usage tracking
        meta = {
            "inferred_domain": inferred.get("title"),
            "ats_score": ats_ck.get("overall_score"),
        }
        log_entry = AIUsageLog(
            user_id=current_user.id,
            resume_id=valid_res_id,
            action_type="wiser_ats_check",
            ai_model=ai_model_name,
            meta_json=json.dumps(meta),
        )
        db.add(log_entry)
        db.commit()

        increment_wiser_ai_usage(db, current_user, action_type="wiser_ats_check")

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
    Deep-clones a resume into a new job-targeted version, or retargets the
    existing Master workspace when apply_to_existing is set (workspace cap).
    """
    source = (
        db.query(Resume)
        .filter(Resume.id == resume_id, Resume.user_id == current_user.id, Resume.is_deleted == False)
        .first()
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source resume not found or access denied")

    def _detail(resume_obj: Resume) -> ResumeDetail:
        active_ids = get_user_active_workspace_ids(db, current_user)
        return ResumeDetail(
            id=resume_obj.id,
            user_id=resume_obj.user_id,
            name=resume_obj.name,
            header_json=parse_json_field(resume_obj.header_json, {}),
            settings_json=parse_json_field(resume_obj.settings_json, {}),
            sections_json=parse_json_field(resume_obj.sections_json, []),
            created_at=resume_obj.created_at,
            updated_at=resume_obj.updated_at,
            target_job_title=resume_obj.target_job_title,
            target_company=resume_obj.target_company,
            target_job_description=resume_obj.target_job_description,
            target_ats_score=resume_obj.target_ats_score,
            jd_analysis_json=parse_json_field(resume_obj.jd_analysis_json, {}),
            is_primary=bool(resume_obj.is_primary),
            is_locked=(resume_obj.id not in active_ids),
            parent_resume_id=resume_obj.parent_resume_id,
        )

    if payload.apply_to_existing:
        db.query(Resume).filter(
            Resume.user_id == current_user.id,
            Resume.is_deleted == False,
        ).update({"is_primary": False})
        source.is_primary = True
        if payload.new_name:
            source.name = payload.new_name
        elif payload.target_company and payload.target_job_title:
            source.name = f"{source.name.split(' — ')[0]} — {payload.target_company} ({payload.target_job_title})"
        source.target_job_title = payload.target_job_title or source.target_job_title
        source.target_company = payload.target_company or source.target_company
        source.target_job_description = payload.target_job_description or source.target_job_description
        source.target_ats_score = payload.target_ats_score if payload.target_ats_score is not None else source.target_ats_score
        if payload.jd_analysis_json:
            source.jd_analysis_json = serialize_json_field(payload.jd_analysis_json)
        source.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(source)
        return _detail(source)

    enforce_resume_limit(db, current_user)

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
        parent_resume_id=source.id,
    )
    db.add(cloned)
    db.commit()
    db.refresh(cloned)
    return _detail(cloned)


# ─── User Template CRUD ────────────────────────────────────────────────────────

templates_router = APIRouter(prefix="/api/templates", tags=["Templates"])


@templates_router.get("/system")
def list_system_templates(
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """
    Returns all global system-wide templates with dynamically calculated
    'is_locked' and 'min_plan_tier' based on user's current subscription tier.
    """
    user_tier = "free"
    if current_user:
        sub = get_or_create_subscription(db, current_user.id)
        user_tier = sub.plan_type

    templates = (
        db.query(ResumeTemplate)
        .filter(
            ResumeTemplate.is_global == True,
            ResumeTemplate.is_active == True,
            ResumeTemplate.is_deleted == False
        )
        .order_by(ResumeTemplate.display_order.asc(), ResumeTemplate.id.asc())
        .all()
    )

    out = []
    for t in templates:
        unlocked = is_template_unlocked_for_tier(user_tier, t.min_plan_tier or "free")
        out.append({
            "id": t.id,
            "template_key": t.template_key or f"tpl-{t.id}",
            "name": t.name,
            "description": t.description or "",
            "category": t.category or "Standard",
            "badge": t.badge or "",
            "min_plan_tier": t.min_plan_tier or "free",
            "is_locked": not unlocked,
            "user_unlocked": unlocked,
            "display_order": t.display_order,
            "settings_json": parse_json_field(t.settings_json, {}),
            "header_style_json": parse_json_field(t.header_style_json, {}),
            "section_defaults_json": parse_json_field(t.section_defaults_json, {}),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return out


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
    current_user: User = Depends(require_template_quota),
    db: Session = Depends(get_db)
):
    """Saves the current resume's style as a reusable named template."""
    enforce_template_limit(db, current_user)
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

