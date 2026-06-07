from rest_framework.response import Response
from rest_framework import serializers as drf_serializers
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema, inline_serializer
import logging
import time
from datetime import datetime

from django.utils import timezone
from django.utils.timezone import make_aware


logger = logging.getLogger(__name__)


def _is_unsupported_session_error(exc: Exception) -> bool:
    return is_data_unavailable_error(exc)


def _build_unified_unavailable_response(year, round_number, session_name, unavailable_type, detail_message, driver=None, limit=None):
    return {
        "meta": {
            "year": int(year),
            "round": int(round_number),
            "session": str(session_name).upper(),
            "row_count": 0,
            "extracted_at": datetime.now().isoformat(),
            "limit_max": 2000,
            "can_proceed": False,
            "available_data": [],
            "unavailable_data": [str(unavailable_type)],
            "message": detail_message,
            "warnings": [detail_message],
        },
        "filters_applied": {
            "driver": str(driver).upper() if driver else None,
            "limit": limit,
        },
        "data": [],
    }


def _build_checklist(can_proceed=True, available_data=None, unavailable_data=None, message=None, warnings=None):
    available_data = available_data or []
    unavailable_data = unavailable_data or []
    if warnings is None:
        warnings = [] if can_proceed else ([message] if message else [])
    return {
        "can_proceed": bool(can_proceed),
        "available_data": list(available_data),
        "unavailable_data": list(unavailable_data),
        "message": message,
        "warnings": list(warnings),
    }


def _ensure_payload_meta_checklist(payload, available_defaults=None, unavailable_defaults=None):
    available_defaults = available_defaults or []
    unavailable_defaults = unavailable_defaults or []
    if not isinstance(payload, dict):
        return payload

    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return payload

    if "can_proceed" in meta and "available_data" in meta and "unavailable_data" in meta:
        return payload

    row_count = meta.get("row_count", 0)
    can_proceed = bool(row_count) and not bool(unavailable_defaults)
    message = meta.get("message")
    if not can_proceed and not message:
        if unavailable_defaults:
            message = f"Session loaded, but required data is unavailable. Missing: {', '.join(unavailable_defaults)}."
        else:
            message = "No data available for the requested dataset."
    meta.update(
        _build_checklist(
            can_proceed=can_proceed,
            available_data=available_defaults if can_proceed else [],
            unavailable_data=[] if can_proceed else (unavailable_defaults or available_defaults),
            message=None if can_proceed else message,
            warnings=[] if can_proceed else ([message] if message else []),
        )
    )
    return payload


def _error_payload(domain, message, code):
    return {
        "error": f"{domain} error: {message}",
        "error_code": code,
    }


