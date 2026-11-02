import os
from dotenv import load_dotenv

# Ensure environment variables are loaded from backend/.env or root .env
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv()

# Application Configuration
SECRET_KEY = os.getenv("SECRET_KEY", "pagewise-jwt-secret-key-change-in-production-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# Database path (SQLite by default, or PostgreSQL when configured)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'resumo.db')}")

# Directory for storing exported files (PDF & DOCX)
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
os.makedirs(EXPORTS_DIR, exist_ok=True)

# Environment and Email flags
ENVIRONMENT = os.getenv("ENVIRONMENT", os.getenv("NODE_ENV", "development")).strip().lower()
DEV_MAIL = os.getenv("DEV_MAIL", "false").strip().lower() in ("true", "1", "t", "yes")

# Email & Gmail OAuth2 API Configuration (aligned with thoughts_and_lists)
SMTP_SERVER = os.getenv("SMTP_SERVER") or os.getenv("SMTP_HOST", "smtp.gmail.com")
try:
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
except ValueError:
    SMTP_PORT = 587
SMTP_USERNAME = os.getenv("EMAIL") or os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("APP_PASSWORD") or os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM") or SMTP_USERNAME or "noreply@resumo.app"

GMAIL_CLIENT_ID = os.getenv("CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("CLIENT_SECRET") or os.getenv("CLIENT_SECRETE") or os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REFRESH_TOKEN = os.getenv("REFRESH_TOKEN") or os.getenv("GMAIL_REFRESH_TOKEN", "")
GMAIL_PROJECT_ID = os.getenv("PROJECT_ID") or os.getenv("GMAIL_PROJECT_ID", "")

# Razorpay Payment Gateway Configuration
# Supports test keys specified in user prompt: RAZORPAY_KEY_TEST & RAZORPAY_SECRETE_TEST
RAZORPAY_KEY_ID = (
    os.getenv("RAZORPAY_KEY_TEST")
    or os.getenv("RAZORPAY_KEY_ID")
    or os.getenv("NEXT_PUBLIC_RAZORPAY_KEY_ID", "")
)
RAZORPAY_KEY_SECRET = (
    os.getenv("RAZORPAY_SECRETE_TEST")
    or os.getenv("RAZORPAY_SECRET_TEST")
    or os.getenv("RAZORPAY_KEY_SECRET")
    or os.getenv("RAZORPAY_SECRET", "")
)

