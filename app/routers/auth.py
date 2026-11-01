from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import json

from ..database import get_db
from ..models import User
from ..schemas import UserRegister, UserLogin, AuthResponse, UserOut, UserPreferencesUpdate
from ..auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    """Registers a new user with email, name, and hashed password."""
    # Check if user already exists
    normalized_email = payload.email.lower().strip()
    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    # Hash the password
    hashed_pwd = hash_password(payload.password)

    # Create user
    user = User(
        name=payload.name.strip(),
        email=normalized_email,
        hashed_password=hashed_pwd,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Generate JWT token
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

    # Generate JWT token
    access_token = create_access_token(data={"sub": str(user.id), "email": user.email})

    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserOut.from_orm(user),
    )


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """Returns the currently authenticated user profile."""
    # Ensure preferences_json is parsed as dict or fallback
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
    db: Session = Depends(get_db)
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
