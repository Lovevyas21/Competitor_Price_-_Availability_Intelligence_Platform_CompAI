from __future__ import annotations

import smtplib
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from email.message import EmailMessage

import httpx

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings

log = get_logger(__name__)


class AlertChannel(ABC):
    name: str

    @abstractmethod
    def is_configured(self) -> bool:
        pass

    @abstractmethod
    def send_batch(self, messages: list[str]) -> bool:
        pass


class SlackChannel(AlertChannel):
    name = "slack"

    def __init__(self, webhook_url: str | None, timeout: float = 10.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.webhook_url)

    def send_batch(self, messages: list[str]) -> bool:
        if not self.is_configured():
            return False
        ok = True
        for message in messages:
            try:
                response = httpx.post(
                    self.webhook_url, json={"text": message}, timeout=self.timeout
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                log.error("alert.slack_failed", error=str(exc))
                ok = False
        return ok


def build_digest(messages: list[str], generated_at: datetime | None = None) -> EmailMessage:
    generated_at = generated_at or datetime.now(UTC)
    count = len(messages)
    subject = f"{count} competitor undercut{'s' if count != 1 else ''} - {generated_at:%d %b %Y}"

    lines = [
        f"{count} undercut{'s' if count != 1 else ''} detected on evidence fresh enough to act on.",
        "",
    ]
    lines += [f"{i}. {m}" for i, m in enumerate(messages, 1)]
    lines += [
        "",
        "---",
        "Undercuts on evidence older than 7 days are recorded but not sent.",
        "Full detail: GET /undercuts on the platform API.",
    ]

    message = EmailMessage()
    message["Subject"] = subject
    message.set_content("\n".join(lines))
    return message


class EmailChannel(AlertChannel):
    name = "email"

    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self.host = s.smtp_host
        self.port = s.smtp_port
        self.username = s.smtp_username
        self.password = s.smtp_password
        self.use_tls = s.smtp_use_tls
        self.sender = s.alert_email_from
        self.recipients = [r.strip() for r in (s.alert_email_to or "").split(",") if r.strip()]
        self.timeout = s.smtp_timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.host and self.sender and self.recipients)

    def send_batch(self, messages: list[str]) -> bool:
        if not self.is_configured() or not messages:
            return False

        digest = build_digest(messages)
        digest["From"] = self.sender
        digest["To"] = ", ".join(self.recipients)

        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.send_message(digest)
        except (OSError, smtplib.SMTPException) as exc:
            log.error("alert.email_failed", error=str(exc), host=self.host)
            return False

        log.info("alert.email_sent", recipients=len(self.recipients), alerts=len(messages))
        return True


class SesChannel(AlertChannel):
    name = "ses"

    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self.region = s.ses_region
        self.sender = s.alert_email_from
        self.recipients = [r.strip() for r in (s.alert_email_to or "").split(",") if r.strip()]

    def is_configured(self) -> bool:
        return bool(self.region and self.sender and self.recipients)

    def send_batch(self, messages: list[str]) -> bool:
        if not self.is_configured() or not messages:
            return False

        try:
            import boto3

            digest = build_digest(messages)
            client = boto3.client("ses", region_name=self.region)
            client.send_email(
                Source=self.sender,
                Destination={"ToAddresses": self.recipients},
                Message={
                    "Subject": {"Data": digest["Subject"]},
                    "Body": {"Text": {"Data": digest.get_content()}},
                },
            )
        except Exception as exc:
            log.error("alert.ses_failed", error=str(exc), region=self.region)
            return False

        log.info("alert.ses_sent", recipients=len(self.recipients), alerts=len(messages))
        return True


def configured_channels(settings: Settings | None = None) -> list[AlertChannel]:
    s = settings or get_settings()

    candidates: list[AlertChannel] = [SlackChannel(s.slack_webhook_url)]
    ses = SesChannel(s)
    candidates.append(ses if ses.is_configured() else EmailChannel(s))

    return [c for c in candidates if c.is_configured()]
