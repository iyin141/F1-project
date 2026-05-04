#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
django.setup()

from api.services.unified_service import SessionManager, PitStopExtractor
from api.serializers import PitStopResponseSerializer

# Load session
s = SessionManager.get_session(2026, 2, 'R')

# Extract pit stops
data = PitStopExtractor(s, 2026, 2, 'R').extract()

# Validate serializer
try:
    serialized = PitStopResponseSerializer(data).data
    print("pit_stop_serializer_ok")
except Exception as e:
    print(f"serializer_error: {e}")

# Show sample pit stop rows
if data.get('data'):
    print(f"pit_rows: {len(data['data'])}")
    for i, row in enumerate(data['data'][:3]):
        print(f"pit_{i}: stop_duration={row.get('stop_duration_seconds')}, compound_out={row.get('compound_out')}, time_gain_loss={row.get('time_gain_loss_seconds')}")
else:
    print("no_pit_rows")
