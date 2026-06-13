import fastf1
import logging
logging.basicConfig(level=logging.INFO)

fastf1.Cache.enable_cache('backend/f1_cache')

try:
    session = fastf1.get_session(2010, 1, 'R')
    session.load(laps=True, telemetry=False, weather=False, messages=False)
    print("Loaded laps:", len(session.laps))
    if len(session.laps) > 0:
        print(session.laps.head(2))
except Exception as e:
    print("Error:", type(e), e)
