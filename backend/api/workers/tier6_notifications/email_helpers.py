from __future__ import annotations

"""Tier-local implementation of `send_plain_api_key_email`.

Copied from the shared helpers and localised to tier6 so the
original module can be removed without breaking imports.
"""

from django.core.mail import send_mail
from django.conf import settings

from api.models.auth import APIKey


def send_plain_api_key_email(api_key_id: str, email: str) -> None:
    """Send a minimal plain-text email for an API key.

    Per project policy, the message body must contain only the API key
    value followed by the signature 'F1 Control Room' on a new line.
    """
    ak = APIKey.objects.filter(id=api_key_id).first()
    ak_key = str(ak.key) if ak and getattr(ak, "key", None) else api_key_id

    subject = "Your F1 Control Room API Key"
    message = f"{ak_key}\n\nF1 Control Room"

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL or "onboarding@resend.dev",
        [email],
        fail_silently=False,
    )


__all__ = ["send_plain_api_key_email"]
