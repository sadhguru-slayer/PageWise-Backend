from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, EmailStr, Field


# ─── Auth Schemas ────────────────────────────────────────────────────────────

class UserRegister(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── Resume Schemas ──────────────────────────────────────────────────────────

class ResumeBase(BaseModel):
    name: str = "Untitled Resume"
    header_json: Any = {}
    settings_json: Any = {}
    sections_json: Any = []


class ResumeCreate(ResumeBase):
    pass


class ResumeUpdate(ResumeBase):
    pass


class ResumeSummary(BaseModel):
    id: int
    user_id: int
    name: str
    created_at: datetime
    updated_at: datetime
    section_count: Optional[int] = 0

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

    class Config:
        from_attributes = True


# ─── Export Schemas ──────────────────────────────────────────────────────────

class ExportPDFRequest(BaseModel):
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
    created_at: datetime

    class Config:
        from_attributes = True
