from celery import shared_task
import logging

from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_key_revocation_email(self, task_key: str, api_key_id: str, email: str):
    logger.info("event=celery_start task=send_key_revocation_email task_key=%s email=%s", task_key, email)
    
    subject = "API Key Revoked"
    message = f"""
Your API key has been revoked and is no longer active.

If this was unexpected or you'd like to re-activate, please contact:
support@f1api.example.com

Best regards,
F1 API Team
"""
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL or 'noreply@f1api.example.com',
        [email],
        fail_silently=False,
    )
    logger.info("event=email_sent task=send_key_revocation_email email=%s", email)
