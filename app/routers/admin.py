from pydantic import BaseModel
from datetime import datetime, timedelta
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import (
    User, Resume, ResumeTemplate, ExportedResume, AIUsageLog,
    Subscription, PaymentOrder, PlanType, PlanTierConfig, Feedback
)
from ..auth import get_current_user, hash_password, verify_password, create_access_token
from ..schemas import (
    UserOut,
    AdminLoginRequest,
    AdminUserCreate,
    AdminUserUpdate,
    AdminResetSelfPassword,
    AdminInsightsResponse,
    MetricStat,
    AdminTemplateCreate,
    AdminTemplateUpdate,
    PlanTierConfigOut,
    PlanTierConfigUpdate,
    FeedbackOut,
    FeedbackAdminUpdate,
    FeedbackListResponse,
    FeedbackStats,
)
from ..services.subscription import (
    PLAN_CONFIGS,
    get_or_create_subscription,
    get_user_plan_status,
    get_user_active_workspace_ids,
)

router = APIRouter(prefix="/api/admin", tags=["Admin Management"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependency that ensures only administrators can access admin routes."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required to access this endpoint."
        )
    return current_user


@router.post("/login")
def admin_login(payload: AdminLoginRequest, db: Session = Depends(get_db)):
    """
    Dedicated admin authentication portal. Accepts email or username.
    Enforces that the user MUST have is_admin=True.
    """
    ident = payload.username_or_email.lower().strip()
    user = (
        db.query(User)
        .filter(
            (func.lower(User.email) == ident) | (func.lower(User.name) == ident)
        )
        .first()
    )

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator credentials."
        )

    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access restricted. Administrative privileges required."
        )

    access_token = create_access_token(data={"sub": str(user.id), "email": user.email, "role": "admin"})

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_admin": True,
        }
    }


@router.get("/me")
def get_admin_me(current_admin: User = Depends(require_admin)):
    """Validates active admin session."""
    return {
        "id": current_admin.id,
        "name": current_admin.name,
        "email": current_admin.email,
        "is_admin": True,
    }
    """Dependency that ensures only administrators can access admin routes."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required to access this endpoint."
        )
    return current_user


# ─── User Management (CRUD & Filtering) ──────────────────────────────────────

@router.get("/users")
def list_users(
    search: Optional[str] = Query(None, description="Search by name or email"),
    plan: Optional[str] = Query(None, description="Filter by plan: free, day_pass, pro_monthly"),
    role: Optional[str] = Query(None, description="Filter by role: admin, user"),
    sort_by: str = Query("created_at", description="Field to sort by: created_at, name, email"),
    sort_order: str = Query("desc", description="asc or desc"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    List all registered users with detailed stats, subscription info, and search filters.
    """
    q = db.query(User)

    if search:
        search_fmt = f"%{search.strip().lower()}%"
        q = q.filter(
            func.lower(User.name).like(search_fmt) | func.lower(User.email).like(search_fmt)
        )

    if role == "admin":
        q = q.filter(User.is_admin == True)
    elif role == "user":
        q = q.filter(User.is_admin == False)

    total_count = q.count()

    if sort_order.lower() == "asc":
        q = q.order_by(getattr(User, sort_by, User.created_at).asc())
    else:
        q = q.order_by(getattr(User, sort_by, User.created_at).desc())

    users = q.offset(skip).limit(limit).all()

    items = []
    for u in users:
        sub = get_or_create_subscription(db, u.id)
        if plan and sub.plan_type != plan:
            continue

        # User metrics
        resume_count = db.query(Resume).filter(Resume.user_id == u.id, Resume.is_deleted == False).count()
        branch_count = db.query(Resume).filter(
            Resume.user_id == u.id,
            Resume.is_deleted == False,
            Resume.parent_resume_id.isnot(None)
        ).count()
        export_count = db.query(ExportedResume).filter(ExportedResume.user_id == u.id, ExportedResume.is_deleted == False).count()
        tmpl_count = db.query(ResumeTemplate).filter(ResumeTemplate.user_id == u.id, ResumeTemplate.is_deleted == False).count()
        job_helps = db.query(AIUsageLog).filter(AIUsageLog.user_id == u.id, AIUsageLog.action_type == "wiser_job_help").count()
        ats_checks = db.query(AIUsageLog).filter(AIUsageLog.user_id == u.id, AIUsageLog.action_type == "wiser_ats_check").count()

        items.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "is_admin": u.is_admin,
            "created_at": u.created_at,
            "subscription": {
                "plan_type": sub.plan_type,
                "plan_name": PLAN_CONFIGS.get(sub.plan_type, {}).get("name", "Pagewise Free"),
                "status": sub.status,
                "expires_at": sub.expires_at,
            },
            "metrics": {
                "resumes": resume_count,
                "branched_resumes": branch_count,
                "exports": export_count,
                "custom_templates": tmpl_count,
                "wiser_job_helps": job_helps,
                "wiser_ats_checks": ats_checks,
                "wiser_total": job_helps + ats_checks,
            }
        })

    return {
        "total": total_count,
        "skip": skip,
        "limit": limit,
        "users": items
    }


