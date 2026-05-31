from celery import shared_task
import logging

from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_usage_summary(self, task_key: str, api_key_id: str, email: str, summary_text: str):
    logger.info("event=celery_start task=send_usage_summary task_key=%s email=%s", task_key, email)
    subject = "Your API Usage Summary"
    message = summary_text
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL or 'noreply@f1api.example.com',
        [email],
        fail_silently=False,
    )
    logger.info("event=email_sent task=send_usage_summary email=%s", email)
