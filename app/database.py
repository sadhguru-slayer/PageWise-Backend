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
    soft-delete columns without requiring manual dropping or migration errors.
    """
    try:
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        with engine.connect() as conn:
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
