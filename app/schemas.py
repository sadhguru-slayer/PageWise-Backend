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


# ─── Usage Stats Schema ───────────────────────────────────────────────────────

class UsageStats(BaseModel):
    resume_count: int = 0
    template_count: int = 0
    jd_analyses_count: int = 0
    export_count: int = 0
    targeted_resume_count: int = 0
