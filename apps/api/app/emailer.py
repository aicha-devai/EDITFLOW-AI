import asyncio
import smtplib
from email.message import EmailMessage

from fastapi import HTTPException

from app.config import settings


def _send_sync(recipient: str, subject: str, body: str) -> None:
    if not settings.email_smtp_host or not settings.email_from:
        raise RuntimeError("Email delivery is not configured")
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    if settings.email_use_ssl:
        with smtplib.SMTP_SSL(settings.email_smtp_host, settings.email_smtp_port, timeout=15) as smtp:
            if settings.email_smtp_username:
                smtp.login(settings.email_smtp_username, settings.email_smtp_password or "")
            smtp.send_message(message)
        return
    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port, timeout=15) as smtp:
        smtp.ehlo()
        if settings.email_starttls:
            smtp.starttls()
            smtp.ehlo()
        if settings.email_smtp_username:
            smtp.login(settings.email_smtp_username, settings.email_smtp_password or "")
        smtp.send_message(message)


async def send_email(recipient: str, subject: str, body: str) -> None:
    try:
        await asyncio.to_thread(_send_sync, recipient, subject, body)
    except Exception as exc:
        raise HTTPException(503, "Email delivery is temporarily unavailable") from exc
