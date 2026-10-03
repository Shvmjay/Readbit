"""Outbound email. EMAIL_DELIVERY=smtp sends through any SMTP provider; =log writes to the log (development only);
=disabled drops messages. Message bodies are never logged in smtp mode."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("readbit.mail")


class MailError(Exception):
    pass


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if handed to the transport; raises MailError on SMTP failure."""
    s = get_settings()
    if s.email_delivery == "disabled":
        return False
    if s.email_delivery == "log":
        if s.is_production:
            return False
        log.info("email (development log delivery)", extra={"to": to, "subject": subject, "body": body})
        return True
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    context = ssl.create_default_context()
    try:
        if s.smtp_starttls:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds) as smtp:
                smtp.starttls(context=context)
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(
                s.smtp_host, s.smtp_port, timeout=s.smtp_timeout_seconds, context=context
            ) as smtp:
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
                smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("email delivery failed", extra={"error": type(exc).__name__})
        raise MailError("email delivery failed") from exc
    log.info("email sent", extra={"subject": subject})
    return True


RESET_TEMPLATES = {
    "en": (
        "Reset your Readbit password",
        "Someone asked to reset the password for your Readbit account.\n\n"
        "Open this link to choose a new password (valid for {minutes} minutes):\n{url}\n\n"
        "If you didn't ask for this, you can ignore this email — your password won't change.",
    ),
    "hi": (
        "अपना Readbit पासवर्ड रीसेट करें",
        "आपके Readbit खाते का पासवर्ड रीसेट करने का अनुरोध किया गया है।\n\n"
        "नया पासवर्ड चुनने के लिए यह लिंक खोलें ({minutes} मिनट तक मान्य):\n{url}\n\n"
        "यदि आपने यह अनुरोध नहीं किया, तो इस ईमेल को अनदेखा करें — आपका पासवर्ड नहीं बदलेगा।",
    ),
}


def send_password_reset(to: str, url: str, language: str) -> bool:
    subject, body = RESET_TEMPLATES.get(language, RESET_TEMPLATES["en"])
    return send_email(to, subject, body.format(url=url, minutes=get_settings().password_reset_ttl_minutes))
