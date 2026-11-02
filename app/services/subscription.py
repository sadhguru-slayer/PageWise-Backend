import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException, status, Depends

from ..database import get_db
from ..auth import get_current_user
from ..models import User, Subscription, PlanType, Resume, ResumeTemplate, ExportedResume, AIUsageLog

# Thread-safe re-entrant lock for concurrency-safe quota evaluations and atomic counter updates
quota_lock = threading.RLock()


# ─── Plan Definitions ────────────────────────────────────────────────────────
PLAN_CONFIGS: Dict[str, Dict[str, Any]] = {
    PlanType.FREE: {
        "id": PlanType.FREE,
        "name": "Pagewise Free",
        "price_inr": 0,
        "duration_days": None,  # Forever
        "resume_limit": 1,
        "export_limit": 1,      # Per calendar month
        "wiser_ai_limit": 1,    # Combined allowance (covering both Job Help and ATS)
        "wiser_job_help_limit": 1,
        "wiser_ats_limit": 1,
        "custom_template_limit": 1,
        "premium_templates_allowed": 1,  # 1 standard customizable template
        "features": [
            "1 resume workspace",
            "Unlimited manual editing",
            "1 export per calendar month",
            "1 Wiser AI evaluation allowance, covering both Job Help and ATS",
            "1 standard customizable template",
            "Basic resume editor",
            "Resume remains saved"
        ]
    },
    PlanType.DAY_PASS: {
        "id": PlanType.DAY_PASS,
        "name": "Wiser Day Pass",
        "price_inr": 49,
        "duration_days": 1,     # 24 hours
        "resume_limit": 1,
        "export_limit": 5,
        "wiser_ai_limit": 6,    # 3 Job Help + 3 ATS
        "wiser_job_help_limit": 3,
        "wiser_ats_limit": 3,
        "custom_template_limit": 3,
        "premium_templates_allowed": 3,
        "features": [
            "24 hours · 1 resume",
            "1 resume workspace",
            "Unlimited manual editing",
            "3 premium templates",
            "5 exports",
            "3 Wiser Job Help analyses",
            "3 Wiser ATS evaluations",
            "AI improvement suggestions and application"
        ]
    },
    PlanType.PRO_MONTHLY: {
        "id": PlanType.PRO_MONTHLY,
        "name": "Pagewise Pro",
        "price_inr": 199,
        "duration_days": 30,    # 30 days
        "resume_limit": 5,
        "export_limit": 30,
        "wiser_ai_limit": 30,   # 15 Job Help + 15 ATS
        "wiser_job_help_limit": 15,
        "wiser_ats_limit": 15,
        "custom_template_limit": 999,
        "premium_templates_allowed": 999,
        "features": [
            "5 resume workspaces",
            "Unlimited manual editing",
            "30 exports",
            "15 Wiser Job Help analyses",
            "15 Wiser ATS evaluations",
            "All premium templates",
            "AI improvement suggestions and application",
            "Resume version management",
            "All export formats"
        ]
    }
}


