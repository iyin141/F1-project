from celery import shared_task
import logging

from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_monthly_usage_report(self, task_key: str, api_key_id: str, email: str, requests_count: int, tier: str):
    logger.info("event=celery_start task=send_monthly_usage_report task_key=%s email=%s requests=%d", task_key, email, requests_count)
    
    subject = "Your F1 API Monthly Usage Report"
    message = f"""
Here's your monthly API usage summary:

Tier: {tier.title()}
Requests This Month: {requests_count}
Monthly Reset: 1st of month

View detailed analytics:
https://dashboard.f1api.example.com/analytics

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
    logger.info("event=email_sent task=send_monthly_usage_report email=%s", email)
