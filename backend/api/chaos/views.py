"""Chaos Point endpoints. Auth, permission and throttle classes are the project defaults (REST_FRAMEWORK in settings),
the same as every analysis view; cost uses endpoint_type "chaos" (not in ENDPOINT_COSTS, so cost 1)."""
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from api.queue.manager import TaskManager

from . import cache as C
from . import history as H
from . import service as S
from .serializers import (
    CircuitHistorySerializer,
    CircuitListSerializer,
    CircuitsSummarySerializer,
    DriverProfileSerializer,
    DriversChaosSerializer,
    LapsChaosSerializer,
    ModelPageSerializer,
    ChaosPendingSerializer,
    RaceChaosSerializer,
)
from .tasks import pipeline_task_key, populate_chaos

_MODEL = OpenApiParameter(name="model", location=OpenApiParameter.QUERY, required=False, type=str,
                          description="auto (default: calibrated Kumo if present, else the baseline, and the response says which), kumo_calibrated, kumo (raw), baseline. A named model that has no run for this race gives 404, never a substitute.")
_R400 = OpenApiResponse(description="Invalid parameter")
_R404 = OpenApiResponse(description="No such run, no stored history, or unknown circuit or driver")
_R202 = OpenApiResponse(response=ChaosPendingSerializer, description="Predictions are being built: the pipeline was queued, retry shortly")


def _err(exc, code):
    return Response({"error": str(exc)}, status=code)


def _pending(year, rnd):
    task_key = pipeline_task_key(year, rnd)
    TaskManager.enqueue_if_needed(task_key, populate_chaos, year, rnd)
    return Response({"status": "pending", "task_key": task_key, "detail": "Chaos predictions are being built; retry shortly."}, status=202)


class _RaceView(APIView):
    """Shared flow: validate, pick the run (no silent fallback), pending or 404, then a cached payload."""

    name = ""

    def build(self, request, year, rnd, run, block):
        raise NotImplementedError

    def extra_key(self, request) -> str:
        return ""

    def get(self, request, year, round_number):
        request.endpoint_type = "chaos"
        try:
            S.parse_race(year, round_number)
            choice = S.parse_model(request.query_params.get("model"))
            extra = self.extra_key(request)
        except S.ParamError as exc:
            return _err(exc, 400)
        run, block = S.select_run(year, round_number, choice)
        if run is None:
            if choice != S.AUTO:
                return _err(f"no {choice} run stored for {year} round {round_number}", 404)
            if not S.has_history(year, round_number):
                return _err(f"no stored races before {year} round {round_number}: nothing to predict from", 404)
            return _pending(year, round_number)
        key = f"{self.name}:{year}:{round_number}:{run.id}:{extra}"
        return Response(C.cached(key, C.TTL_PREDICTIONS, lambda: self.build(request, year, round_number, run, block)))


class ChaosRaceAPIView(_RaceView):
    name = "race"

    @extend_schema(
        operation_id="chaos_race_retrieve", summary="Chaos Index and per-target probabilities for a race",
        description="Expected disruptive events (Chaos Index = expected safety-car/VSC/red windows + expected mechanical and incident retirements, from the same run's per-entity probabilities), each target's probability with p10/p90, and the largest differences from the circuit-type average. `model` says which run produced it; the baseline is only served when no calibrated Kumo run exists, and says so. 202 and the pipeline is queued if nothing is stored yet.",
        parameters=[_MODEL], responses={200: RaceChaosSerializer, 202: _R202, 400: _R400, 404: _R404})
    def get(self, request, year, round_number):
        return super().get(request, year, round_number)

    def build(self, request, year, rnd, run, block):
        return S.race_payload(year, rnd, run, block)


class ChaosDriversAPIView(_RaceView):
    name = "drivers"

    @extend_schema(
        operation_id="chaos_race_drivers_retrieve", summary="Per-driver retirement and pit-stop risks for a race",
        description="Per driver: probability, p10 and p90 of a mechanical retirement, an accident/collision retirement, a slow stop and an unlucky stop. Unlucky stop is a tendency with a wide interval, not a skill rating.",
        parameters=[_MODEL], responses={200: DriversChaosSerializer, 202: _R202, 400: _R400, 404: _R404})
    def get(self, request, year, round_number):
        return super().get(request, year, round_number)

    def build(self, request, year, rnd, run, block):
        return S.drivers_payload(year, rnd, run, block)