def get_or_create_subscription(db: Session, user_id: int) -> Subscription:
    """Retrieves the user's subscription record or creates a default Free one."""
    sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not sub:
        sub = Subscription(
            user_id=user_id,
            plan_type=PlanType.FREE,
            status="active",
            started_at=datetime.utcnow(),
            expires_at=None,
            resumes_created_in_period=0,
            exports_used_in_period=0,
            wiser_job_help_used=0,
            wiser_ats_used=0,
            period_reset_at=datetime.utcnow()
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
    else:
        # Check if expired
        now = datetime.utcnow()
        if sub.expires_at and now > sub.expires_at and sub.status == "active":
            sub.status = "expired"
            sub.plan_type = PlanType.FREE
            sub.expires_at = None
            db.commit()
            db.refresh(sub)

        # Check calendar month reset for Free tier
        if sub.plan_type == PlanType.FREE and sub.period_reset_at:
            if (now.year > sub.period_reset_at.year) or (now.month > sub.period_reset_at.month):
                sub.exports_used_in_period = 0
                sub.wiser_job_help_used = 0
                sub.wiser_ats_used = 0
                sub.period_reset_at = now
                db.commit()
                db.refresh(sub)

    return sub


def get_user_plan_status(db: Session, user: User) -> Dict[str, Any]:
    """Returns active subscription plan details and current quota usages."""
    sub = get_or_create_subscription(db, user.id)
    plan_config = PLAN_CONFIGS.get(sub.plan_type, PLAN_CONFIGS[PlanType.FREE])

    # Count active workspace resumes
    active_resumes_count = (
        db.query(Resume)
        .filter(Resume.user_id == user.id, Resume.is_deleted == False)
        .count()
    )

    # Active templates
    active_templates_count = (
        db.query(ResumeTemplate)
        .filter(ResumeTemplate.user_id == user.id, ResumeTemplate.is_deleted == False)
        .count()
    )

    is_admin_flag = bool(user.is_admin)

    resumes_limit = plan_config["resume_limit"]
    exports_limit = plan_config["export_limit"]
    job_help_limit = plan_config["wiser_job_help_limit"]
    ats_limit = plan_config["wiser_ats_limit"]
    combined_limit = plan_config["wiser_ai_limit"]
    templates_limit = plan_config["custom_template_limit"]

    exports_used = sub.exports_used_in_period or 0
    job_help_used = sub.wiser_job_help_used or 0
    ats_used = sub.wiser_ats_used or 0
    total_ai_used = job_help_used + ats_used

    return {
        "plan_type": sub.plan_type,
        "plan_name": plan_config["name"],
        "status": sub.status,
        "is_admin": is_admin_flag,
        "started_at": sub.started_at,
        "expires_at": sub.expires_at,
        "limits": {
            "resumes": resumes_limit,
            "exports": exports_limit,
            "wiser_job_help": job_help_limit,
            "wiser_ats": ats_limit,
            "wiser_ai_combined": combined_limit,
            "custom_templates": templates_limit,
            "premium_templates_allowed": plan_config["premium_templates_allowed"],
        },
        "usage": {
            "active_resumes": active_resumes_count,
            "exports_used": exports_used,
            "wiser_job_help_used": job_help_used,
            "wiser_ats_used": ats_used,
            "wiser_ai_total_used": total_ai_used,
            "custom_templates_count": active_templates_count,
        },
        "remaining": {
            "resumes": max(0, resumes_limit - active_resumes_count),
            "exports": max(0, exports_limit - exports_used),
            "wiser_job_help": max(0, job_help_limit - job_help_used),
            "wiser_ats": max(0, ats_limit - ats_used),
            "wiser_ai_combined": max(0, combined_limit - total_ai_used),
            "custom_templates": max(0, templates_limit - active_templates_count),
        },
        "features": plan_config["features"],
    }


def get_user_active_workspace_ids(db: Session, user: User):
    """
    Returns list of resume IDs that are currently active/editable workspaces
    based on the user's plan limit and primary selection.
    """
    sub = get_or_create_subscription(db, user.id)
    plan_config = PLAN_CONFIGS.get(sub.plan_type, PLAN_CONFIGS[PlanType.FREE])
    limit = plan_config["resume_limit"]

    resumes = (
        db.query(Resume)
        .filter(Resume.user_id == user.id, Resume.is_deleted == False)
        .order_by(Resume.is_primary.desc(), Resume.updated_at.desc())
        .all()
    )
    if not resumes:
        return []

    # Ensure at least one primary resume
    has_primary = any(r.is_primary for r in resumes)
    if not has_primary:
        resumes[0].is_primary = True
        db.commit()

    # Top `limit` resumes are the active workspaces
    active_ids = [r.id for r in resumes[:limit]]
    return active_ids


def enforce_resume_edit_permission(db: Session, user: User, resume_id: int):
    """Ensures the specified resume is an allowed active workspace under user's plan."""
    active_ids = get_user_active_workspace_ids(db, user)
    if resume_id not in active_ids:
        sub = get_or_create_subscription(db, user.id)
        plan_config = PLAN_CONFIGS.get(sub.plan_type, PLAN_CONFIGS[PlanType.FREE])
        limit = plan_config["resume_limit"]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This resume is in Read-Only mode under your {plan_config['name']} workspace limit ({limit}). Set this resume as your Master Resume or upgrade to Pagewise Pro to edit."
        )


def enforce_resume_limit(db: Session, user: User):
    """Enforces active resume limits before creating or cloning a resume."""
    with quota_lock:
        status_info = get_user_plan_status(db, user)
        limit = status_info["limits"]["resumes"]
        current_count = status_info["usage"]["active_resumes"]

        if current_count >= limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Plan limit reached: {status_info['plan_name']} allows up to {limit} resume workspace(s). Please upgrade your plan to add more."
            )


