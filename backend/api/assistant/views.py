"""POST /api/assistant/ask: validate, enqueue a `rag`-queue task, stream its events as Server-Sent Events.

Auth, permission and throttle classes are the project defaults (APIKeyAuthentication, IsAPIKeyAuthenticated,
APIKeyThrottle), the same as every analysis view. The throttle cost comes from `request.endpoint_type`; it is set in
`initial()` BEFORE the throttle runs (views that set it inside get() only affect the response, not the cost).
"""
import uuid

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from . import sse
from .tasks import ask_question


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(min_length=3, max_length=1000, trim_whitespace=True)
    year = serializers.IntegerField(min_value=2018, max_value=2030, required=False)
    round = serializers.IntegerField(min_value=1, max_value=30, required=False)

    def validate(self, attrs):
        if "round" in attrs and "year" not in attrs:
            raise serializers.ValidationError({"round": "round needs year"})
        return attrs


class AskAPIView(APIView):
    def initial(self, request, *args, **kwargs):
        request.endpoint_type = "assistant_ask"  # before the throttle: an assistant call costs more
        super().initial(request, *args, **kwargs)

    @extend_schema(
        operation_id="assistant_ask",
        summary="Ask the stewards and rules assistant",
        description=(
            "Answers from FIA regulations, stewards' decisions and our race data only, with citations (document, page, "
            "article, FIA source URL, a quote of at most 300 characters). The answer is produced on the `rag` worker and "
            "streamed as Server-Sent Events: `status` (phase: queued, solving, searching, composing), `token` (text), "
            "`citations`, then `done` (or `error`). With no evidence the answer is \"Evidence not found.\""
        ),
        request=AskSerializer,
        responses={200: OpenApiResponse(description="text/event-stream"), 400: OpenApiResponse(description="Invalid body")},
    )
    def post(self, request):
        ser = AskSerializer(data=request.data)
        if not ser.is_valid():
            return Response({"error": ser.errors}, status=400)
        d = ser.validated_data
        task_key = f"ask-{uuid.uuid4().hex}"
        bus = sse.get_bus()
        bus.publish(task_key, {"type": "status", "phase": "queued", "message": "Queued", "task_key": task_key})
        ask_question.delay(task_key, d["question"], d.get("year"), d.get("round"))
        return sse.sse_response(task_key, bus)
