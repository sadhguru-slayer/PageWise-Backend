# services/email.py
# Inspired by thoughts_and_lists Gmail OAuth2 & Zinc Email architecture

import base64
import logging
import os
import pathlib
import datetime
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.discovery_cache.base import Cache
from googleapiclient.errors import HttpError

from app.services.otp import OTPPurpose

logger = logging.getLogger(__name__)

# Ensure environment variables are loaded
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT_DIR = os.path.dirname(BASE_DIR)
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"))
load_dotenv()


# Suppress noisy file_cache warning and avoid remote discovery fetch on every send
class _MemoryCache(Cache):
    _data: dict = {}

    def get(self, url):
        return self._data.get(url)

    def set(self, url, content):
        self._data[url] = content


# Module-level singleton so the Gmail service is built once and reused
_gmail_service = None

# Brand and sender constants
_BRAND = os.getenv("APP_NAME", "PageWise")
_SENDER_NAME = os.getenv("EMAIL_FROM_NAME") or os.getenv("APP_NAME") or "PageWise"
_DEV_PREVIEW_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "email_previews"


# ---------------------------------------------------------------------------
# CSS Styling Constants (Clean, Deliverability-Optimized Aesthetic)
# ---------------------------------------------------------------------------
_EMAIL_STYLE = """
  body { background-color: #f4f4f5; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 0; -webkit-text-size-adjust: 100%; }
  .email-wrapper { width: 100%; background-color: #f4f4f5; padding: 40px 16px; }
  .email-card { max-width: 500px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e4e4e7; border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05); }
  .email-body { padding: 36px 32px 28px 32px; }
  .brand-header { font-size: 14px; font-weight: 700; color: #d97706; letter-spacing: 0.5px; text-transform: uppercase; margin-bottom: 12px; }
  .email-title { font-size: 20px; font-weight: 700; color: #09090b; margin: 0 0 8px 0; line-height: 1.3; }
  .email-subtitle { font-size: 14px; color: #52525b; line-height: 1.5; margin: 0 0 24px 0; }
  .otp-container { text-align: center; margin: 24px 0; }
  .otp-box { display: inline-block; padding: 14px 28px; font-size: 32px; font-weight: 700; letter-spacing: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; background-color: #fafafa; border: 1px solid #e4e4e7; border-radius: 8px; color: #09090b; }
  .email-note { font-size: 13px; color: #52525b; line-height: 1.5; background-color: #f4f4f5; border-radius: 8px; padding: 12px 16px; text-align: center; margin-bottom: 24px; }
  .email-divider { border: none; border-top: 1px solid #e4e4e7; margin: 24px 0 20px 0; }
  .email-footer { text-align: center; font-size: 12px; color: #71717a; line-height: 1.6; }
"""


def generate_email_content(otp_code: str, purpose: OTPPurpose) -> tuple[str, str, str]:
    """Builds subject, plain text, and HTML formatted OTP message with anti-spam deliverability standards."""
    brand = _BRAND
    if purpose == OTPPurpose.LOGIN:
        subject = f"{otp_code} is your {brand} sign-in code"
        title = "Sign in to your account"
        subtitle = "Please enter the one-time verification code below to complete your sign in."
    elif purpose in (OTPPurpose.PASSWORD_RESET, OTPPurpose.PROFILE_PASSWORD_RESET):
        subject = f"{otp_code} is your {brand} password reset code"
        title = "Reset your password"
        subtitle = "Please enter the one-time verification code below to reset your password."
    elif purpose == OTPPurpose.REGISTER:
        subject = f"{otp_code} is your {brand} verification code"
        title = "Verify your email address"
        subtitle = f"Please enter the verification code below to complete your {brand} account setup."
    else:
        subject = f"{otp_code} is your {brand} verification code"
        title = "Verification Code"
        subtitle = "Please enter the verification code below to continue."

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{subject}</title>
<style>
{_EMAIL_STYLE}
</style>
</head>
<body style="background-color: #f4f4f5; margin: 0; padding: 0;">
<!-- Hidden snippet for inbox preview -->
<div style="display: none; max-height: 0px; overflow: hidden; font-size: 1px; line-height: 1px; color: #f4f4f5; opacity: 0;">
  Your {brand} verification code is {otp_code}. Valid for 10 minutes.