def enforce_template_limit(db: Session, user: User):
    """Enforces custom template limits before saving a custom template."""
    with quota_lock:
        status_info = get_user_plan_status(db, user)
        limit = status_info["limits"]["custom_templates"]
        current_count = status_info["usage"]["custom_templates_count"]

        if current_count >= limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Template limit reached: {status_info['plan_name']} allows up to {limit} custom template(s). Please upgrade your plan to save more templates."
            )


def enforce_export_limit(db: Session, user: User):
    """Enforces export limits before generating PDF, DOCX, PNG, HTML."""
    with quota_lock:
        status_info = get_user_plan_status(db, user)
        limit = status_info["limits"]["exports"]
        used = status_info["usage"]["exports_used"]

        if used >= limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Export allowance reached: {status_info['plan_name']} allows {limit} export(s). Please upgrade to Wiser Day Pass or Pagewise Pro."
            )


def increment_export_usage(db: Session, user: User):
    """Increments the export usage counter for the user."""
    with quota_lock:
        sub = get_or_create_subscription(db, user.id)
        sub.exports_used_in_period = (sub.exports_used_in_period or 0) + 1
        db.commit()


def enforce_wiser_ai_limit(db: Session, user: User, action_type: str = "wiser_job_help"):
    """Enforces Wiser AI limits (Job Help vs ATS check)."""
    with quota_lock:
        sub = get_or_create_subscription(db, user.id)
        plan_config = PLAN_CONFIGS.get(sub.plan_type, PLAN_CONFIGS[PlanType.FREE])

        if sub.plan_type == PlanType.FREE:
            # Free tier: 1 combined evaluation allowance covering both Job Help and ATS
            combined = (sub.wiser_job_help_used or 0) + (sub.wiser_ats_used or 0)
            if combined >= plan_config["wiser_ai_limit"]:
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail="Wiser AI evaluation allowance reached for Pagewise Free (1 evaluation). Upgrade to Wiser Day Pass or Pagewise Pro for more."
                )
        else:
            # Tiered limits
            if action_type == "wiser_job_help":
                if (sub.wiser_job_help_used or 0) >= plan_config["wiser_job_help_limit"]:
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail=f"Wiser Job Help allowance of {plan_config['wiser_job_help_limit']} reached. Upgrade to Pagewise Pro for 15 evaluations."
                    )
            elif action_type == "wiser_ats_check":
                if (sub.wiser_ats_used or 0) >= plan_config["wiser_ats_limit"]:
                    raise HTTPException(
                        status_code=status.HTTP_402_PAYMENT_REQUIRED,
                        detail=f"Wiser ATS allowance of {plan_config['wiser_ats_limit']} reached. Upgrade to Pagewise Pro for 15 evaluations."
                    )


def increment_wiser_ai_usage(db: Session, user: User, action_type: str = "wiser_job_help"):
    """Increments the specific Wiser AI usage counter for the user."""
    with quota_lock:
        sub = get_or_create_subscription(db, user.id)
        if action_type == "wiser_job_help":
            sub.wiser_job_help_used = (sub.wiser_job_help_used or 0) + 1
        elif action_type == "wiser_ats_check":
            sub.wiser_ats_used = (sub.wiser_ats_used or 0) + 1
        db.commit()


# ─── Fast FastAPI Dependency Guards ──────────────────────────────────────────

def require_resume_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """FastAPI Dependency: verifies active resume workspace limits before request body processing."""
    enforce_resume_limit(db, current_user)
    return current_user


def require_export_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """FastAPI Dependency: verifies export allowance limits upfront before heavy file generation."""
    enforce_export_limit(db, current_user)
    return current_user


def require_template_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """FastAPI Dependency: verifies custom template limits before saving."""
    enforce_template_limit(db, current_user)
    return current_user


def require_wiser_job_help_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """FastAPI Dependency: verifies Wiser Job Help quota before AI generation."""
    enforce_wiser_ai_limit(db, current_user, action_type="wiser_job_help")
    return current_user


def require_wiser_ats_quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """FastAPI Dependency: verifies Wiser ATS evaluation quota before AI analysis."""
    enforce_wiser_ai_limit(db, current_user, action_type="wiser_ats_check")
    return current_user

