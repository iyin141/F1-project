"""POST /api/assistant/ask: validate, enqueue a `rag`-queue task, stream its events as Server-Sent Events.

Auth, permission and throttle classes are the project defaults (APIKeyAuthentication, IsAPIKeyAuthenticated,
APIKeyThrottle), the same as every analysis view. The throttle cost comes from `request.endpoint_type`; it is set in
`initial()` BEFORE the throttle runs (views that set it inside get() only affect the response, not the cost).
"""
import re
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


TASK_KEY = re.compile(r"^ask-[0-9a-f]{32}$")


class AskEventsAPIView(APIView):
    """GET /api/assistant/ask/<task_key>/events: replay and follow the events of a question already asked.

    Resume after a dropped connection with the standard `Last-Event-ID` header (or `?from=<seq>`): the stream
    continues after that event id. Events are kept 15 minutes. Same auth and throttle as the other endpoints."""

    @extend_schema(
        operation_id="assistant_ask_events",
        summary="Reconnect to the event stream of a question",
        description="Same event format as POST /api/assistant/ask. 404 when the task key is unknown or its events expired.",
        responses={200: OpenApiResponse(description="text/event-stream"), 404: OpenApiResponse(description="Unknown or expired")},
    )
    def get(self, request, task_key):
        if not TASK_KEY.match(task_key):
            return Response({"error": "invalid task key"}, status=404)
        bus = sse.get_bus()
        if not bus.exists(task_key):
            return Response({"error": "unknown or expired task key"}, status=404)
        try:
            if request.headers.get("Last-Event-ID") is not None:
                start = int(request.headers["Last-Event-ID"]) + 1   # SSE: resume AFTER the last event seen
            else:
                start = int(request.query_params.get("from", 0))
        except ValueError:
            return Response({"error": "Last-Event-ID / from must be an integer"}, status=400)
        start = max(start, 0)
        return sse.sse_response(task_key, bus, start)
