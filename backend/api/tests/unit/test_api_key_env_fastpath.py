from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory
from rest_framework.request import Request

from django.db import connection
from django.test.utils import CaptureQueriesContext

from api.auth import APIKeyAuthentication, is_internal_env_key


class APIKeyEnvFastpathTest(TestCase):
    @override_settings(INTERNAL_API_KEY="11111111-1111-1111-1111-111111111111")
    def test_internal_key_no_db_queries(self):
        key = "11111111-1111-1111-1111-111111111111"
        self.assertTrue(is_internal_env_key(key))

        factory = APIRequestFactory()
        req = factory.get("/api/test", HTTP_X_API_KEY=key)
        drf_req = Request(req)

        auth = APIKeyAuthentication()
        with CaptureQueriesContext(connection) as cq:
            result = auth.authenticate(drf_req)

        # internal env key should avoid DB queries
        self.assertEqual(len(cq.captured_queries), 0)
        self.assertIsNotNone(result)
        user, api_key_obj = result
        # ensure synthetic object indicates internal tier
        self.assertTrue(hasattr(api_key_obj, "tier"))
        self.assertEqual(getattr(api_key_obj, "tier"), "internal")
