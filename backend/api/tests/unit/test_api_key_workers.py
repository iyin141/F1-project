import uuid

import pytest
from django.core import mail

from api.models.auth import APIKey
from api.workers.tier6_notifications.update_api_key_usage import update_api_key_usage
from api.workers.tier6_notifications.email_helpers import send_plain_api_key_email


@pytest.mark.django_db
def test_update_api_key_usage_increments_request_count():
    ak = APIKey.objects.create(email="worker-test@example.com")
    assert ak.request_count == 0

    # invoke the task synchronously via Celery Task.apply to respect binding
    update_api_key_usage.apply(args=("test_task", str(ak.id), 3))

    ak.refresh_from_db()
    assert ak.request_count == 3


@pytest.mark.django_db
def test_send_plain_api_key_email_body_and_subject():
    ak = APIKey.objects.create(email="mail-test@example.com")

    # Ensure outbox is empty before sending
    mail.outbox.clear()

    send_plain_api_key_email(str(ak.id), ak.email)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.subject == "Your F1 Control Room API Key"
    assert msg.body == f"{ak.key}\n\nF1 Control Room"
