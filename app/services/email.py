# services/email.py
# Inspired by thoughts_and_lists Gmail OAuth2 & Zinc Email architecture

import base64
import logging
import os
import pathlib
import datetime
import smtplib
from email.message import EmailMessage

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

# Brand constants
_BRAND = os.getenv("APP_NAME", "Resumo")
_DEV_PREVIEW_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "email_previews"


# ---------------------------------------------------------------------------
# CSS Styling Constants (Unified Zinc / Dark-aware Aesthetic)
# ---------------------------------------------------------------------------
_EMAIL_STYLE = f"""
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#f4f4f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-text-size-adjust:100%}}
  .wrap{{width:100%;background:#f4f4f5;padding:48px 16px}}
  .card{{max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e4e4e7;border-radius:16px;overflow:hidden;box-shadow:0 1px 3px 0 rgba(0,0,0,0.05),0 1px 2px 0 rgba(0,0,0,0.06)}}
  .body{{padding:40px 32px 32px 32px}}
  .subtitle{{font-size:14px;color:#71717a;line-height:1.5;margin-bottom:24px}}
  .otp-wrap{{margin:0 0 24px;text-align:center}}
  .otp-label{{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:#a1a1aa;margin-bottom:8px}}
  .otp-box{{display:inline-block;padding:16px 28px;font-size:32px;font-weight:700;letter-spacing:8px;font-family:SFMono-Regular,Consolas,"Liberation Mono",Menlo,monospace;background:#fafafa;border:1px solid #e4e4e7;border-radius:10px;color:#09090b}}
  .note{{font-size:13px;color:#52525b;line-height:1.5;background:#f4f4f5;border-radius:8px;padding:12px 16px;text-align:center}}
  .divider{{border:none;border-top:1px solid #e4e4e7;margin:28px 0}}
  .footer{{padding:0;text-align:center}}
  .footer p{{font-size:12px;color:#71717a;line-height:1.6}}
  .footer a{{color:#09090b;text-decoration:none;font-weight:600}}
  .badge{{display:inline-block;margin-top:12px;font-size:11px;color:#a1a1aa;letter-spacing:.3px}}

  @media only screen and (max-width:480px){{
    .wrap{{padding:24px 10px}}
    .body{{padding:28px 20px 24px 20px}}
    .otp-box{{font-size:26px;letter-spacing:6px;padding:14px 20px}}
    .header-title{{font-size:18px!important}}
  }}
  @media (prefers-color-scheme:dark){{
    body,.wrap{{background:#09090b!important}}
    .card{{background:#09090b!important;border-color:#27272a!important;box-shadow:none!important}}
    .header-title{{color:#f4f4f5!important}}
    .header-pre{{color:#a1a1aa!important}}
    .subtitle{{color:#a1a1aa!important}}
    .otp-box{{background:#18181b!important;border-color:#27272a!important;color:#f4f4f5!important}}
    .note{{background:#18181b!important;border-color:#27272a!important;color:#a1a1aa!important}}
    .divider{{border-color:#27272a!important}}
    .footer p{{color:#71717a!important}}
    .footer a{{color:#f4f4f5!important}}
    .badge{{color:#71717a!important}}
  }}
"""


def _html_header(icon: str, title: str, subtitle: str = "", category: str = "SECURITY") -> str:
    sub_row = ""
    if subtitle:
        sub_row = f'<p class="subtitle" style="font-size:14px;color:#71717a;line-height:1.5;margin:8px 0 0 0;">{subtitle}</p>'

    return f"""
      <div class="header" style="margin-bottom:24px;text-align:left;">
        <div class="header-pre" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#71717a;margin-bottom:8px;">
          <span class="header-icon" style="margin-right:4px;">{icon}</span>{_BRAND} · {category}
        </div>
        <h1 class="header-title" style="font-size:22px;font-weight:800;color:#09090b;margin:0;line-height:1.25;letter-spacing:-0.5px;">{title}</h1>
        {sub_row}
      </div>"""


def _html_footer(extra_note: str = "") -> str:
    note_html = ""
    if extra_note:
        note_html = f'<p style="font-size:12px;color:#71717a;line-height:1.6;margin-bottom:16px;">{extra_note}</p>'
    return f"""
          <hr class="divider" style="border:none;border-top:1px solid #e4e4e7;margin:28px 0;"/>
          <div class="footer" style="text-align:center;">
            {note_html}
            <div class="badge" style="display:inline-block;margin-top:12px;font-size:11px;color:#a1a1aa;letter-spacing:.3px;">
              {_BRAND} · Precision Career &amp; Resume Intelligence
            </div>
          </div>"""


