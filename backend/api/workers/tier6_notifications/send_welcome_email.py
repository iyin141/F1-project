from celery import shared_task
import logging

from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_welcome_email(self, task_key: str, api_key_id: str, email: str, tier: str):
    logger.info("event=celery_start task=send_welcome_email task_key=%s email=%s tier=%s", task_key, email, tier)
    
    tier_limits = {
        'free': '100 requests/min',
        'standard': '500 requests/min',
        'premium': '2000 requests/min',
        'internal': '10000 requests/min',
    }
    limit = tier_limits.get(tier, 'Unknown')
    
    subject = f"Welcome! Your {tier.title()} API Key is Active"
    message = f"""
Your API key is now active and ready to use!

Tier: {tier.title()}
Rate Limit: {limit}

Get started:
https://docs.f1api.example.com/getting-started

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
    logger.info("event=email_sent task=send_welcome_email email=%s", email)
