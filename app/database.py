from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import DATABASE_URL

# Synchronous connection URL: convert async driver prefix if present
sync_db_url = DATABASE_URL
if sync_db_url.startswith("postgresql+asyncpg://"):
    sync_db_url = sync_db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)

# For SQLite, check_same_thread=False allows FastAPI threads to use the connection
engine = create_engine(
    sync_db_url,
    connect_args={"check_same_thread": False} if "sqlite" in sync_db_url else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def run_auto_migrations():
    """
    Ensures existing databases gracefully adapt to schema additions like
    soft-delete columns, admin flags, parent resume lineage, and payment tables.
    """
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        with engine.connect() as conn:
            # Users table additions
            if "users" in existing_tables:
                user_cols = [c["name"] for c in inspector.get_columns("users")]
                if "is_admin" not in user_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0 NOT NULL"))

            # Resumes table additions
            if "resumes" in existing_tables:
                resume_cols = [c["name"] for c in inspector.get_columns("resumes")]
                if "parent_resume_id" not in resume_cols:
                    conn.execute(text("ALTER TABLE resumes ADD COLUMN parent_resume_id INTEGER NULL"))
                if "is_primary" not in resume_cols:
                    conn.execute(text("ALTER TABLE resumes ADD COLUMN is_primary BOOLEAN DEFAULT 0 NOT NULL"))

            # Resume templates additions
            if "resume_templates" in existing_tables:
                tmpl_cols = [c["name"] for c in inspector.get_columns("resume_templates")]
                if "template_key" not in tmpl_cols:
                    conn.execute(text("ALTER TABLE resume_templates ADD COLUMN template_key VARCHAR(100) NULL"))
                if "is_global" not in tmpl_cols:
                    conn.execute(text("ALTER TABLE resume_templates ADD COLUMN is_global BOOLEAN DEFAULT 0 NOT NULL"))
                if "min_plan_tier" not in tmpl_cols:
                    conn.execute(text("ALTER TABLE resume_templates ADD COLUMN min_plan_tier VARCHAR(50) DEFAULT 'free' NOT NULL"))
                if "badge" not in tmpl_cols:
                    conn.execute(text("ALTER TABLE resume_templates ADD COLUMN badge VARCHAR(100) NULL"))
                if "category" not in tmpl_cols:
                    conn.execute(text("ALTER TABLE resume_templates ADD COLUMN category VARCHAR(255) NULL"))
                if "preview_thumbnail" not in tmpl_cols:
                    conn.execute(text("ALTER TABLE resume_templates ADD COLUMN preview_thumbnail VARCHAR(255) NULL"))
                if "display_order" not in tmpl_cols:
                    conn.execute(text("ALTER TABLE resume_templates ADD COLUMN display_order INTEGER DEFAULT 0 NOT NULL"))
                if "is_active" not in tmpl_cols:
                    conn.execute(text("ALTER TABLE resume_templates ADD COLUMN is_active BOOLEAN DEFAULT 1 NOT NULL"))

            # Plan tier configs additions
            if "plan_tier_configs" in existing_tables:
                plan_cols = [c["name"] for c in inspector.get_columns("plan_tier_configs")]
                if "is_archived" not in plan_cols:
                    conn.execute(text("ALTER TABLE plan_tier_configs ADD COLUMN is_archived BOOLEAN DEFAULT 0 NOT NULL"))

            # Feedbacks table auto-creation / column guarantee
            if "feedbacks" not in existing_tables:
                try:
                    from .models import Feedback
                    Feedback.__table__.create(bind=engine, checkfirst=True)
                except Exception as fe:
                    print(f"[AutoMigration] Notice creating feedbacks table: {fe}")

            # Soft deletes
            for table in ["resumes", "resume_templates", "exported_resumes"]:
                if table in existing_tables:
                    col_names = [c["name"] for c in inspector.get_columns(table)]
                    if "is_deleted" not in col_names:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN is_deleted BOOLEAN DEFAULT 0 NOT NULL"))
                    if "deleted_at" not in col_names:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN deleted_at TIMESTAMP NULL"))
            conn.commit()
    except Exception as e:
        print(f"[AutoMigration] Notice: {e}")


def get_db():
    """Dependency that provides a database session to FastAPI route handlers."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
