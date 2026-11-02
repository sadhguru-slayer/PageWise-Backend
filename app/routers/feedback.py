from datetime import datetime, timedelta
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import Feedback, User
from ..auth import get_current_user_optional, get_current_user
from ..schemas import FeedbackCreate, FeedbackOut

router = APIRouter(prefix="/api/feedback", tags=["Feedback"])

# In-memory IP submission timestamp cache for burst rate limiting
# Key: client_ip, Value: list of datetime timestamps
_submission_cache = {}


def get_client_ip(request: Request) -> str:
    """Extract real client IP considering reverse proxy headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


@router.post("", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackCreate,
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """
    Submits user feedback with anti-spam protections:
    - Honeypot validation (website_hp must be empty)
    - Sliding window rate limiting (max 5 submissions per hour per IP)
    - Duplicate message suppression within 10 minutes
    - Optional authenticated user binding
    """
    client_ip = get_client_ip(request)
    user_agent = (request.headers.get("user-agent") or "")[:500]

    # 1. Honeypot check (hidden bot field)
    if payload.website_hp and payload.website_hp.strip():
        # Bot filled the invisible trap field
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Automated submission blocked.",
        )

    # 2. Minimum content check
    clean_message = (payload.message or "").strip()
    if len(clean_message) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feedback message must be at least 5 characters long.",
        )

    # 3. Rate limiting by IP (max 5 per hour)
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    hourly_count = (
        db.query(Feedback)
        .filter(Feedback.ip_address == client_ip, Feedback.created_at >= one_hour_ago)
        .count()
    )
    if hourly_count >= 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You have submitted several feedbacks recently. Please try again in an hour.",
        )

    # 4. Duplicate message suppression within 10 minutes
    ten_mins_ago = datetime.utcnow() - timedelta(minutes=10)
    duplicate = (
        db.query(Feedback)
        .filter(
            Feedback.ip_address == client_ip,
            Feedback.message == clean_message,
            Feedback.created_at >= ten_mins_ago,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Duplicate feedback recently submitted. Thank you for your input!",
        )

    # 5. Metadata JSON formatting
    meta = payload.metadata_json or {}
    if not isinstance(meta, dict):
        try:
            meta = json.loads(str(meta))
        except Exception:
            meta = {}
    
    meta_str = json.dumps(meta)

    # 6. Contact Email determination
    contact_email = payload.email
    if current_user and not contact_email:
        contact_email = current_user.email

    # 7. Persist Feedback Record
    feedback = Feedback(
        user_id=current_user.id if current_user else None,
        category=(payload.category or "pilot_feedback").lower().strip(),
        rating=payload.rating,
        title=(payload.title or "").strip() or None,
        message=clean_message,
        email=contact_email,
        metadata_json=meta_str,
        status="new",
        ip_address=client_ip,
        user_agent=user_agent,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)

    # Construct response with user details if available
    return FeedbackOut(
        id=feedback.id,
        user_id=feedback.user_id,
        user_name=current_user.name if current_user else None,
        user_email=current_user.email if current_user else feedback.email,
        category=feedback.category,
        rating=feedback.rating,
        title=feedback.title,
        message=feedback.message,
        email=feedback.email,
        metadata_json=meta,
        status=feedback.status,
        admin_notes=feedback.admin_notes,
        ip_address=feedback.ip_address,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


@router.get("/my", response_model=List[FeedbackOut])
def get_my_feedback(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Returns feedback submitted by the currently authenticated user."""
    items = (
        db.query(Feedback)
        .filter(Feedback.user_id == current_user.id)
        .order_by(Feedback.created_at.desc())
        .limit(50)
        .all()
    )
    results = []
    for f in items:
        meta = {}
        try:
            meta = json.loads(f.metadata_json) if f.metadata_json else {}
        except Exception:
            pass
        results.append(
            FeedbackOut(
                id=f.id,
                user_id=f.user_id,
                user_name=current_user.name,
                user_email=current_user.email,
                category=f.category,
                rating=f.rating,
                title=f.title,
                message=f.message,
                email=f.email,
                metadata_json=meta,
                status=f.status,
                admin_notes=f.admin_notes,
                ip_address=f.ip_address,
                created_at=f.created_at,
                updated_at=f.updated_at,
            )
        )
    return results
