import os
import logging
import smtplib
import pathlib
import datetime
from email.message import EmailMessage
from app.services.otp import OTPPurpose

logger = logging.getLogger(__name__)

# SMTP configuration from environment
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "security@pagewise.studio"))

_BRAND = "PageWise Studio"
_BRAND_COLOR = "#f59e0b"  # Amber 500
_PREVIEW_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "email_previews"


def _build_otp_email_html(otp_code: str, purpose: OTPPurpose) -> tuple[str, str, str]:
    if purpose == OTPPurpose.REGISTER:
        title = "Verify Your Email Address"
        subtitle = "Use the verification code below to complete your PageWise Studio registration and activate your account."
    elif purpose == OTPPurpose.LOGIN:
        title = "Your One-Time Login Code"
        subtitle = "Use the code below to log in to your PageWise Studio workspace. No password required."
    elif purpose == OTPPurpose.PROFILE_PASSWORD_RESET:
        title = "Profile Password Reset Verification"
        subtitle = "A request was made to update your studio password from inside your profile."
    else:
        title = "Password Reset Request"
        subtitle = "We received a request to reset your PageWise Studio account password."

    subject = f"[{_BRAND}] {title} — {otp_code}"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{subject}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #090B10; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #F1F3F9; }}
    .wrap {{ width: 100%; padding: 48px 16px; background: #090B10; }}
    .card {{ max-width: 480px; margin: 0 auto; background: #111420; border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; overflow: hidden; box-shadow: 0 10px 40px rgba(0,0,0,0.4); }}
    .header {{ padding: 32px 32px 24px; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.06); }}
    .logo-badge {{ display: inline-flex; align-items: center; justify-content: center; width: 44px; height: 44px; border-radius: 12px; background: linear-gradient(135deg, #d97706, #b45309); color: #fff; font-size: 16px; font-weight: 800; font-family: monospace; margin-bottom: 12px; }}
    .header h1 {{ font-size: 20px; font-weight: 700; color: #ffffff; letter-spacing: -0.3px; }}
    .body {{ padding: 32px; text-align: center; }}
    .desc {{ font-size: 13px; color: #94a3b8; line-height: 1.6; margin-bottom: 24px; }}
    .otp-box {{ display: inline-block; padding: 16px 28px; background: rgba(0,0,0,0.5); border: 1px solid rgba(245,158,11,0.3); border-radius: 12px; font-family: 'SFMono-Regular', Consolas, Monaco, monospace; font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #f59e0b; margin-bottom: 24px; text-shadow: 0 0 15px rgba(245,158,11,0.25); }}
    .warning {{ font-size: 12px; color: #64748b; line-height: 1.5; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 12px 16px; margin-bottom: 24px; text-align: left; }}
    .footer {{ padding: 20px 32px; background: #0c0e17; border-top: 1px solid rgba(255,255,255,0.06); text-align: center; font-size: 11px; color: #64748b; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <div class="header">
        <div class="logo-badge">PW</div>
        <h1>{title}</h1>
      </div>
      <div class="body">
        <p class="desc">{subtitle}</p>
        <div>
          <div class="otp-box">{otp_code}</div>
        </div>
        <div class="warning">
          &#9201; <strong>Code expires in 10 minutes.</strong><br/>
          &#128274; If you did not initiate this request, please disregard this email.
        </div>
      </div>
      <div class="footer">
        PageWise Studio &bull; Precision ATS Intelligence<br/>
        This is an automated security transmission.
      </div>
    </div>
  </div>
</body>
</html>"""

    plain_text = f"""{_BRAND} · {title}

{subtitle}

Your 6-digit verification code:
>>> {otp_code} <<<

This code will expire in 10 minutes.
If you did not request this code, no action is needed."""

    return subject, plain_text, html_content


def _save_dev_preview(to_email: str, subject: str, html_content: str):
    try:
        _PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = _PREVIEW_DIR / f"{ts}_{to_email.replace('@', '_at_')}.html"
        filepath.write_text(html_content, encoding="utf-8")
        logger.info(f"[DEV] Saved email preview: {filepath}")
    except Exception as e:
        logger.warning(f"Could not save preview file: {e}")


def send_otp_email(to_email: str, otp_code: str, purpose: OTPPurpose):
    """Sends OTP email via SMTP if configured, or logs to console and dev preview."""
    subject, plain_text, html_content = _build_otp_email_html(otp_code, purpose)

    # Always log clearly in console for easy development & debugging
    logger.info(
        f"\n======================================================\n"
        f" [OTP EMAIL DISPATCH]\n"
        f" To: {to_email}\n"
        f" Brand: {_BRAND}\n"
        f" Purpose: {purpose.value}\n"
        f" Code: >>> {otp_code} <<<\n"
        f" Expires: 10 minutes\n"
        f"======================================================"
    )

    # Save preview file in development
    _save_dev_preview(to_email, subject, html_content)

    # Send via SMTP if configured
    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = SMTP_FROM
            msg["To"] = to_email
            msg.set_content(plain_text)
            msg.add_alternative(html_content, subtype="html")

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)

            logger.info(f"Successfully sent OTP email via SMTP to {to_email}")
        except Exception as e:
            logger.error(f"Failed to dispatch email via SMTP: {e}")