</div>
<div class="email-wrapper" style="width: 100%; background-color: #f4f4f5; padding: 40px 16px; box-sizing: border-box;">
  <table width="100%" role="presentation" cellpadding="0" cellspacing="0" border="0">
    <tr>
      <td align="center">
        <div class="email-card" style="max-width: 500px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e4e4e7; border-radius: 12px; overflow: hidden;">
          <div class="email-body" style="padding: 36px 32px 28px 32px; text-align: left;">
            <div class="brand-header" style="font-size: 14px; font-weight: 700; color: #d97706; letter-spacing: 0.5px; text-transform: uppercase; margin-bottom: 12px;">
              {brand}
            </div>
            <h1 class="email-title" style="font-size: 20px; font-weight: 700; color: #09090b; margin: 0 0 8px 0; line-height: 1.3;">
              {title}
            </h1>
            <p class="email-subtitle" style="font-size: 14px; color: #52525b; line-height: 1.5; margin: 0 0 24px 0;">
              {subtitle}
            </p>
            <div class="otp-container" style="text-align: center; margin: 24px 0;">
              <div class="otp-box" style="display: inline-block; padding: 14px 28px; font-size: 32px; font-weight: 700; letter-spacing: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; background-color: #fafafa; border: 1px solid #e4e4e7; border-radius: 8px; color: #09090b;">
                {otp_code}
              </div>
            </div>
            <div class="email-note" style="font-size: 13px; color: #52525b; line-height: 1.5; background-color: #f4f4f5; border-radius: 8px; padding: 12px 16px; text-align: center; margin-bottom: 24px;">
              This code will expire in <strong>10 minutes</strong>.<br/>
              For your security, please do not share this code with anyone.
            </div>
            <hr class="email-divider" style="border: none; border-top: 1px solid #e4e4e7; margin: 24px 0 20px 0;" />
            <div class="email-footer" style="text-align: center; font-size: 12px; color: #71717a; line-height: 1.6;">
              <p style="margin: 0 0 8px 0;">
                You received this email because a verification request was made for your {brand} account. If you did not make this request, you can safely ignore this email.
              </p>
              <p style="margin: 0; color: #a1a1aa; font-size: 11px;">
                &copy; 2026 {brand}. All rights reserved.
              </p>
            </div>
          </div>
        </div>
      </td>
    </tr>
  </table>
</div>
</body>
</html>"""

    text_body = f"""Hello,

Your {brand} verification code is: {otp_code}

Please enter this code to complete your verification. This code is valid for 10 minutes.

For your security, do not share this code with anyone. If you didn't request this verification code, no further action is required and you can safely ignore this email.

