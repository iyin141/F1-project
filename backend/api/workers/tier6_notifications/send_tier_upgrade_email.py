from celery import shared_task
import logging

from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_tier_upgrade_email(self, task_key: str, api_key_id: str, email: str, new_tier: str, old_tier: str):
    logger.info("event=celery_start task=send_tier_upgrade_email task_key=%s email=%s", task_key, email)
    
    tier_limits = {
        'free': '100 requests/min',
        'standard': '500 requests/min',
        'premium': '2000 requests/min',
        'internal': '10000 requests/min',
    }
    new_limit = tier_limits.get(new_tier, 'Unknown')
    
    subject = f"Your API Key Upgraded to {new_tier.title()}"
    message = f"""
Great news! Your API key tier has been upgraded.

Old Tier: {old_tier.title()}
New Tier: {new_tier.title()}
New Rate Limit: {new_limit}

Your changes are effective immediately.

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
    logger.info("event=email_sent task=send_tier_upgrade_email email=%s", email)
