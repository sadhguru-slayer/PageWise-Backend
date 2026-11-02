import json
from datetime import datetime
from typing import Optional, Any, List
from pydantic import BaseModel, EmailStr, Field, field_validator


# ─── Auth Schemas ────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    register_token: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    is_admin: Optional[bool] = False
    preferences_json: Optional[Any] = {}
    created_at: datetime

    @field_validator("preferences_json", mode="before")
    @classmethod
    def parse_prefs(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {}
        return v or {}

    class Config:
        from_attributes = True


class UserPreferencesUpdate(BaseModel):
    name: Optional[str] = None
    allow_bold_text: Optional[bool] = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── OTP Schemas (Register, Login, Password Reset) ───────────────────────────

class RegisterOTPRequest(BaseModel):
    email: EmailStr


class RegisterOTPVerify(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=10)


class RegisterTokenResponse(BaseModel):
    register_token: str
    message: str = "Email verified successfully"


class LoginOTPRequest(BaseModel):
    email: EmailStr


class LoginOTPVerify(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=10)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyResetOTPRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=4, max_length=10)


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(..., min_length=6, max_length=128)


class ProfileVerifyResetOTPRequest(BaseModel):
    otp: str = Field(..., min_length=4, max_length=10)


class ProfileResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(..., min_length=6, max_length=128)


class MessageResponse(BaseModel):
    message: str


class ResetTokenResponse(BaseModel):
    reset_token: str
    message: str = "OTP verified successfully"


# ─── Resume Schemas ──────────────────────────────────────────────────────────

class ResumeBase(BaseModel):
    name: str = "Untitled Resume"
    header_json: Any = {}
    settings_json: Any = {}
    sections_json: Any = []


class ResumeCreate(ResumeBase):
    pass


class ResumeUpdate(BaseModel):
    name: Optional[str] = None
    header_json: Optional[Any] = None
    settings_json: Optional[Any] = None
    sections_json: Optional[Any] = None
    # Job targeting fields
    target_job_title: Optional[str] = None
    target_company: Optional[str] = None
    target_job_description: Optional[str] = None
    target_ats_score: Optional[float] = None
    jd_analysis_json: Optional[Any] = {}


class ResumeSummary(BaseModel):
    id: int
    user_id: int
    name: str
    created_at: datetime
    updated_at: datetime
    section_count: Optional[int] = 0
    # Job targeting
    target_job_title: Optional[str] = None
    target_company: Optional[str] = None
    target_ats_score: Optional[float] = None
    is_primary: Optional[bool] = False
    is_locked: Optional[bool] = False
    parent_resume_id: Optional[int] = None

    class Config:
        from_attributes = True


class ResumeDetail(BaseModel):
    id: int
    user_id: int
    name: str
    header_json: Any
    settings_json: Any
    sections_json: Any
    created_at: datetime
    updated_at: datetime
    # Job targeting
    target_job_title: Optional[str] = None
    target_company: Optional[str] = None
    target_job_description: Optional[str] = None
    target_ats_score: Optional[float] = None
    jd_analysis_json: Optional[Any] = {}
    is_primary: Optional[bool] = False
    is_locked: Optional[bool] = False
    parent_resume_id: Optional[int] = None

    class Config:
        from_attributes = True


# ─── Resume Clone Request ─────────────────────────────────────────────────────

class ResumeCloneRequest(BaseModel):
    new_name: Optional[str] = None
    target_job_title: Optional[str] = None
    target_company: Optional[str] = None
    target_job_description: Optional[str] = None
    target_ats_score: Optional[float] = None
    jd_analysis_json: Optional[Any] = {}


# ─── User Template Schemas ───────────────────────────────────────────────────

class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    settings_json: Any = {}
    header_style_json: Any = {}
    section_defaults_json: Any = {}


class TemplateOut(BaseModel):
    id: int
    user_id: int
    name: str
    description: Optional[str] = None
    settings_json: Any
    header_style_json: Any
    section_defaults_json: Any
    created_at: datetime

    class Config:
        from_attributes = True


