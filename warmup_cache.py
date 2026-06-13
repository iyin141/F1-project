import os
import sys
import time
import fastf1
import logging

# Add backend to path so we can use its fastf1 instance/settings if needed
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# Important: do not use the proxy for local warmup
if 'PROXY_HOST' in os.environ:
    del os.environ['PROXY_HOST']
if 'HTTP_PROXY' in os.environ:
    del os.environ['HTTP_PROXY']
if 'HTTPS_PROXY' in os.environ:
    del os.environ['HTTPS_PROXY']

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
fastf1.set_log_level('WARNING')  # Keep it relatively quiet

# Tell FastF1 to use the local f1_cache folder
cache_dir = os.path.join(os.path.dirname(__file__), "backend", "f1_cache")
os.makedirs(cache_dir, exist_ok=True)
fastf1.Cache.enable_cache(cache_dir)
logging.info(f"Warming up cache at: {cache_dir}")

YEARS = range(2010, 2027)  # 2010 till now
SESSIONS_TO_LOAD = ['FP1', 'FP2', 'FP3', 'Q', 'SQ', 'S', 'R']  # All sessions

def get_schedule_with_retry(year):
    while True:
        try:
            return fastf1.get_event_schedule(year)
        except Exception as e:
            if "RateLimitExceeded" in str(type(e)):
                logging.warning(f"Rate limit hit getting schedule for {year}. Sleeping 20 minutes...")
                time.sleep(1200)
            else:
                raise e

def load_session_with_retry(year, round_num, session_type):
    while True:
        try:
            session = fastf1.get_session(year, round_num, session_type)
            
            # Skip if the cache folder for this session already exists and has files
            # The folder format is usually like: f1_cache/2026-03-01_Bahrain_Grand_Prix_Race
            import glob
            cache_pattern = os.path.join(cache_dir, f"{year}-*_{session.event['EventName'].replace(' ', '_')}*_{session.name.replace(' ', '_')}*")
            if glob.glob(cache_pattern):
                logging.info(f"  -> SKIPPED: Already cached on disk")
                return

            session.load(laps=True, telemetry=True, weather=False, messages=False)
            try:
                lap_count = len(session.laps)
                logging.info(f"  -> SUCCESS: Loaded {lap_count} laps")
            except Exception as lap_err:
                if "NotLoaded" in str(type(lap_err)):
                    logging.info(f"  -> SUCCESS: Session loaded (No laps available for {year})")
                else:
                    raise
            return
        except Exception as e:
            if "SessionNotAvailable" in str(type(e)):
                logging.warning(f"  -> Session {session_type} not available for {year} Round {round_num}")
                return
            elif "RateLimitExceeded" in str(type(e)):
                logging.warning(f"  -> Rate limit hit! Sleeping 20 minutes before retrying {session_type}...")
                time.sleep(1200)
                # Loop repeats and tries again
            else:
                logging.error(f"  -> ERROR loading {session_type}: {e}")
                return

for year in YEARS:
    logging.info(f"=== Starting Year {year} ===")
    try:
        schedule = get_schedule_with_retry(year)
        schedule = schedule[schedule['EventFormat'] != 'testing']
        
        for index, event in schedule.iterrows():
            round_num = event['RoundNumber']
            event_name = event['EventName']
            
            import datetime
            # Stop if the event hasn't happened yet (using EventDate)
            event_date = event.get('EventDate')
            if event_date and hasattr(event_date, 'to_pydatetime'):
                if event_date.to_pydatetime() > datetime.datetime.now():
                    logging.info(f"Skipping Round {round_num} ({event_name}) because it hasn't happened yet.")
                    break
            
            # Filter SESSIONS_TO_LOAD based on the year (Sprints started in 2021)
            valid_sessions = [s for s in SESSIONS_TO_LOAD if not (s in ['S', 'SQ'] and year < 2021)]
            
            for session_type in valid_sessions:
                logging.info(f"Loading {year} Round {round_num} ({event_name}) - {session_type}")
                load_session_with_retry(year, round_num, session_type)
                
                # Sleep to strictly pace to ~450 sessions per hour
                time.sleep(8) 
                
    except Exception as e:
        logging.error(f"Failed to load schedule for {year}: {e}")

logging.info("Warming up complete! You can now zip the backend/f1_cache folder and upload it to your server.")