Best regards,
The {brand} Team
https://pagewise.space
"""

    return subject, text_body, html_body


# ---------------------------------------------------------------------------
# Dynamic Config & Gmail API Helpers
# ---------------------------------------------------------------------------

def _get_mail_config():
    """Reads current Gmail and SMTP environment variables dynamically."""
    gmail_client_id = os.getenv("CLIENT_ID") or os.getenv("GMAIL_CLIENT_ID", "")
    gmail_client_secret = os.getenv("CLIENT_SECRET") or os.getenv("CLIENT_SECRETE") or os.getenv("GMAIL_CLIENT_SECRET", "")
    gmail_refresh_token = os.getenv("REFRESH_TOKEN") or os.getenv("GMAIL_REFRESH_TOKEN", "")

    sender_email = (
        os.getenv("EMAIL")
        or os.getenv("SMTP_USERNAME")
        or os.getenv("SMTP_FROM")
        or os.getenv("SMTP_USER", "")
    )

    smtp_server = os.getenv("SMTP_SERVER") or os.getenv("SMTP_HOST", "smtp.gmail.com")
    port_str = os.getenv("SMTP_PORT", "587")
    try:
        smtp_port = int(port_str)
    except ValueError:
        smtp_port = 587
    smtp_password = os.getenv("APP_PASSWORD") or os.getenv("SMTP_PASSWORD", "")

    env = os.getenv("ENVIRONMENT", os.getenv("NODE_ENV", "development")).strip().lower()
    is_dev = env in ("development", "dev", "local", "test")

    raw_dev_mail = os.getenv("DEV_MAIL", "false").strip().lower()
    dev_mail = raw_dev_mail in ("true", "1", "t", "yes")

    has_gmail_api = bool(gmail_client_id and gmail_client_secret and gmail_refresh_token)
    has_smtp = bool(smtp_server and (smtp_password or sender_email))

    return {
        "gmail_client_id": gmail_client_id,
        "gmail_client_secret": gmail_client_secret,
        "gmail_refresh_token": gmail_refresh_token,
        "sender_email": sender_email,
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "smtp_password": smtp_password,
        "is_dev": is_dev,
        "dev_mail": dev_mail,
        "raw_dev_mail": raw_dev_mail,
        "has_gmail_api": has_gmail_api,
        "has_smtp": has_smtp,
    }


def _get_gmail_service():
    """Initializes or returns cached Google OAuth2 Gmail API client."""
    global _gmail_service
    if _gmail_service is not None:
        return _gmail_service

    cfg = _get_mail_config()
    creds = Credentials(
        token=None,
        refresh_token=cfg["gmail_refresh_token"],
        client_id=cfg["gmail_client_id"],
        client_secret=cfg["gmail_client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
    )
    _gmail_service = build("gmail", "v1", credentials=creds, cache=_MemoryCache())
    logger.info("Gmail API service initialized and cached successfully.")
    return _gmail_service


def _dev_save_html(subject: str, to_email: str, html_body: str, log_label: str) -> str:
    """Writes email HTML to disk for offline preview in development."""
    _DEV_PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_label = log_label.lower().replace(" ", "_")
    filename = f"{ts}_{safe_label}_{to_email.replace('@', '_at_')}.html"
    filepath = _DEV_PREVIEW_DIR / filename
    filepath.write_text(html_body, encoding="utf-8")
    return str(filepath)


def _send_via_gmail_api(to_email: str, subject: str, text_body: str, html_body: str, cfg: dict):
    """Sends email directly via Google Gmail API OAuth2 (with proper display name and RFC headers)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    sender_addr = cfg["sender_email"] or "pagewises@gmail.com"
    msg["From"] = formataddr((_SENDER_NAME, sender_addr))
    msg["Reply-To"] = sender_addr
    msg["To"] = to_email
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    service = _get_gmail_service()
    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(userId="me", body={"raw": encoded}).execute()
    msg_id = result.get("id")
    success_msg = f"[GMAIL API SUCCESS] OTP Email SENT to {to_email} | Message ID: {msg_id}"
    print(success_msg, flush=True)
    logger.info(success_msg)