def generate_email_content(otp_code: str, purpose: OTPPurpose) -> tuple[str, str, str]:
    """Builds subject, plain text, and HTML formatted OTP message."""
    brand = _BRAND
    if purpose == OTPPurpose.LOGIN:
        subject = f"Your {brand} Login Code"
        title = "Login Verification"
        subtitle = "Use the one-time code below to sign in securely."
        icon = "🔐"
        category = "SECURITY"
    elif purpose == OTPPurpose.PASSWORD_RESET:
        subject = f"Reset your {brand} password"
        title = "Password Reset"
        subtitle = "Use the code below to reset your password. It expires in 10 minutes."
        icon = "🔑"
        category = "SECURITY"
    elif purpose == OTPPurpose.PROFILE_PASSWORD_RESET:
        subject = f"Reset your {brand} password"
        title = "Profile Password Reset"
        subtitle = "Use the code below to update your password from inside your profile."
        icon = "🔑"
        category = "SECURITY"
    elif purpose == OTPPurpose.REGISTER:
        subject = f"Verify your {brand} account"
        title = "Verify Your Email Address"
        subtitle = f"Use the verification code below to complete your {brand} registration."
        icon = "✨"
        category = "SECURITY"
    else:
        subject = f"Your {brand} OTP Code"
        title = "Verification Code"
        subtitle = "Use the code below to continue."
        icon = "✅"
        category = "SECURITY"

    header = _html_header(icon, title, subtitle=subtitle, category=category)
    footer = _html_footer(
        f"If you didn't request this, you can safely ignore this email.<br/>"
        f"This is an automated security transmission from {brand}."
    )

    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<meta name="color-scheme" content="light dark"/>
<title>{subject}</title>
<style>
{_EMAIL_STYLE}
</style>
</head>
<body>
<div class="wrap">
  <table width="100%" role="presentation" cellpadding="0" cellspacing="0">
    <tr><td align="center">
      <div class="card">
        <div class="body">
          {header}
          <div class="otp-wrap">
            <div class="otp-label">Your one-time code</div>
            <div class="otp-box">{otp_code}</div>
          </div>
          <div class="note">
            ⏱ This code expires in <strong>10 minutes</strong>.<br/>
            🔒 Never share this code with anyone.
          </div>
          {footer}
        </div>
      </div>
    </td></tr>
  </table>
</div>
</body>
</html>"""

    text_body = f"""{brand} · {title}

{subtitle}

Your one-time code:
>>> {otp_code} <<<

This code expires in 10 minutes. Do not share it with anyone.

— {brand} Security Transmission"""

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
    """Sends email directly via Google Gmail API OAuth2 (as in thoughts_and_lists)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"] or "me"
    msg["To"] = to_email
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
    """Fallback to standard SMTP if Gmail API credentials are not provided."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"] or "noreply@resumo.app"
    msg["To"] = to_email
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    print(f"[SMTP] Connecting to {cfg['smtp_server']}:{cfg['smtp_port']}...", flush=True)

    if cfg["smtp_port"] == 465:
        with smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=15) as server:
            if cfg["sender_email"] and cfg["smtp_password"]:
                server.login(cfg["sender_email"], cfg["smtp_password"])
            server.send_message(msg)
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
            server.send_message(msg)

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
        f" Purpose: {purpose_label}\n"
        f" OTP Code: >>> {otp_code} <<<\n"
        f" Mode: {'DEVELOPMENT' if is_dev else 'PRODUCTION'} | DEV_MAIL: {dev_mail}\n"
        f" Provider: {'Gmail API' if cfg['has_gmail_api'] else 'SMTP' if cfg['has_smtp'] else 'None'}\n"
        f" Expires: 10 minutes\n"
        f"======================================================\n"
    )
    print(console_msg, flush=True)
    logger.info(console_msg)

    subject, text_body, html_body = generate_email_content(otp_code, purpose)

    # 2. In dev mode without DEV_MAIL=True, save preview and skip live dispatch
    if is_dev and not dev_mail:
        filepath = _dev_save_html(subject, to_email, html_body, log_label=f"otp_{purpose_label}")
        skip_msg = (
            f"[DEV] Email NOT dispatched (dev mode). HTML preview saved -> {filepath}\n"
            f"[DEV] To enable sending real emails in dev, set DEV_MAIL=True in your .env"
        )
        print(skip_msg, flush=True)
        logger.info(skip_msg)
        return

    # 3. Live dispatch: prioritize Gmail API (OAuth2) as in thoughts_and_lists
    if cfg["has_gmail_api"]:
        try:
            print(f"[GMAIL API] Dispatching OTP email to {to_email}...", flush=True)
            _send_via_gmail_api(to_email, subject, text_body, html_body, cfg)
            return
        except HttpError as error:
            err_msg = f"[GMAIL API ERROR] Failed to send OTP via Gmail API: {error}"
            print(err_msg, flush=True)
            logger.error(err_msg)
        except Exception as e:
            err_msg = f"[GMAIL API ERROR] Unexpected error: {e}"
            print(err_msg, flush=True)
            logger.error(err_msg, exc_info=True)

    # 4. Fallback to standard SMTP if Gmail API is not configured or failed
    if cfg["has_smtp"]:
        try:
            _send_via_smtp_fallback(to_email, subject, text_body, html_body, cfg)
            return
        except Exception as e:
            err_msg = f"[SMTP ERROR] Failed to send OTP via SMTP: {e}"
            print(err_msg, flush=True)
            logger.error(err_msg, exc_info=True)

    # 5. Neither provider configured
    if not cfg["has_gmail_api"] and not cfg["has_smtp"]:
        warn_msg = (
            f"[MAIL CONFIG WARNING] Neither Gmail API nor SMTP is configured. "
            f"Provide either GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN (recommended, like thoughts_and_lists) "
            f"or SMTP_SERVER / SMTP_PORT / APP_PASSWORD in .env."
        )
        print(warn_msg, flush=True)
        logger.warning(warn_msg)
