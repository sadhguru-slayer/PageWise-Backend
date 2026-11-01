from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    preferences_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    resumes = relationship("Resume", back_populates="owner", cascade="all, delete-orphan")
    exports = relationship("ExportedResume", back_populates="user", cascade="all, delete-orphan")
    templates = relationship("ResumeTemplate", back_populates="owner", cascade="all, delete-orphan")
    ai_logs = relationship("AIUsageLog", back_populates="user", cascade="all, delete-orphan")


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), default="Untitled Resume", nullable=False)

    # Store JSON strings for header, settings, and sections
    header_json = Column(Text, default="{}")
    settings_json = Column(Text, default="{}")
    sections_json = Column(Text, default="[]")

    # ─── Job Targeting Metadata ───────────────────────────────────────────────
    target_job_title = Column(String(255), nullable=True)
    target_company = Column(String(255), nullable=True)
    target_job_description = Column(Text, nullable=True)
    target_ats_score = Column(Float, nullable=True)
    jd_analysis_json = Column(Text, default="{}")

    # ─── Soft Deletion & Audit ────────────────────────────────────────────────
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    owner = relationship("User", back_populates="resumes")
    exports = relationship("ExportedResume", back_populates="resume", cascade="all, delete-orphan")
    ai_logs = relationship("AIUsageLog", back_populates="resume")


class ResumeTemplate(Base):
    """User-saved style templates (fonts, margins, colors, section defaults)."""
    __tablename__ = "resume_templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)

    # Style data stored as JSON strings
    settings_json = Column(Text, default="{}")       # page settings (margins, fonts, sizes)
    header_style_json = Column(Text, default="{}")   # header style (alignment, fonts, divider)
    section_defaults_json = Column(Text, default="{}") # section heading defaults

    # ─── Soft Deletion & Audit ────────────────────────────────────────────────
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    owner = relationship("User", back_populates="templates")


class ExportedResume(Base):
    __tablename__ = "exported_resumes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)

    resume_name = Column(String(255), nullable=False)
    file_type = Column(String(10), nullable=False)  # "pdf", "png", "html", or legacy "docx"
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, default=0)  # Size in bytes
    target_job_title = Column(String(255), nullable=True)
    target_company = Column(String(255), nullable=True)
    template_name = Column(String(255), nullable=True)

    # ─── Soft Deletion & Audit ────────────────────────────────────────────────
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    deleted_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="exports")
    resume = relationship("Resume", back_populates="exports")


class AIUsageLog(Base):
    """
    Audit log of Wiser AI invocations for quota enforcement,
    usage analytics, and subscription model tiers.
    """
    __tablename__ = "ai_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True, index=True)

    action_type = Column(String(50), nullable=False, index=True)  # "wiser_job_help", "wiser_ats_check", "wiser_pdf_import"
    ai_model = Column(String(100), nullable=True)
    tokens_used = Column(Integer, default=0)
    meta_json = Column(Text, default="{}")

    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    user = relationship("User", back_populates="ai_logs")
    resume = relationship("Resume", back_populates="ai_logs")