def _send_via_smtp_fallback(to_email: str, subject: str, text_body: str, html_body: str, cfg: dict):
    """Fallback to standard SMTP with proper display name and anti-spam RFC headers."""
    msg = EmailMessage()
    msg["Subject"] = subject
    sender_addr = cfg["sender_email"] or "pagewises@gmail.com"
    msg["From"] = formataddr((_SENDER_NAME, sender_addr))
    msg["Reply-To"] = sender_addr
    msg["To"] = to_email
    msg["Auto-Submitted"] = "auto-generated"
    msg["X-Auto-Response-Suppress"] = "All"
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    print(f"[SMTP] Connecting to {cfg['smtp_server']}:{cfg['smtp_port']}...", flush=True)

    if cfg["smtp_port"] == 465:
        with smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=15) as server:
            if cfg["sender_email"] and cfg["smtp_password"]:
                server.login(cfg["sender_email"], cfg["smtp_password"])
            server.send_message(msg, from_addr=cfg["sender_email"], to_addrs=[to_email])
    else:
        with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"], timeout=15) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except Exception as tls_err:
                logger.debug(f"STARTTLS skipped/failed: {tls_err}")
            if cfg["sender_email"] and cfg["smtp_password"]:
                server.login(cfg["sender_email"], cfg["smtp_password"])
            server.send_message(msg, from_addr=cfg["sender_email"], to_addrs=[to_email])

    success_msg = f"[SMTP SUCCESS] Successfully sent OTP email to {to_email} via SMTP ({cfg['smtp_server']}:{cfg['smtp_port']})"
    print(success_msg, flush=True)
    logger.info(success_msg)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_otp_email(to_email: str, otp_code: str, purpose: OTPPurpose):
    """
    Sends OTP email to the user.
    - Inspired by thoughts_and_lists: uses Gmail API OAuth2 (with GMAIL_CLIENT_ID,
      GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN, EMAIL) or SMTP fallback.
    - In dev mode: sends live email if DEV_MAIL=True is set; otherwise writes
      HTML preview to email_previews/ and logs OTP to terminal.
    - In production: sends live email.
    """
    cfg = _get_mail_config()
    is_dev = cfg["is_dev"]
    dev_mail = cfg["dev_mail"]

    purpose_label = purpose.value if hasattr(purpose, "value") else str(purpose)

    # 1. Log clearly in console so development is never blocked
    console_msg = (
        f"\n======================================================\n"
        f" [OTP DISPATCH]\n"
        f" To: {to_email}\n"
        f" Brand: {_BRAND}\n"
        f" From: {_SENDER_NAME} <{cfg['sender_email']}>\n"
        f" Purpose: {purpose_label}\n"
        f" OTP Code: {otp_code}\n"
        f" Mode: {'DEVELOPMENT' if is_dev else 'PRODUCTION'} | DEV_MAIL: {dev_mail}\n"
        f" Provider: {'Gmail API' if cfg['has_gmail_api'] else 'SMTP' if cfg['has_smtp'] else 'None'}\n"
        f" Expires: 10 minutes\n"
        f"======================================================\n"
    )
    print(console_msg, flush=True)

    subject, text_body, html_body = generate_email_content(otp_code, purpose)

    # 2. In local dev mode without live dispatch, save preview
    if is_dev and not dev_mail:
        saved_path = _dev_save_html(subject, to_email, html_body, purpose_label)
        skip_msg = (
            f"[EMAIL DEV MODE] Live dispatch suppressed (DEV_MAIL={dev_mail}). "
            f"Preview written to: {saved_path}"
        )
        print(skip_msg, flush=True)
        logger.info(skip_msg)
        return

    # 3. Live dispatch: try Gmail API first, then fallback to SMTP
    if cfg["has_gmail_api"]:
        try:
            _send_via_gmail_api(to_email, subject, text_body, html_body, cfg)
            return
        except Exception as e:
            err_msg = f"[GMAIL API ERROR] Failed to send via Gmail API: {e}. Falling back to SMTP..."
            print(err_msg, flush=True)
            logger.warning(err_msg)

    if cfg["has_smtp"]:
        try:
            _send_via_smtp_fallback(to_email, subject, text_body, html_body, cfg)
            return
        except Exception as e:
            err_msg = f"[SMTP ERROR] Failed to send via SMTP fallback: {e}"
            print(err_msg, flush=True)
            logger.error(err_msg)
            raise e

    warn_msg = (
        "[EMAIL CONFIG WARNING] No valid email transport configured "
        "(neither Gmail API nor SMTP available). Email was not dispatched."
    )
    print(warn_msg, flush=True)
    logger.warning(warn_msg)
