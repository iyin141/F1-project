#!/usr/bin/env python
import os
import sys
import django
import pandas as pd

# Add the backend directory to path
sys.path.insert(0, 'c:/Users/iyino/Videos/F1-project/f1-project-backend/backend')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'f1_project.settings')
django.setup()

from api.services.unified_service import SessionManager

# Load session
s = SessionManager.get_session(2026, 2, 'R')

# Get laps for analysis
laps = s.laps.copy()
laps = laps[laps["LapTime"].notna()]

print("Looking for pit stops (rows with PitInTime.notna() AND PitOutTime.notna()):\n")

for driver_code, driver_laps in laps.groupby("Driver"):
    pit_laps_both = driver_laps[(driver_laps["PitInTime"].notna()) & (driver_laps["PitOutTime"].notna())]
    pit_laps_in_only = driver_laps[(driver_laps["PitInTime"].notna()) & (driver_laps["PitOutTime"].isna())]
    
    if len(pit_laps_both) > 0:
        print(f"Driver: {driver_code}")
        print(f"  Pit laps (both times): {len(pit_laps_both)}")
        
        for idx, (_, lap) in enumerate(pit_laps_both.iterrows()):
            lap_num = lap.get("LapNumber")
            pit_in = lap.get("PitInTime")
            pit_out = lap.get("PitOutTime")
            compound = lap.get("Compound")
            
            if pd.notna(pit_in) and pd.notna(pit_out):
                duration = (pit_out - pit_in).total_seconds()
                print(f"    Pit {idx+1}: Lap {lap_num}, In={pit_in}, Out={pit_out}, Duration={duration}s, Compound={compound}")
                
                # Check outlap
                outlap_rows = driver_laps[driver_laps["LapNumber"] == lap_num + 1]
                if len(outlap_rows) > 0:
                    outlap_compound = outlap_rows.iloc[0].get("Compound")
                    print(f"      Outlap compound: {outlap_compound}")
            else:
                print(f"    Pit {idx+1}: Lap {lap_num}, In={pit_in}, Out={pit_out} (INCOMPLETE)")
        print()
    
    if len(pit_laps_in_only) > 0 and len(pit_laps_both) == 0:
        print(f"Driver: {driver_code}")
        print(f"  Pit laps (incomplete - only PitInTime): {len(pit_laps_in_only)}")
        for idx, (_, lap) in enumerate(pit_laps_in_only.head(2).iterrows()):
            lap_num = lap.get("LapNumber")
            pit_in = lap.get("PitInTime")
            pit_out = lap.get("PitOutTime")
            print(f"    Lap {lap_num}: In={pit_in}, Out={pit_out}")
        print()
