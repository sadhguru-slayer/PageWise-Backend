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
    is_admin = Column(Boolean, default=False, nullable=False)
    preferences_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    resumes = relationship("Resume", back_populates="owner", cascade="all, delete-orphan")
    exports = relationship("ExportedResume", back_populates="user", cascade="all, delete-orphan")
    templates = relationship("ResumeTemplate", back_populates="owner", cascade="all, delete-orphan")
    ai_logs = relationship("AIUsageLog", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan")
    payment_orders = relationship("PaymentOrder", back_populates="user", cascade="all, delete-orphan")
    feedbacks = relationship("Feedback", back_populates="user", cascade="all, delete-orphan")


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

    # ─── Branching / Cloned Resume Lineage ─────────────────────────────────────
    parent_resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="SET NULL"), nullable=True)

    # ─── Primary / Master Resume Designation ──────────────────────────────────
    is_primary = Column(Boolean, default=False, nullable=False)

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
    """User-saved and system global style templates (fonts, margins, colors, section defaults)."""
    __tablename__ = "resume_templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)
    template_key = Column(String(100), nullable=True, index=True)

    # Style data stored as JSON strings
    settings_json = Column(Text, default="{}")       # page settings (margins, fonts, sizes)
    header_style_json = Column(Text, default="{}")   # header style (alignment, fonts, divider)
    section_defaults_json = Column(Text, default="{}") # section heading defaults

    # Schema-driven section requirements & schema version
    section_schema_json = Column(Text, default="{}")   # configurable section & field requirements
    schema_version = Column(Integer, default=1, nullable=False)

    # Global / System template & Tier restriction fields
    is_global = Column(Boolean, default=False, nullable=False, index=True)
    min_plan_tier = Column(String(50), default="free", nullable=False)  # "free", "day_pass", "pro_monthly"
    badge = Column(String(100), nullable=True)                          # "Free Standard", "Day Pass", "Pro Exclusive"
    category = Column(String(255), nullable=True)                       # "Traditional", "Tech & AI", "Leadership"
    preview_thumbnail = Column(String(255), nullable=True)
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True, nullable=False)

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


# ─── Subscription & Payment Tracking ─────────────────────────────────────────

class PlanType:
    FREE = "free"
    DAY_PASS = "day_pass"
    PRO_MONTHLY = "pro_monthly"
    PILOT = "pilot"


class Subscription(Base):
    """Tracks the active subscription tier and billing cycle for a user."""
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)

    plan_type = Column(String(50), default=PlanType.FREE, nullable=False)  # "free", "day_pass", "pro_monthly"
    status = Column(String(50), default="active", nullable=False)          # "active", "expired", "cancelled"

    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)                          # Null for lifetime free, +24h for Day Pass, +30d for Pro

    # Quota counters for the current active billing cycle / period
    resumes_created_in_period = Column(Integer, default=0)
    exports_used_in_period = Column(Integer, default=0)
    wiser_job_help_used = Column(Integer, default=0)
    wiser_ats_used = Column(Integer, default=0)
    period_reset_at = Column(DateTime, default=datetime.utcnow)

    # Razorpay reference
    razorpay_payment_id = Column(String(100), nullable=True)
    razorpay_order_id = Column(String(100), nullable=True)
    razorpay_subscription_id = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="subscription")


class PaymentOrder(Base):
    """Tracks individual payment attempts and successful orders."""
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    plan_type = Column(String(50), nullable=False)
    amount_inr = Column(Integer, nullable=False)              # Stored in INR (e.g. 49, 199)
    currency = Column(String(10), default="INR", nullable=False)
    status = Column(String(50), default="created", nullable=False)  # "created", "paid", "failed"

    razorpay_order_id = Column(String(100), unique=True, index=True, nullable=True)
    razorpay_payment_id = Column(String(100), index=True, nullable=True)
    razorpay_signature = Column(String(255), nullable=True)

    receipt = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="payment_orders")


class PlanTierConfig(Base):
    """
    Dynamic subscription tier configurations managed by Admin.
    Defines limits, pricing, discounts, and marketing features.
    """
    __tablename__ = "plan_tier_configs"

    id = Column(Integer, primary_key=True, index=True)
    tier_key = Column(String(50), unique=True, index=True, nullable=False)  # "free", "day_pass", "pro_monthly"
    name = Column(String(100), nullable=False)                             # "Pagewise Free", "Wiser Day Pass", "Pagewise Pro"
    tagline = Column(String(255), nullable=True)
    badge = Column(String(100), nullable=True)

    # Pricing in INR
    base_price_inr = Column(Integer, default=0, nullable=False)            # regular price (e.g. 0, 99, 299)
    discount_price_inr = Column(Integer, default=0, nullable=False)        # actual charged price (e.g. 0, 49, 199)
    discount_percent = Column(Integer, default=0)                          # e.g. 50%
    billing_period_text = Column(String(50), default="forever")            # "forever", "one-time purchase (24 hours)", "/ month"
    duration_days = Column(Integer, nullable=True)                         # None (forever), 1 (Day pass), 30 (Pro monthly)

    # Tier Allowance & Quota Limits
    resume_limit = Column(Integer, default=1, nullable=False)
    export_limit = Column(Integer, default=1, nullable=False)
    wiser_ai_limit = Column(Integer, default=1, nullable=False)            # combined
    wiser_job_help_limit = Column(Integer, default=1, nullable=False)
    wiser_ats_limit = Column(Integer, default=1, nullable=False)
    custom_template_limit = Column(Integer, default=1, nullable=False)
    premium_templates_allowed = Column(Integer, default=1, nullable=False) # 1 standard, 3 for Day pass, 999 for Pro

    # Feature checklist (JSON array string)
    features_json = Column(Text, default="[]", nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Feedback(Base):
    """
    In-house user feedback system.
    Scalable across multiple categories: pilot_feedback, bug, feature_request, wiser_ai, general.
    Includes spam resistance metadata, client telemetry, and admin audit status.
    """
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Classification & Content
    category = Column(String(50), default="pilot_feedback", nullable=False, index=True)
    rating = Column(Integer, nullable=True)  # 1 - 5 stars
    title = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    email = Column(String(255), nullable=True)

    # Context / Telemetry JSON (url, user_agent, viewport, resume_id, etc.)
    metadata_json = Column(Text, default="{}", nullable=False)

    # Workflow & Moderation
    status = Column(String(50), default="new", nullable=False, index=True)  # "new", "reviewed", "in_progress", "resolved", "archived"
    admin_notes = Column(Text, nullable=True)

    # Anti-Spam Telemetry
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="feedbacks")


class CustomSectionSchema(Base):
    """
    Admin-defined or system-level custom section schemas.
    Allows administrators to define, validate, and publish custom structured sections
    with raw JSON schemas that are usable by both the builder and the AI parser.
    """
    __tablename__ = "custom_section_schemas"

    id = Column(Integer, primary_key=True, index=True)
    section_key = Column(String(100), unique=True, nullable=False, index=True)  # e.g. "publications", "patents"
    label = Column(String(150), nullable=False)                                # e.g. "Publications & Papers"
    icon = Column(String(50), default="FileText", nullable=False)
    description = Column(String(255), nullable=True)
    is_repeatable = Column(Boolean, default=True, nullable=False)

    # Raw JSON schema of fields: [{ key, label, type, required, placeholder, gridSpan }]
    fields_json = Column(Text, default="[]", nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

