from celery import shared_task
import logging

from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, queue="tier6_notifications")
def send_usage_summary_all(self, task_key: str, email: str, summaries: dict):
    logger.info("event=celery_start task=send_usage_summary_all task_key=%s email=%s", task_key, email)
    subject = "Your API Usage Summaries"
    message_lines = []
    for name, text in summaries.items():
        message_lines.append(f"== {name} ==\n{text}\n")
    message = "\n".join(message_lines)
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL or 'noreply@f1api.example.com',
        [email],
        fail_silently=False,
    )
    logger.info("event=email_sent task=send_usage_summary_all email=%s", email)
