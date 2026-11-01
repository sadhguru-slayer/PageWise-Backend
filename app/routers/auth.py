import random
import json
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import (
    UserRegister,
    UserLogin,
    AuthResponse,
    UserOut,
    UserPreferencesUpdate,
    ForgotPasswordRequest,
    VerifyResetOTPRequest,
    ResetPasswordRequest,
    ProfileVerifyResetOTPRequest,
    ProfileResetPasswordRequest,
    MessageResponse,
    ResetTokenResponse,
)
from ..auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_reset_token,
    verify_reset_token,
    get_current_user,
)
from ..services.otp import OTPService, OTPPurpose
from ..services.email import send_otp_email

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


# ─── Standard Auth ────────────────────────────────────────────────────────────

@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    """Registers a new user with email, name, and hashed password."""
    normalized_email = payload.email.lower().strip()
    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    hashed_pwd = hash_password(payload.password)
    user = User(
        name=payload.name.strip(),
        email=normalized_email,
        hashed_password=hashed_pwd,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token = create_access_token(data={"sub": str(user.id), "email": user.email})

    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=AuthResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """Authenticates a user and returns a signed JWT access token."""
    normalized_email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == normalized_email).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id), "email": user.email})

    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Returns the currently authenticated user profile."""
    prefs = current_user.preferences_json
    if isinstance(prefs, str):
        try:
            prefs = json.loads(prefs)
        except Exception:
            prefs = {}
    return UserOut(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        preferences_json=prefs or {},
        created_at=current_user.created_at,
    )


@router.put("/preferences", response_model=UserOut)
def update_preferences(
    payload: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Updates user studio preferences (such as allow_bold_text) and full name."""
    existing_prefs = {}
    if current_user.preferences_json:
        try:
            existing_prefs = json.loads(current_user.preferences_json)
        except Exception:
            existing_prefs = {}

    if payload.name:
        current_user.name = payload.name.strip()

    if payload.allow_bold_text is not None:
        existing_prefs["allow_bold_text"] = bool(payload.allow_bold_text)

    current_user.preferences_json = json.dumps(existing_prefs)
    db.commit()
    db.refresh(current_user)

    return UserOut(
        id=current_user.id,
        name=current_user.name,
        email=current_user.email,
        preferences_json=existing_prefs,
        created_at=current_user.created_at,
    )


# ─── Forgot Password Flow (Unauthenticated) ───────────────────────────────────

@router.post("/request-password-reset", response_model=MessageResponse)
@router.post("/forgot-password/request-otp", response_model=MessageResponse)
async def request_password_reset(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Generates a 6-digit OTP code, stores it in Redis, and sends an email to the user."""
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No account registered with this email address.",
        )

    # Generate 6-digit OTP
    otp_code = f"{random.randint(100000, 999999)}"
    await OTPService.save(OTPPurpose.PASSWORD_RESET, user.email, otp_code, expire_seconds=600)

    # Send email in background
    background_tasks.add_task(send_otp_email, user.email, otp_code, OTPPurpose.PASSWORD_RESET)

    return MessageResponse(message=f"Verification code has been sent to {user.email}.")


@router.post("/verify-reset-otp", response_model=ResetTokenResponse)
@router.post("/forgot-password/verify-otp", response_model=ResetTokenResponse)
async def verify_reset_otp(
    payload: VerifyResetOTPRequest,
    db: Session = Depends(get_db),
):
    """Verifies the OTP against Redis and issues a short-lived scoped reset token."""
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    stored_otp = await OTPService.get(OTPPurpose.PASSWORD_RESET, email)
    if not stored_otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired or was not requested. Please request a new code.",
        )

    if stored_otp.strip() != payload.otp.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please check your email and try again.",
        )

    # Consume the OTP once verified
    await OTPService.delete(OTPPurpose.PASSWORD_RESET, email)

    # Issue scoped reset token (15 mins)
    reset_token = create_reset_token(email=user.email, user_id=user.id, scope="password_reset", expires_minutes=15)
    return ResetTokenResponse(reset_token=reset_token, message="Verification code confirmed.")


@router.post("/reset-password", response_model=MessageResponse)
@router.post("/forgot-password/reset-password", response_model=MessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """Resets the account password using the verified reset token."""
    token_payload = verify_reset_token(payload.reset_token, expected_scope="password_reset")
    user_id = int(token_payload["sub"])

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found.",
        )

    if len(payload.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long.",
        )

    user.hashed_password = hash_password(payload.new_password)
    db.commit()

    return MessageResponse(message="Your password has been reset successfully. You can now sign in.")


# ─── Profile Reset Password Flow (Authenticated) ──────────────────────────────

@router.post("/profile/request-reset-otp", response_model=MessageResponse)
async def profile_request_reset_otp(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Requests a security OTP to reset password from inside user profile/settings."""
    otp_code = f"{random.randint(100000, 999999)}"
    await OTPService.save(OTPPurpose.PROFILE_PASSWORD_RESET, current_user.email, otp_code, expire_seconds=600)

    background_tasks.add_task(send_otp_email, current_user.email, otp_code, OTPPurpose.PROFILE_PASSWORD_RESET)

    return MessageResponse(message=f"Security verification code dispatched to {current_user.email}.")


@router.post("/profile/verify-reset-otp", response_model=ResetTokenResponse)
async def profile_verify_reset_otp(
    payload: ProfileVerifyResetOTPRequest,
    current_user: User = Depends(get_current_user),
):
    """Verifies the OTP entered in profile settings and returns a profile reset token."""
    stored_otp = await OTPService.get(OTPPurpose.PROFILE_PASSWORD_RESET, current_user.email)
    if not stored_otp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired or was not requested. Please request a new code.",
        )

    if stored_otp.strip() != payload.otp.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please check your email.",
        )

    # Consume OTP
    await OTPService.delete(OTPPurpose.PROFILE_PASSWORD_RESET, current_user.email)

    reset_token = create_reset_token(
        email=current_user.email,
        user_id=current_user.id,
        scope="profile_password_reset",
        expires_minutes=15,
    )
    return ResetTokenResponse(reset_token=reset_token, message="Security verification accepted.")


@router.post("/profile/reset-password", response_model=MessageResponse)
def profile_reset_password(
    payload: ProfileResetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resets password for the logged-in profile after OTP verification."""
    token_payload = verify_reset_token(payload.reset_token, expected_scope="profile_password_reset")
    token_user_id = int(token_payload["sub"])

    if token_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not belong to the current authenticated user.",
        )

    if len(payload.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long.",
        )

    current_user.hashed_password = hash_password(payload.new_password)
    db.commit()

    return MessageResponse(message="Password updated successfully.")
