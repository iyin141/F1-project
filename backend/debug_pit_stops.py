#!/usr/bin/env python
import os
import django
import pandas as pd

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
django.setup()

from api.services.unified_service import SessionManager, PitStopExtractor

# Load session
s = SessionManager.get_session(2026, 2, 'R')

# Get laps for a driver with pit stops
laps = s.laps.copy()
laps = laps[laps["LapTime"].notna()]

# Look at first driver with pit stops
for driver_code, driver_laps in laps.groupby("Driver"):
    pit_laps = driver_laps[driver_laps["PitInTime"].notna()]
    if len(pit_laps) > 0:
        print(f"\nDriver: {driver_code}")
        print(f"Total laps: {len(driver_laps)}")
        print(f"Pit laps: {len(pit_laps)}")
        
        # Show first pit stop details
        first_pit = pit_laps.iloc[0]
        lap_num = first_pit.get("LapNumber")
        pit_in_time = first_pit.get("PitInTime")
        pit_out_time = first_pit.get("PitOutTime")
        compound = first_pit.get("Compound")
        
        print(f"\nFirst pit stop:")
        print(f"  Lap number: {lap_num}")
        print(f"  PitInTime: {pit_in_time}")
        print(f"  PitOutTime: {pit_out_time}")
        print(f"  Compound: {compound}")
        
        if pd.notna(pit_in_time) and pd.notna(pit_out_time):
            duration = (pit_out_time - pit_in_time).total_seconds()
            print(f"  Duration: {duration}s")
        
        # Check outlap
        outlap_rows = driver_laps[driver_laps["LapNumber"] == lap_num + 1]
        if len(outlap_rows) > 0:
            outlap_compound = outlap_rows.iloc[0].get("Compound")
            print(f"  Outlap compound: {outlap_compound}")
        else:
            print(f"  No outlap found")
        
        # Check position delta
        pre_pit = driver_laps[driver_laps["LapNumber"] == lap_num - 1]
        post_pit = driver_laps[driver_laps["LapNumber"] == lap_num + 2]
        
        if len(pre_pit) > 0:
            print(f"  Pre-pit position: {pre_pit.iloc[0].get('Position')}")
        if len(post_pit) > 0:
            print(f"  Post-pit (lap+2) position: {post_pit.iloc[0].get('Position')}")
        
        # Stop after first driver with pit stops
        break
