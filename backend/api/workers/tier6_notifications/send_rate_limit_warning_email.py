from celery import shared_task
import logging

from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_rate_limit_warning_email(self, task_key: str, api_key_id: str, email: str, usage_percent: int):
    logger.info("event=celery_start task=send_rate_limit_warning_email task_key=%s email=%s usage=%d%%", task_key, email, usage_percent)
    
    subject = f"Rate Limit Warning ({usage_percent}% Used)"
    message = f"""
You're using {usage_percent}% of your rate limit.

If you need more capacity, consider upgrading to a higher tier:
https://dashboard.f1api.example.com/upgrade

Current usage: {usage_percent}%
Reset time: Next hour

Questions? Contact support@f1api.example.com

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
    logger.info("event=email_sent task=send_rate_limit_warning_email email=%s", email)