# ─── Export Schemas ──────────────────────────────────────────────────────────

class ExportPDFRequest(BaseModel):
    resume_id: Optional[int] = None
    name: str = "Resume"
    html: str


class ExportImageRequest(BaseModel):
    resume_id: Optional[int] = None
    name: str = "Resume"
    html: str


class ExportHTMLRequest(BaseModel):
    resume_id: Optional[int] = None
    name: str = "Resume"
    html: str


class ExportDocxRequest(BaseModel):
    resume_id: Optional[int] = None
    name: str = "Resume"
    header_json: Any = {}
    settings_json: Any = {}
    sections_json: Any = []


class ExportedResumeOut(BaseModel):
    id: int
    resume_id: Optional[int]
    resume_name: str
    file_type: str
    file_name: str
    file_size: int
    target_job_title: Optional[str] = None
    target_company: Optional[str] = None
    template_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ─── JD & ATS Analysis Schemas ───────────────────────────────────────────────

class JDAnalyzeRequest(BaseModel):
    resume_id: Optional[int] = None
    job_description: str
    current_resume_override: Optional[Any] = None
    include_all_user_resumes: Optional[bool] = True


class ATSAnalyzeRequest(BaseModel):
    """Request payload for standalone Wiser ATS audit (no JD required)."""
    resume_id: Optional[int] = None
    current_resume_override: Optional[Any] = None


# ─── Usage Stats Schema ───────────────────────────────────────────────────────

class UsageStats(BaseModel):
    # Active resources currently in workspace
    resume_count: int = 0
    template_count: int = 0
    export_count: int = 0
    targeted_resume_count: int = 0

    # Lifetime total resources created (including soft-deleted)
    total_resumes_generated: int = 0
    total_templates_created: int = 0
    total_exports_generated: int = 0

    # Wiser AI Layer metrics (subscriptions & quota enforcement)
    jd_analyses_count: int = 0          # Alias for wiser_job_helps_count
    wiser_job_helps_count: int = 0      # Wiser Job Help (JD + ATS match runs)
    wiser_ats_checks_count: int = 0     # Wiser ATS (Standalone ATS checks)
    wiser_total_invocations: int = 0    # Grand total AI actions in selected period

    # Date Range & Billing Cycle metadata
    period: str = "all"                 # "this_billing" | "prev_billing" | "last_3_months" | "all"
    period_label: str = "All Time"
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None

    # Resources generated strictly within the selected duration
    period_resumes_created: int = 0
    period_templates_created: int = 0
    period_exports_generated: int = 0


# ─── Payment & Subscription Schemas ──────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    plan_type: str  # "day_pass" | "pro_monthly"


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PlanStatusResponse(BaseModel):
    plan_type: str
    plan_name: str
    status: str
    is_admin: bool
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    limits: dict
    usage: dict
    remaining: Optional[dict] = None
    features: List[str]


# ─── Admin Schemas ───────────────────────────────────────────────────────────

class AdminLoginRequest(BaseModel):
    username_or_email: str
    password: str


class AdminResetSelfPassword(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6, max_length=128)
    new_email: Optional[EmailStr] = None
    new_name: Optional[str] = None

class AdminUserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    is_admin: Optional[bool] = False
    plan_type: Optional[str] = "free"


class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    is_admin: Optional[bool] = None
    plan_type: Optional[str] = None


class MetricStat(BaseModel):
    total: int = 0
    avg_per_user: float = 0.0
    max_per_user: int = 0
    min_per_user: int = 0


class AdminInsightsResponse(BaseModel):
    total_users: int = 0
    active_plans: dict = {}
    ai_usage: dict = {}
    exports: MetricStat
    custom_templates: MetricStat
    resumes: MetricStat
    branched_resumes: MetricStat

    lifetime_wiser_invocations: int = 0