class ChaosLapsAPIView(_RaceView):
    name = "laps"

    def extra_key(self, request):
        return S.parse_target(request.query_params.get("target"), H.RACE_TARGETS)

    @extend_schema(
        operation_id="chaos_race_laps_retrieve", summary="Lap-window heat strip",
        description="Probability per 5-lap window of each target; `strip` is the chosen target as a flat list for a heat strip.",
        parameters=[_MODEL, OpenApiParameter(name="target", location=OpenApiParameter.QUERY, required=False, type=str, description="sc_vsc_red (default), dnf_mechanical, dnf_incident, slow_stop, unlucky_stop")],
        responses={200: LapsChaosSerializer, 202: _R202, 400: _R400, 404: _R404})
    def get(self, request, year, round_number):
        return super().get(request, year, round_number)

    def build(self, request, year, rnd, run, block):
        return S.laps_payload(year, rnd, run, block, self.extra_key(request))


class ChaosCircuitListAPIView(APIView):

    @extend_schema(
        operation_id="chaos_circuits_list", summary="Known circuits and their slugs",
        description="Every circuit chaos can identify: slug (use it in circuits/<slug>/history/), name, type, the schedule aliases it matches (event location and event name), linked track-map key, and whether a CircuitProfile row is stored yet.",
        responses={200: CircuitListSerializer})
    def get(self, request):
        request.endpoint_type = "chaos"
        return Response(C.cached("circuits", C.TTL_MODEL, S.circuit_list))


class ChaosCircuitsSummaryAPIView(APIView):

    @extend_schema(
        operation_id="chaos_circuits_summary", summary="History rates of every circuit in one response",
        description="For each known circuit: races counted and the share of its stored races with a safety car, VSC, red flag or any neutralisation, plus mean mechanical and incident retirements per race. Replaces one circuits/<slug>/history/ call per circuit. Refreshed when labels are rebuilt.",
        responses={200: CircuitsSummarySerializer})
    def get(self, request):
        request.endpoint_type = "chaos"
        return Response(C.cached("circuits_summary", C.TTL_HISTORY, S.circuits_summary))


class ChaosCircuitHistoryAPIView(APIView):

    @extend_schema(
        operation_id="chaos_circuit_history_retrieve", summary="Neutralisation and retirement history of a circuit",
        description="Circuit traits, per-race safety-car / VSC / red-flag / retirement / pit-stop label counts, and summary rates. `circuit` is the circuit slug (for example monaco).",
        responses={200: CircuitHistorySerializer, 404: _R404})
    def get(self, request, circuit):
        request.endpoint_type = "chaos"
        try:
            return Response(C.cached(f"circuit:{circuit.lower()}", C.TTL_HISTORY, lambda: S.circuit_history(circuit)))
        except S.NotFound as exc:
            return _err(exc, 404)


class ChaosDriverProfileAPIView(APIView):

    @extend_schema(
        operation_id="chaos_driver_profile_retrieve", summary="A driver's retirement and pit-stop tendencies",
        description="Shrunk tendencies with p10/p90, not skill ratings: with few races the interval is wide.",
        responses={200: DriverProfileSerializer, 400: _R400, 404: _R404})
    def get(self, request, code):
        request.endpoint_type = "chaos"
        try:
            c = S.parse_driver(code)
            return Response(C.cached(f"driver:{c}", C.TTL_HISTORY, lambda: S.driver_profile(c)))
        except S.ParamError as exc:
            return _err(exc, 400)
        except S.NotFound as exc:
            return _err(exc, 404)


class ChaosModelAPIView(APIView):

    @extend_schema(
        operation_id="chaos_model_retrieve", summary="Current chaos model runs, backtest metrics and calibration bins",
        description="The latest run of each model (calibrated Kumo, raw Kumo, Beta-Binomial) with its calibration table, and the latest leave-one-season-out backtest: Brier, log-loss, AUC, ECE and the 10-bin reliability table per model and target. Empty lists when nothing has run yet.",
        responses={200: ModelPageSerializer})
    def get(self, request):
        request.endpoint_type = "chaos"
        return Response(C.cached("model", C.TTL_MODEL, S.model_page))
