import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, PaymentOrder, Subscription, PlanType
from ..auth import get_current_user
from ..config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
from ..schemas import CreateOrderRequest, VerifyPaymentRequest, PlanStatusResponse
from ..services.subscription import (
    PLAN_CONFIGS,
    get_or_create_subscription,
    get_user_plan_status
)

router = APIRouter(prefix="/api/payments", tags=["Payments"])


def get_razorpay_client():
    """Returns Razorpay client instance if keys are configured."""
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
        return None
    try:
        import razorpay
        return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    except Exception as e:
        print(f"[Razorpay] Client initialization failed: {e}")
        return None


@router.get("/config")
def get_payment_config():
    """Provides public Razorpay key ID to frontend for initiating checkout."""
    return {
        "key_id": RAZORPAY_KEY_ID or "rzp_test_placeholder",
        "currency": "INR",
        "plans": PLAN_CONFIGS
    }


@router.get("/status", response_model=PlanStatusResponse)
def get_current_plan_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns active plan, quotas, and current consumption for authenticated user."""
    return get_user_plan_status(db, current_user)


@router.post("/create-order")
def create_payment_order(
    payload: CreateOrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Creates a Razorpay Order for purchasing Day Pass (₹49) or Pagewise Pro (₹199).
    Also supports sandbox/mock order creation if keys are running in initial test setup.
    """
    plan_info = PLAN_CONFIGS.get(payload.plan_type)
    if not plan_info or plan_info["price_inr"] <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or free plan selected: '{payload.plan_type}'."
        )

    amount_inr = plan_info["price_inr"]
    amount_paise = amount_inr * 100
    receipt = f"rcpt_u{current_user.id}_{int(datetime.utcnow().timestamp())}"

    client = get_razorpay_client()
    order_id = None

    if client:
        try:
            rzp_order = client.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt,
                "notes": {
                    "user_id": str(current_user.id),
                    "user_email": current_user.email,
                    "plan_type": payload.plan_type,
                    "plan_name": plan_info["name"]
                }
            })
            order_id = rzp_order.get("id")
        except Exception as e:
            print(f"[Razorpay] Order creation API error: {e}")
            raise HTTPException(status_code=502, detail=f"Failed to create Razorpay order: {str(e)}")
    else:
        # Fallback simulation order if test credentials not configured in environment yet
        order_id = f"order_test_{int(datetime.utcnow().timestamp())}_{current_user.id}"

    # Persist order record in database
    payment_order = PaymentOrder(
        user_id=current_user.id,
        plan_type=payload.plan_type,
        amount_inr=amount_inr,
        currency="INR",
        status="created",
        razorpay_order_id=order_id,
        receipt=receipt
    )
    db.add(payment_order)
    db.commit()
    db.refresh(payment_order)

    return {
        "order_id": order_id,
        "amount": amount_paise,
        "amount_inr": amount_inr,
        "currency": "INR",
        "plan_type": payload.plan_type,
        "plan_name": plan_info["name"],
        "key_id": RAZORPAY_KEY_ID or "rzp_test_placeholder",
        "user_name": current_user.name,
        "user_email": current_user.email
    }


@router.post("/verify")
def verify_payment(
    payload: VerifyPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verifies the Razorpay payment signature and upgrades user's subscription.
    """
    # Find matching order
    order = (
        db.query(PaymentOrder)
        .filter(PaymentOrder.razorpay_order_id == payload.razorpay_order_id, PaymentOrder.user_id == current_user.id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Payment order not found")

    client = get_razorpay_client()
    if client and RAZORPAY_KEY_SECRET:
        try:
            client.utility.verify_payment_signature({
                "razorpay_order_id": payload.razorpay_order_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
                "razorpay_signature": payload.razorpay_signature,
            })
        except Exception as e:
            order.status = "failed"
            order.error_message = f"Signature verification failed: {str(e)}"
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid payment signature")
    else:
        # Development / test fallback verification
        pass

    # Mark order as paid
    order.status = "paid"
    order.razorpay_payment_id = payload.razorpay_payment_id
    order.razorpay_signature = payload.razorpay_signature
    order.updated_at = datetime.utcnow()

    # Upgrade or extend user's subscription
    sub = get_or_create_subscription(db, current_user.id)
    plan_info = PLAN_CONFIGS.get(order.plan_type, PLAN_CONFIGS[PlanType.PRO_MONTHLY])

    now = datetime.utcnow()
    sub.plan_type = order.plan_type
    sub.status = "active"
    sub.started_at = now
    sub.razorpay_order_id = payload.razorpay_order_id
    sub.razorpay_payment_id = payload.razorpay_payment_id

    # Reset period usage counters for new subscription period
    sub.exports_used_in_period = 0
    sub.wiser_job_help_used = 0
    sub.wiser_ats_used = 0
    sub.period_reset_at = now

    if plan_info.get("duration_days"):
        sub.expires_at = now + timedelta(days=plan_info["duration_days"])
    else:
        sub.expires_at = None

    db.commit()

    return {
        "success": True,
        "message": f"Successfully activated {plan_info['name']}!",
        "plan_status": get_user_plan_status(db, current_user)
    }
