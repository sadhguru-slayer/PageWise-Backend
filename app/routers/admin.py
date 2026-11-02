from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import User, Resume, ResumeTemplate, ExportedResume, AIUsageLog, Subscription, PaymentOrder, PlanType
from ..auth import get_current_user, hash_password, verify_password, create_access_token
from ..schemas import (
    UserOut,
    AdminLoginRequest,
    AdminUserCreate,
    AdminUserUpdate,
    AdminResetSelfPassword,
    AdminInsightsResponse,
    MetricStat
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
        elif payload.plan_type == PlanType.FREE:
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
    for p in [PlanType.FREE, PlanType.DAY_PASS, PlanType.PRO_MONTHLY]:
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
