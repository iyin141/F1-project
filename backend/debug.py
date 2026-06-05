#!/usr/bin/env python
"""
Diagnostic script to check available sessions for a given year/round.
Helps identify the correct session identifiers FastF1 expects.
"""

import fastf1
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_sessions_available(year, round_number):
    """Check what sessions FastF1 knows about for this round."""
    
    print(f"\n{'='*60}")
    print(f"Checking sessions for {year} Round {round_number}")
    print(f"{'='*60}\n")
    
    try:
        # Load the event to see what sessions exist
        event = fastf1.get_event(year, round_number)
        
        print(f"Event name: {event['EventName']}")
        print(f"Event format: {event.get('EventFormat', 'Unknown')}")
        print(f"\nAvailable sessions in FastF1 data:")
        
        # Try to load each possible session type
        session_types = ['FP1', 'FP2', 'FP3', 'Q', 'R', 'S', 'SQ', 'SS', 'SprintShootout', 'Sprint Shootout']
        
        found_sessions = []
        
        for session_type in session_types:
            try:
                print(f"\nTrying session type: '{session_type}'...", end=" ")
                session = fastf1.get_session(year, round_number, session_type)
                
                # Check if session has data
                has_results = hasattr(session, 'results') and session.results is not None and not session.results.empty
                has_laps = hasattr(session, 'laps') and session.laps is not None and not session.laps.empty
                
                status = "✅ FOUND"
                if has_results:
                    status += f" (results: {len(session.results)} rows)"
                if has_laps:
                    status += f" (laps: {len(session.laps)} rows)"
                
                print(status)
                found_sessions.append({
                    'identifier': session_type,
                    'name': session.name if hasattr(session, 'name') else 'Unknown',
                    'has_results': has_results,
                    'has_laps': has_laps,
                })
                
            except ValueError as e:
                print(f"❌ NOT FOUND ({str(e)[:50]}...)")
            except Exception as e:
                print(f"❌ ERROR: {str(e)[:50]}...")
        
        print(f"\n{'='*60}")
        print("SUMMARY OF AVAILABLE SESSIONS")
        print(f"{'='*60}")
        
        if found_sessions:
            for session in found_sessions:
                print(f"\n✅ {session['identifier']} (Name: {session['name']})")
                if session['has_results']:
                    print(f"   - Has results data")
                if session['has_laps']:
                    print(f"   - Has lap data")
                if not session['has_results'] and not session['has_laps']:
                    print(f"   - WARNING: No results or lap data!")
        else:
            print("\n❌ No sessions found!")
        
        print(f"\n{'='*60}\n")
        
        return found_sessions
        
    except Exception as e:
        print(f"Error loading event: {e}")
        return []


def check_all_2023_rounds():
    """Check all 2023 rounds to see which have SQ."""
    print("\n" + "="*60)
    print("CHECKING ALL 2023 ROUNDS FOR SPRINT SHOOTOUT")
    print("="*60 + "\n")
    
    for round_num in range(1, 25):
        try:
            sessions = check_sessions_available(2023, round_num)
            sq_available = any(s['identifier'].upper() in ['SQ', 'SS', 'SPRINTSHOOTOUT'] for s in sessions)
            
            if sq_available:
                print(f"✅ 2023 Round {round_num}: HAS SPRINT SHOOTOUT")
            else:
                print(f"❌ 2023 Round {round_num}: No sprint shootout")
                
        except Exception as e:
            print(f"⚠️  2023 Round {round_num}: Error - {str(e)[:50]}")


if __name__ == '__main__':
    # Check 2023 Round 4 specifically
    found = check_sessions_available(2023, 4)
    
    if found:
        print("\nUSE THESE IDENTIFIERS IN YOUR CODE:")
        for session in found:
            print(f"  session_type = '{session['identifier']}'")
    
    # Optionally check all rounds
    # check_all_2023_rounds()