@router.get("/users/{user_id}")
def get_user_detail(
    user_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Retrieve full profile and activity details of a specific user."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    plan_status = get_user_plan_status(db, u)
    active_ids = get_user_active_workspace_ids(db, u)
    resumes = db.query(Resume).filter(Resume.user_id == u.id, Resume.is_deleted == False).order_by(Resume.is_primary.desc(), Resume.updated_at.desc()).all()
    exports = db.query(ExportedResume).filter(ExportedResume.user_id == u.id, ExportedResume.is_deleted == False).order_by(ExportedResume.created_at.desc()).all()
    templates = db.query(ResumeTemplate).filter(ResumeTemplate.user_id == u.id, ResumeTemplate.is_deleted == False).order_by(ResumeTemplate.created_at.desc()).all()
    payments = db.query(PaymentOrder).filter(PaymentOrder.user_id == u.id).order_by(PaymentOrder.created_at.desc()).all()
    ai_logs = db.query(AIUsageLog).filter(AIUsageLog.user_id == u.id).order_by(AIUsageLog.created_at.desc()).limit(30).all()

    total_spent_inr = sum(p.amount_inr for p in payments if p.status == "paid")
    branched_count = sum(1 for r in resumes if r.parent_resume_id is not None)

    return {
        "user": {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "is_admin": u.is_admin,
            "created_at": u.created_at,
            "updated_at": u.updated_at,
        },
        "plan_status": plan_status,
        "metrics_summary": {
            "total_resumes": len(resumes),
            "master_resumes": sum(1 for r in resumes if r.is_primary),
            "branched_resumes": branched_count,
            "total_exports": len(exports),
            "total_templates": len(templates),
            "total_payments_count": len(payments),
            "total_spent_inr": total_spent_inr,
            "total_ai_logs": len(ai_logs),
        },
        "resumes": [
            {
                "id": r.id,
                "name": r.name,
                "is_primary": bool(r.is_primary),
                "is_locked": (r.id not in active_ids),
                "parent_resume_id": r.parent_resume_id,
                "is_branched": bool(r.parent_resume_id is not None),
                "target_job_title": r.target_job_title,
                "target_company": r.target_company,
                "target_ats_score": r.target_ats_score,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in resumes
        ],
        "exports": [
            {
                "id": e.id,
                "resume_name": e.resume_name,
                "file_type": e.file_type,
                "file_name": e.file_name,
                "file_size": e.file_size,
                "target_job_title": e.target_job_title,
                "target_company": e.target_company,
                "template_name": e.template_name,
                "created_at": e.created_at,
            }
            for e in exports
        ],
        "templates": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "created_at": t.created_at,
            }
            for t in templates
        ],
        "payments": [
            {
                "id": p.id,
                "amount_inr": p.amount_inr,
                "plan_type": p.plan_type,
                "status": p.status,
                "razorpay_order_id": p.razorpay_order_id,
                "razorpay_payment_id": p.razorpay_payment_id,
                "created_at": p.created_at,
            }
            for p in payments
        ],
        "ai_logs": [
            {
                "id": a.id,
                "action_type": a.action_type,
                "ai_model": a.ai_model,
                "tokens_used": a.tokens_used,
                "created_at": a.created_at,
                "meta_json": a.meta_json,
            }
            for a in ai_logs
        ],
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Admin endpoint to create a new user account with specific role and plan."""
    norm_email = payload.email.lower().strip()
    existing = db.query(User).filter(User.email == norm_email).first()
    if existing:
        raise HTTPException(status_code=400, detail="User with this email already exists")

    hashed = hash_password(payload.password)
    user = User(
        name=payload.name.strip(),
        email=norm_email,
        hashed_password=hashed,
        is_admin=bool(payload.is_admin)
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Initialize plan
    sub = get_or_create_subscription(db, user.id)
    if payload.plan_type and payload.plan_type in PLAN_CONFIGS:
        sub.plan_type = payload.plan_type
        if payload.plan_type == PlanType.DAY_PASS:
            sub.expires_at = datetime.utcnow() + timedelta(days=1)
        elif payload.plan_type == PlanType.PRO_MONTHLY:
            sub.expires_at = datetime.utcnow() + timedelta(days=30)
        else:
            sub.expires_at = None
        db.commit()

    return {
        "message": "User created successfully",
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "is_admin": user.is_admin,
        "plan_type": sub.plan_type
    }


@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Admin endpoint to edit user name, email, password, admin role, or subscription tier."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.name is not None:
        user.name = payload.name.strip()

    if payload.email is not None:
        norm_email = payload.email.lower().strip()
        conflict = db.query(User).filter(User.email == norm_email, User.id != user_id).first()
        if conflict:
            raise HTTPException(status_code=400, detail="Email is already used by another account")
        user.email = norm_email

    if payload.password is not None and payload.password.strip():
        user.hashed_password = hash_password(payload.password.strip())

    if payload.is_admin is not None:
        user.is_admin = bool(payload.is_admin)

    if payload.plan_type is not None and payload.plan_type in PLAN_CONFIGS:
        sub = get_or_create_subscription(db, user.id)
        sub.plan_type = payload.plan_type
        if payload.plan_type == PlanType.DAY_PASS:
            sub.expires_at = datetime.utcnow() + timedelta(days=1)
        elif payload.plan_type == PlanType.PRO_MONTHLY:
            sub.expires_at = datetime.utcnow() + timedelta(days=30)
        else:
            sub.expires_at = None

    db.commit()
    db.refresh(user)

    return {
        "message": "User updated successfully",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_admin": user.is_admin,
        }
    }


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Admin endpoint to delete a user account and all cascading records."""
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Admins cannot delete their own current account")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    db.delete(user)
    db.commit()
    return {"message": f"User #{user_id} deleted successfully"}


# ─── Confidential Admin Account Self-Update ──────────────────────────────────

@router.put("/me/security")
def update_admin_self_credentials(
    payload: AdminResetSelfPassword,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Allows the logged-in administrator to confidentially update their password,
    email, or display name with required current password verification.
    """
    if not verify_password(payload.current_password, current_admin.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password verification failed. Please enter your correct current password."
        )

    if payload.new_email:
        norm_email = payload.new_email.lower().strip()
        conflict = db.query(User).filter(User.email == norm_email, User.id != current_admin.id).first()
        if conflict:
            raise HTTPException(status_code=400, detail="Email is already used by another account")
        current_admin.email = norm_email

    if payload.new_name:
        current_admin.name = payload.new_name.strip()

    if payload.new_password and payload.new_password.strip():
        current_admin.hashed_password = hash_password(payload.new_password.strip())

    current_admin.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_admin)

    return {
        "success": True,
        "message": "Admin credentials updated successfully.",
        "admin": {
            "id": current_admin.id,
            "name": current_admin.name,
            "email": current_admin.email,
        }
    }


# ─── Deep Insights & Aggregated Analytics ────────────────────────────────────

def compute_metric_stat(db: Session, model_class, user_id_col, extra_filter=None) -> MetricStat:
    """Helper to calculate total, avg per head, max per head, and min per head."""
    total_users = db.query(User).count()
    if total_users == 0:
        return MetricStat(total=0, avg_per_user=0.0, max_per_user=0, min_per_user=0)

    # Count total items
    q = db.query(func.count(model_class.id))
    if hasattr(model_class, "is_deleted"):
        q = q.filter(model_class.is_deleted == False)
    if extra_filter is not None:
        q = q.filter(extra_filter)
    total_items = q.scalar() or 0

    # Group counts per user
    grp_q = db.query(user_id_col, func.count(model_class.id).label("cnt"))
    if hasattr(model_class, "is_deleted"):
        grp_q = grp_q.filter(model_class.is_deleted == False)
    if extra_filter is not None:
        grp_q = grp_q.filter(extra_filter)
    user_counts = {r[0]: r[1] for r in grp_q.group_by(user_id_col).all()}

    # All users including those with 0
    all_user_ids = [uid[0] for uid in db.query(User.id).all()]
    counts_list = [user_counts.get(uid, 0) for uid in all_user_ids]

    avg_val = round(total_items / total_users, 2) if total_users > 0 else 0.0
    max_val = max(counts_list) if counts_list else 0
    min_val = min(counts_list) if counts_list else 0

    return MetricStat(
        total=total_items,
        avg_per_user=avg_val,
        max_per_user=max_val,
        min_per_user=min_val
    )


@router.get("/insights", response_model=AdminInsightsResponse)
def get_admin_insights(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Returns deep analytics on:
    - AI Usage (Wiser Job Help, Wiser ATS evaluations, total tokens, daily trends)
    - Resumes (Total, per-head avg/max/min)
    - Branched Resumes (Total, per-head avg/max/min)
    - Exports (Total, per-head avg/max/min)
    - Custom Templates (Total, per-head avg/max/min)
    - User subscription distribution
    """
    total_users = db.query(User).count()

    # Plan distribution
    subs = db.query(Subscription.plan_type, func.count(Subscription.id)).group_by(Subscription.plan_type).all()
    active_plans = {p[0]: p[1] for p in subs}
    for p in [PlanType.FREE, PlanType.DAY_PASS, PlanType.PRO_MONTHLY, PlanType.PILOT]:
        if p not in active_plans:
            active_plans[p] = 0

    # Wiser AI usage metrics
    wiser_job_helps = db.query(AIUsageLog).filter(AIUsageLog.action_type == "wiser_job_help").count()
    wiser_ats_checks = db.query(AIUsageLog).filter(AIUsageLog.action_type == "wiser_ats_check").count()
    total_ai_invocations = wiser_job_helps + wiser_ats_checks

    ai_usage = {
        "wiser_job_helps": wiser_job_helps,
        "wiser_ats_checks": wiser_ats_checks,
        "total_invocations": total_ai_invocations,
        "avg_ai_per_user": round(total_ai_invocations / total_users, 2) if total_users else 0.0
    }

    # Resource metrics
    exports_stat = compute_metric_stat(db, ExportedResume, ExportedResume.user_id)
    templates_stat = compute_metric_stat(db, ResumeTemplate, ResumeTemplate.user_id)
    resumes_stat = compute_metric_stat(db, Resume, Resume.user_id)
    branched_stat = compute_metric_stat(
        db, Resume, Resume.user_id, extra_filter=Resume.parent_resume_id.isnot(None)
    )

    return AdminInsightsResponse(
        total_users=total_users,
        active_plans=active_plans,
        ai_usage=ai_usage,
        exports=exports_stat,
        custom_templates=templates_stat,
        resumes=resumes_stat,
        branched_resumes=branched_stat
    )


# ─── Template & Tier Admin Management ──────────────────────────────────────────

def serialize_json_field(val):
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    if isinstance(val, str):
        return val
    return "{}"


def parse_json_field(val, default):
    if not val:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


@router.get("/templates")
def admin_list_templates(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Lists all global templates for admin management."""
    templates = (
        db.query(ResumeTemplate)
        .filter(ResumeTemplate.is_global == True, ResumeTemplate.is_deleted == False)
        .order_by(ResumeTemplate.display_order.asc(), ResumeTemplate.id.asc())
        .all()
    )
    out = []
    for t in templates:
        out.append({
            "id": t.id,
            "template_key": t.template_key or f"tpl-{t.id}",
            "name": t.name,
            "description": t.description or "",
            "category": t.category or "Standard",
            "badge": t.badge or "",
            "min_plan_tier": t.min_plan_tier or "free",
            "is_global": t.is_global,
            "display_order": t.display_order,
            "is_active": t.is_active,
            "settings_json": parse_json_field(t.settings_json, {}),
            "header_style_json": parse_json_field(t.header_style_json, {}),
            "section_defaults_json": parse_json_field(t.section_defaults_json, {}),
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return out


@router.post("/templates")
def admin_create_template(
    payload: AdminTemplateCreate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Creates a new global system template with specified tier access."""
    tpl_key = (payload.template_key or payload.name.lower().replace(" ", "-")).strip()
    existing = db.query(ResumeTemplate).filter(ResumeTemplate.template_key == tpl_key, ResumeTemplate.is_deleted == False).first()
    if existing:
        tpl_key = f"{tpl_key}-{int(datetime.utcnow().timestamp())}"

    tmpl = ResumeTemplate(
        user_id=None,
        is_global=True,
        template_key=tpl_key,
        name=payload.name,
        description=payload.description,
        category=payload.category or "Standard",
        badge=payload.badge or "",
        min_plan_tier=payload.min_plan_tier,
        settings_json=serialize_json_field(payload.settings_json),
        header_style_json=serialize_json_field(payload.header_style_json),
        section_defaults_json=serialize_json_field(payload.section_defaults_json),
        display_order=payload.display_order,
        is_active=payload.is_active,
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return {
        "success": True,
        "message": "Template created successfully",
        "id": tmpl.id,
        "template_key": tmpl.template_key,
    }


@router.put("/templates/{template_id}")
def admin_update_template(
    template_id: int,
    payload: AdminTemplateUpdate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Updates an existing global template's tier requirement, badge, styling, or active status."""
    tmpl = db.query(ResumeTemplate).filter(ResumeTemplate.id == template_id, ResumeTemplate.is_deleted == False).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    if payload.name is not None:
        tmpl.name = payload.name
    if payload.description is not None:
        tmpl.description = payload.description
    if payload.category is not None:
        tmpl.category = payload.category
    if payload.badge is not None:
        tmpl.badge = payload.badge
    if payload.min_plan_tier is not None:
        tmpl.min_plan_tier = payload.min_plan_tier
    if payload.display_order is not None:
        tmpl.display_order = payload.display_order
    if payload.is_active is not None:
        tmpl.is_active = payload.is_active
    if payload.settings_json is not None:
        tmpl.settings_json = serialize_json_field(payload.settings_json)
    if payload.header_style_json is not None:
        tmpl.header_style_json = serialize_json_field(payload.header_style_json)
    if payload.section_defaults_json is not None:
        tmpl.section_defaults_json = serialize_json_field(payload.section_defaults_json)

    db.commit()
    db.refresh(tmpl)
    return {
        "success": True,
        "message": "Template updated successfully",
        "id": tmpl.id,
        "template_key": tmpl.template_key,
        "min_plan_tier": tmpl.min_plan_tier,
    }


@router.delete("/templates/{template_id}")
def admin_delete_template(
    template_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Soft-deletes a global template."""
    tmpl = db.query(ResumeTemplate).filter(ResumeTemplate.id == template_id, ResumeTemplate.is_deleted == False).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    tmpl.is_deleted = True
    tmpl.deleted_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": "Template soft-deleted"}


@router.get("/tiers")
def admin_list_tiers(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Lists all configured subscription tiers and pricing parameters."""
    tiers = db.query(PlanTierConfig).order_by(PlanTierConfig.display_order.asc()).all()
    out = []
    for t in tiers:
        features = parse_json_field(t.features_json, [])
        out.append({
            "id": t.id,
            "tier_key": t.tier_key,
            "name": t.name,
            "tagline": t.tagline or "",
            "badge": t.badge or "",
            "base_price_inr": t.base_price_inr,
            "discount_price_inr": t.discount_price_inr if t.discount_price_inr is not None else t.base_price_inr,
            "discount_percent": t.discount_percent or 0,
            "billing_period_text": t.billing_period_text or "",
            "duration_days": t.duration_days,
            "resume_limit": t.resume_limit,
            "export_limit": t.export_limit,
            "wiser_ai_limit": t.wiser_ai_limit,
            "wiser_job_help_limit": t.wiser_job_help_limit,
            "wiser_ats_limit": t.wiser_ats_limit,
            "custom_template_limit": t.custom_template_limit,
            "premium_templates_allowed": t.premium_templates_allowed,
            "features": features,
            "is_active": t.is_active,
            "is_archived": getattr(t, "is_archived", False),
            "display_order": t.display_order,
        })
    return out


@router.put("/tiers/{tier_key}")
def admin_update_tier(
    tier_key: str,
    payload: PlanTierConfigUpdate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Updates pricing, quotas, features, or duration for a specific plan tier."""
    tier = db.query(PlanTierConfig).filter(PlanTierConfig.tier_key == tier_key).first()
    if not tier:
        raise HTTPException(status_code=404, detail=f"Tier '{tier_key}' not found.")

    if payload.name is not None:
        tier.name = payload.name
    if payload.tagline is not None:
        tier.tagline = payload.tagline
    if payload.badge is not None:
        tier.badge = payload.badge
    if payload.base_price_inr is not None:
        tier.base_price_inr = payload.base_price_inr
    if payload.discount_price_inr is not None:
        tier.discount_price_inr = payload.discount_price_inr
    if payload.discount_percent is not None:
        tier.discount_percent = payload.discount_percent
    if payload.billing_period_text is not None:
        tier.billing_period_text = payload.billing_period_text
    if payload.duration_days is not None:
        tier.duration_days = payload.duration_days
    if payload.resume_limit is not None:
        tier.resume_limit = payload.resume_limit
    if payload.export_limit is not None:
        tier.export_limit = payload.export_limit
    if payload.wiser_ai_limit is not None:
        tier.wiser_ai_limit = payload.wiser_ai_limit
    if payload.wiser_job_help_limit is not None:
        tier.wiser_job_help_limit = payload.wiser_job_help_limit
    if payload.wiser_ats_limit is not None:
        tier.wiser_ats_limit = payload.wiser_ats_limit
    if payload.custom_template_limit is not None:
        tier.custom_template_limit = payload.custom_template_limit
    if payload.premium_templates_allowed is not None:
        tier.premium_templates_allowed = payload.premium_templates_allowed
    if payload.features is not None:
        tier.features_json = json.dumps(payload.features)
    if payload.is_active is not None:
        tier.is_active = payload.is_active
    if payload.is_archived is not None:
        tier.is_archived = payload.is_archived
    if payload.display_order is not None:
        tier.display_order = payload.display_order

    tier.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(tier)

    return {
        "success": True,
        "message": f"Tier '{tier_key}' updated successfully.",
        "tier_key": tier.tier_key,
        "price_inr": tier.discount_price_inr if tier.discount_price_inr is not None else tier.base_price_inr,
    }


@router.post("/apply-pilot-all")
def apply_pilot_all(
    archive_others: bool = Query(True, description="Archive all non-pilot tiers to hide paid checkouts"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Activates pilot mode:
    1. Ensures PILOT tier exists in PlanTierConfig (and unarchived + active).
    2. Archives all other tiers (free, day_pass, pro_monthly) if archive_others=True.
    3. Migrates all non-admin users to PILOT tier.
    """
    pilot_tier = db.query(PlanTierConfig).filter(PlanTierConfig.tier_key == PlanType.PILOT).first()
    pilot_cfg = PLAN_CONFIGS[PlanType.PILOT]

    if not pilot_tier:
        pilot_tier = PlanTierConfig(
            tier_key=PlanType.PILOT,
            name=pilot_cfg["name"],
            tagline=pilot_cfg["tagline"],
            badge=pilot_cfg["badge"],
            base_price_inr=pilot_cfg["price_inr"],
            discount_price_inr=pilot_cfg["price_inr"],
            discount_percent=0,
            billing_period_text="Pilot Program (Free)",
            duration_days=None,
            resume_limit=pilot_cfg["resume_limit"],
            export_limit=pilot_cfg["export_limit"],
            wiser_ai_limit=pilot_cfg["wiser_ai_limit"],
            wiser_job_help_limit=pilot_cfg["wiser_job_help_limit"],
            wiser_ats_limit=pilot_cfg["wiser_ats_limit"],
            custom_template_limit=pilot_cfg["custom_template_limit"],
            premium_templates_allowed=pilot_cfg["premium_templates_allowed"],
            features_json=json.dumps(pilot_cfg["features"]),
            is_active=True,
            is_archived=False,
            display_order=0,
        )
        db.add(pilot_tier)
    else:
        pilot_tier.is_active = True
        pilot_tier.is_archived = False
        pilot_tier.resume_limit = pilot_cfg["resume_limit"]
        pilot_tier.export_limit = pilot_cfg["export_limit"]
        pilot_tier.wiser_ai_limit = pilot_cfg["wiser_ai_limit"]
        pilot_tier.wiser_job_help_limit = pilot_cfg["wiser_job_help_limit"]
        pilot_tier.wiser_ats_limit = pilot_cfg["wiser_ats_limit"]
        pilot_tier.custom_template_limit = pilot_cfg["custom_template_limit"]
        pilot_tier.premium_templates_allowed = pilot_cfg["premium_templates_allowed"]

    # Archive other tiers if requested
    if archive_others:
        other_tiers = db.query(PlanTierConfig).filter(PlanTierConfig.tier_key != PlanType.PILOT).all()
        for ot in other_tiers:
            ot.is_archived = True

    # Migrate all non-admin users to pilot
    non_admins = db.query(User).filter(User.is_admin == False).all()
    migrated_count = 0
    for u in non_admins:
        sub = get_or_create_subscription(db, u.id)
        sub.plan_type = PlanType.PILOT
        sub.status = "active"
        sub.expires_at = None
        migrated_count += 1

    db.commit()
    return {
        "success": True,
        "message": f"Successfully activated Pilot Mode! Migrated {migrated_count} non-admin user(s) to Pilot tier.",
        "migrated_users_count": migrated_count,
        "pilot_tier": {
            "tier_key": pilot_tier.tier_key,
            "name": pilot_tier.name,
            "resume_limit": pilot_tier.resume_limit,
            "export_limit": pilot_tier.export_limit,
            "wiser_job_help_limit": pilot_tier.wiser_job_help_limit,
            "wiser_ats_limit": pilot_tier.wiser_ats_limit,
            "custom_template_limit": pilot_tier.custom_template_limit,
        }
    }


@router.post("/users/bulk-plan")
def bulk_update_user_plan(
    user_ids: List[int],
    plan_type: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Bulk updates subscription tier for selected user accounts."""
    if plan_type not in PLAN_CONFIGS:
        raise HTTPException(status_code=400, detail=f"Invalid plan type '{plan_type}'")

    updated = 0
    for uid in user_ids:
        u = db.query(User).filter(User.id == uid).first()
        if u and not u.is_admin:
            sub = get_or_create_subscription(db, u.id)
            sub.plan_type = plan_type
            sub.status = "active"
            if plan_type == PlanType.DAY_PASS:
                sub.expires_at = datetime.utcnow() + timedelta(days=1)
            elif plan_type == PlanType.PRO_MONTHLY:
                sub.expires_at = datetime.utcnow() + timedelta(days=30)
            else:
                sub.expires_at = None
            updated += 1

    db.commit()
    return {"success": True, "updated_count": updated, "plan_type": plan_type}


# ─── User Feedback Telemetry & Moderation ─────────────────────────────────────

@router.get("/feedback", response_model=FeedbackListResponse)
def list_feedbacks(
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Lists submitted feedbacks with search, category, and status filters."""
    query = db.query(Feedback).outerjoin(User, Feedback.user_id == User.id)

    if category and isinstance(category, str) and category != "all":
        query = query.filter(Feedback.category == category)

    if status and isinstance(status, str) and status != "all":
        query = query.filter(Feedback.status == status)

    if search and isinstance(search, str) and search.strip():
        term = f"%{search.strip().lower()}%"
        query = query.filter(
            func.lower(Feedback.message).like(term)
            | func.lower(Feedback.title).like(term)
            | func.lower(Feedback.email).like(term)
            | func.lower(User.name).like(term)
            | func.lower(User.email).like(term)
        )

    total = query.count()

    sort_name = sort_by if isinstance(sort_by, str) else "created_at"
    sort_col = getattr(Feedback, sort_name, Feedback.created_at)
    order_val = sort_order if isinstance(sort_order, str) else "desc"
    if order_val == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()

    results = []
    for f in items:
        meta = {}
        if f.metadata_json:
            try:
                meta = json.loads(f.metadata_json)
            except Exception:
                meta = {}

        user_name = f.user.name if f.user else None
        user_email = f.user.email if f.user else f.email

        results.append(
            FeedbackOut(
                id=f.id,
                user_id=f.user_id,
                user_name=user_name,
                user_email=user_email,
                category=f.category,
                rating=f.rating,
                title=f.title,
                message=f.message,
                email=f.email or user_email,
                metadata_json=meta,
                status=f.status,
                admin_notes=f.admin_notes,
                ip_address=f.ip_address,
                created_at=f.created_at,
                updated_at=f.updated_at,
            )
        )

    total_pages = max(1, (total + page_size - 1) // page_size)
    return FeedbackListResponse(
        items=results,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/feedback/stats", response_model=FeedbackStats)
def get_feedback_stats(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Calculates summary telemetry for feedback submissions."""
    total = db.query(Feedback).count()
    new_count = db.query(Feedback).filter(Feedback.status == "new").count()
    reviewed_count = db.query(Feedback).filter(Feedback.status == "reviewed").count()
    resolved_count = db.query(Feedback).filter(Feedback.status == "resolved").count()

    avg_rating_row = db.query(func.avg(Feedback.rating)).filter(Feedback.rating != None).scalar()
    avg_rating = round(float(avg_rating_row), 1) if avg_rating_row else None

    cat_rows = db.query(Feedback.category, func.count(Feedback.id)).group_by(Feedback.category).all()
    by_category = {cat: count for cat, count in cat_rows}

    status_rows = db.query(Feedback.status, func.count(Feedback.id)).group_by(Feedback.status).all()
    by_status = {st: count for st, count in status_rows}

    return FeedbackStats(
        total=total,
        new_count=new_count,
        reviewed_count=reviewed_count,
        resolved_count=resolved_count,
        avg_rating=avg_rating,
        by_category=by_category,
        by_status=by_status,
    )


@router.patch("/feedback/{feedback_id}", response_model=FeedbackOut)
def update_feedback(
    feedback_id: int,
    payload: FeedbackAdminUpdate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Updates feedback moderation status or internal administrative notes."""
    item = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Feedback item not found.")

    if payload.status is not None:
        valid_statuses = {"new", "reviewed", "in_progress", "resolved", "archived"}
        if payload.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status '{payload.status}'")
        item.status = payload.status

    if payload.admin_notes is not None:
        item.admin_notes = payload.admin_notes

    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)

    meta = {}
    if item.metadata_json:
        try:
            meta = json.loads(item.metadata_json)
        except Exception:
            pass

    user_name = item.user.name if item.user else None
    user_email = item.user.email if item.user else item.email

    return FeedbackOut(
        id=item.id,
        user_id=item.user_id,
        user_name=user_name,
        user_email=user_email,
        category=item.category,
        rating=item.rating,
        title=item.title,
        message=item.message,
        email=item.email or user_email,
        metadata_json=meta,
        status=item.status,
        admin_notes=item.admin_notes,
        ip_address=item.ip_address,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.delete("/feedback/{feedback_id}")
def delete_feedback(
    feedback_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Deletes a feedback record permanently."""
    item = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Feedback item not found.")

    db.delete(item)
    db.commit()
    return {"success": True, "deleted_id": feedback_id}



# ─── Commerce: Finances, Orders, and Subscriptions ───────────────────────────

class AdminSubscriptionUpdatePayload(BaseModel):
    plan_type: Optional[str] = None
    status: Optional[str] = None
    extend_days: Optional[int] = None
    reset_quotas: Optional[bool] = False


@router.get("/finances")
def get_admin_finances(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Returns comprehensive financial telemetry:
    - Total Gross Revenue (All time, 30-day, 7-day, 24-hour)
    - Order volume and success/failure conversion rates
    - Revenue breakdown by plan tier
    - Recent transactions list
    """
    now = datetime.utcnow()
    day_ago = now - timedelta(days=1)
    seven_days_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)

    total_rev = db.query(func.coalesce(func.sum(PaymentOrder.amount_inr), 0)).filter(
        PaymentOrder.status == "paid"
    ).scalar() or 0

    rev_30d = db.query(func.coalesce(func.sum(PaymentOrder.amount_inr), 0)).filter(
        PaymentOrder.status == "paid",
        PaymentOrder.created_at >= thirty_days_ago
    ).scalar() or 0

    rev_7d = db.query(func.coalesce(func.sum(PaymentOrder.amount_inr), 0)).filter(
        PaymentOrder.status == "paid",
        PaymentOrder.created_at >= seven_days_ago
    ).scalar() or 0

    rev_24h = db.query(func.coalesce(func.sum(PaymentOrder.amount_inr), 0)).filter(
        PaymentOrder.status == "paid",
        PaymentOrder.created_at >= day_ago
    ).scalar() or 0

    total_orders = db.query(PaymentOrder).count()
    paid_orders = db.query(PaymentOrder).filter(PaymentOrder.status == "paid").count()
    failed_orders = db.query(PaymentOrder).filter(PaymentOrder.status == "failed").count()
    created_orders = db.query(PaymentOrder).filter(PaymentOrder.status == "created").count()

    avg_order_val = round(total_rev / paid_orders, 2) if paid_orders else 0.0

    tier_stats = db.query(
        PaymentOrder.plan_type,
        func.count(PaymentOrder.id).label("count"),
        func.coalesce(func.sum(PaymentOrder.amount_inr), 0).label("revenue")
    ).filter(
        PaymentOrder.status == "paid"
    ).group_by(PaymentOrder.plan_type).all()

    by_plan = {}
    for p, c, r in tier_stats:
        by_plan[p] = {"count": c, "revenue": r}

    recent = (
        db.query(PaymentOrder, User.name, User.email)
        .outerjoin(User, PaymentOrder.user_id == User.id)
        .order_by(PaymentOrder.created_at.desc())
        .limit(10)
        .all()
    )
    recent_transactions = []
    for order, u_name, u_email in recent:
        recent_transactions.append({
            "id": order.id,
            "user_id": order.user_id,
            "user_name": u_name or "Anonymous",
            "user_email": u_email or "N/A",
            "plan_type": order.plan_type,
            "amount_inr": order.amount_inr,
            "currency": order.currency,
            "status": order.status,
            "razorpay_order_id": order.razorpay_order_id,
            "razorpay_payment_id": order.razorpay_payment_id,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        })

    return {
        "total_revenue_inr": total_rev,
        "revenue_30d_inr": rev_30d,
        "revenue_7d_inr": rev_7d,
        "revenue_24h_inr": rev_24h,
        "total_orders": total_orders,
        "paid_orders": paid_orders,
        "failed_orders": failed_orders,
        "created_orders": created_orders,
        "average_order_value_inr": avg_order_val,
        "conversion_rate": round((paid_orders / total_orders * 100), 1) if total_orders else 0.0,
        "by_plan": by_plan,
        "recent_transactions": recent_transactions,
    }


@router.get("/orders")
def get_admin_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    status: Optional[str] = Query(None),
    plan_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Paginated model-ledger of all customer payment orders with search and filtering.
    """
    q = db.query(PaymentOrder, User.name, User.email).outerjoin(User, PaymentOrder.user_id == User.id)

    if status and status != "all":
        q = q.filter(PaymentOrder.status == status.strip().lower())

    if plan_type and plan_type != "all":
        q = q.filter(PaymentOrder.plan_type == plan_type.strip().lower())

    if search:
        s = f"%{search.strip().lower()}%"
        q = q.filter(
            (func.lower(User.email).like(s))
            | (func.lower(User.name).like(s))
            | (func.lower(PaymentOrder.razorpay_order_id).like(s))
            | (func.lower(PaymentOrder.razorpay_payment_id).like(s))
        )

    total = q.count()
    offset = (page - 1) * limit
    results = q.order_by(PaymentOrder.created_at.desc()).offset(offset).limit(limit).all()

    orders_out = []
    for order, u_name, u_email in results:
        orders_out.append({
            "id": order.id,
            "user_id": order.user_id,
            "user_name": u_name or "Unknown",
            "user_email": u_email or "N/A",
            "plan_type": order.plan_type,
            "amount_inr": order.amount_inr,
            "currency": order.currency,
            "status": order.status,
            "razorpay_order_id": order.razorpay_order_id,
            "razorpay_payment_id": order.razorpay_payment_id,
            "receipt": order.receipt,
            "error_message": order.error_message,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
        })

    paid_sum = db.query(func.coalesce(func.sum(PaymentOrder.amount_inr), 0)).filter(
        PaymentOrder.status == "paid"
    ).scalar() or 0

    return {
        "orders": orders_out,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": max(1, (total + limit - 1) // limit),
        "total_paid_inr": paid_sum,
    }


@router.get("/orders/{order_id}")
def get_admin_order_detail(
    order_id: int,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Detailed metadata view of an individual payment order."""
    res = (
        db.query(PaymentOrder, User.name, User.email)
        .outerjoin(User, PaymentOrder.user_id == User.id)
        .filter(PaymentOrder.id == order_id)
        .first()
    )
    if not res:
        raise HTTPException(status_code=404, detail="Order not found")
    order, u_name, u_email = res
    return {
        "id": order.id,
        "user_id": order.user_id,
        "user_name": u_name,
        "user_email": u_email,
        "plan_type": order.plan_type,
        "amount_inr": order.amount_inr,
        "currency": order.currency,
        "status": order.status,
        "razorpay_order_id": order.razorpay_order_id,
        "razorpay_payment_id": order.razorpay_payment_id,
        "razorpay_signature": order.razorpay_signature,
        "receipt": order.receipt,
        "error_message": order.error_message,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


@router.get("/subscriptions")
def get_admin_subscriptions(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    plan_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Lists and filters customer subscriptions with quotas and status.
    """
    q = db.query(Subscription, User.name, User.email).join(User, Subscription.user_id == User.id)

    if plan_type and plan_type != "all":
        q = q.filter(Subscription.plan_type == plan_type.strip().lower())

    if status and status != "all":
        q = q.filter(Subscription.status == status.strip().lower())

    if search:
        s = f"%{search.strip().lower()}%"
        q = q.filter((func.lower(User.email).like(s)) | (func.lower(User.name).like(s)))

    total = q.count()
    offset = (page - 1) * limit
    results = q.order_by(Subscription.updated_at.desc()).offset(offset).limit(limit).all()

    subs_out = []
    for sub, u_name, u_email in results:
        subs_out.append({
            "id": sub.id,
            "user_id": sub.user_id,
            "user_name": u_name,
            "user_email": u_email,
            "plan_type": sub.plan_type,
            "status": sub.status,
            "started_at": sub.started_at.isoformat() if sub.started_at else None,
            "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
            "resumes_created_in_period": sub.resumes_created_in_period,
            "exports_used_in_period": sub.exports_used_in_period,
            "wiser_job_help_used": sub.wiser_job_help_used,
            "wiser_ats_used": sub.wiser_ats_used,
            "razorpay_payment_id": sub.razorpay_payment_id,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
            "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
        })

    active_count = db.query(Subscription).filter(Subscription.status == "active").count()
    pro_count = db.query(Subscription).filter(Subscription.plan_type == "pro_monthly", Subscription.status == "active").count()
    day_pass_count = db.query(Subscription).filter(Subscription.plan_type == "day_pass", Subscription.status == "active").count()
    pilot_count = db.query(Subscription).filter(Subscription.plan_type == "pilot", Subscription.status == "active").count()

    return {
        "subscriptions": subs_out,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": max(1, (total + limit - 1) // limit),
        "summary": {
            "active_count": active_count,
            "pro_count": pro_count,
            "day_pass_count": day_pass_count,
            "pilot_count": pilot_count,
        }
    }


@router.put("/subscriptions/{user_id}")
def update_admin_user_subscription(
    user_id: int,
    payload: AdminSubscriptionUpdatePayload,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Manually modifies or overrides a customer's subscription plan, expiration, or quotas.
    """
    sub = get_or_create_subscription(user_id, db)

    if payload.plan_type:
        sub.plan_type = payload.plan_type.strip().lower()

    if payload.status:
        sub.status = payload.status.strip().lower()

    if payload.extend_days is not None and payload.extend_days > 0:
        base_time = sub.expires_at if (sub.expires_at and sub.expires_at > datetime.utcnow()) else datetime.utcnow()
        sub.expires_at = base_time + timedelta(days=payload.extend_days)
        sub.status = "active"

    if payload.reset_quotas:
        sub.resumes_created_in_period = 0
        sub.exports_used_in_period = 0
        sub.wiser_job_help_used = 0
        sub.wiser_ats_used = 0
        sub.period_reset_at = datetime.utcnow()

    sub.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(sub)

    return {
        "success": True,
        "message": f"Subscription updated for user #{user_id}",
        "subscription": {
            "id": sub.id,
            "user_id": sub.user_id,
            "plan_type": sub.plan_type,
            "status": sub.status,
            "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
        }
    }


# ─── Telemetry: AI Usage & Quotas ────────────────────────────────────────────

@router.get("/ai-usage")
def get_admin_ai_usage_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    action_type: Optional[str] = Query(None),
    user_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Paginated audit log of all AI invocations across the platform.
    """
    q = db.query(AIUsageLog, User.name, User.email).join(User, AIUsageLog.user_id == User.id)

    if action_type and action_type != "all":
        q = q.filter(AIUsageLog.action_type == action_type.strip().lower())

    if user_id:
        q = q.filter(AIUsageLog.user_id == user_id)

    if search:
        s = f"%{search.strip().lower()}%"
        q = q.filter((func.lower(User.email).like(s)) | (func.lower(User.name).like(s)))

    total = q.count()
    offset = (page - 1) * limit
    results = q.order_by(AIUsageLog.created_at.desc()).offset(offset).limit(limit).all()

    logs_out = []
    for log, u_name, u_email in results:
        meta = parse_json_field(log.meta_json, {})
        logs_out.append({
            "id": log.id,
            "user_id": log.user_id,
            "user_name": u_name,
            "user_email": u_email,
            "resume_id": log.resume_id,
            "action_type": log.action_type,
            "ai_model": log.ai_model or "gemini-2.5-flash",
            "tokens_used": log.tokens_used or 0,
            "meta": meta,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    return {
        "logs": logs_out,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": max(1, (total + limit - 1) // limit),
    }


@router.get("/ai-usage/stats")
def get_admin_ai_usage_stats(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Telemetry statistics for AI invocation counts, token consumption, and top users.
    """
    total_calls = db.query(AIUsageLog).count()
    total_tokens = db.query(func.coalesce(func.sum(AIUsageLog.tokens_used), 0)).scalar() or 0

    by_action = db.query(
        AIUsageLog.action_type,
        func.count(AIUsageLog.id).label("calls"),
        func.coalesce(func.sum(AIUsageLog.tokens_used), 0).label("tokens")
    ).group_by(AIUsageLog.action_type).all()

    action_summary = {}
    for a, c, t in by_action:
        action_summary[a] = {"calls": c, "tokens": t}

    by_model = db.query(
        AIUsageLog.ai_model,
        func.count(AIUsageLog.id)
    ).group_by(AIUsageLog.ai_model).all()
    model_summary = {m[0] or "default": m[1] for m in by_model}

    top_users_query = (
        db.query(
            AIUsageLog.user_id,
            User.name,
            User.email,
            func.count(AIUsageLog.id).label("calls"),
            func.coalesce(func.sum(AIUsageLog.tokens_used), 0).label("tokens")
        )
        .join(User, AIUsageLog.user_id == User.id)
        .group_by(AIUsageLog.user_id, User.name, User.email)
        .order_by(func.sum(AIUsageLog.tokens_used).desc())
        .limit(10)
        .all()
    )
    top_users = []
    for uid, name, email, calls, tokens in top_users_query:
        top_users.append({
            "user_id": uid,
            "name": name,
            "email": email,
            "calls": calls,
            "tokens": tokens,
        })

    return {
        "total_calls": total_calls,
        "total_tokens": total_tokens,
        "by_action": action_summary,
        "by_model": model_summary,
        "top_users": top_users,
    }
