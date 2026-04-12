"""
JSON cache for flight status times.

Persists status times (check-in, gate, etc.) to disk so they survive app restarts.
When the app opens, it polls this cache first. If a flight has cached status data,
it uses that instead of polling the API. When a flight is departing/flying, the
cache entry is removed.

Cache structure:
{
  "2026-04-12": {
    "VN123": {
      "flight_no": "VN123",
      "status_time": "0830",        # HHMM format from status
      "status": "CHECK-IN",         # Flight status
      "gate": "9",
      "ck_row": "28-29",
      "route": "PQC-HAN",
      "notes_en": "CHECK-IN 14:25",
      "notes_vn": "LÀM THỦ TỤC LÚC 14:25",
      "cached_at": "2026-04-12T07:30:00"
    }
  }
}
"""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache file location (same directory as this module)
CACHE_FILE = Path(__file__).parent / "status_cache.json"
_cache_lock = threading.Lock()


def _load_cache_raw() -> dict:
    """Load raw cache from disk. Returns empty dict on error."""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load status cache: {e}")
    return {}


def _save_cache_raw(cache: dict) -> None:
    """Save raw cache to disk."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error(f"Failed to save status cache: {e}")


def get_cached_flight(date_iso: str, flight_no: str) -> Optional[dict]:
    """
    Get cached status data for a specific flight on a specific date.
    
    Args:
        date_iso: ISO date (YYYY-MM-DD)
        flight_no: Flight number (e.g., "VN123")
    
    Returns:
        Cached flight dict or None if not found.
    """
    with _cache_lock:
        cache = _load_cache_raw()
        date_data = cache.get(date_iso, {})
        return date_data.get(flight_no.upper())


def save_flight_status(
    date_iso: str,
    flight_no: str,
    status_time: str,
    status: str = "",
    gate: str = "",
    ck_row: str = "",
    route: str = "",
    notes_en: str = "",
    notes_vn: str = "",
) -> None:
    """
    Save status data for a flight.

    Args:
        date_iso: ISO date (YYYY-MM-DD)
        flight_no: Flight number
        status_time: Time from status in HHMM format (e.g., "0830")
        status: Flight status (e.g., "CHECK-IN", "BOARDING", "DEPARTED")
        gate: Gate number
        ck_row: Check-in row
        route: Flight route
        notes_en: English notes (e.g., "CHECK-IN 14:25" or "DEPARTED")
        notes_vn: Vietnamese notes (e.g., "LÀM THỦ TỤC LÚC 14:25" or "ĐÃ CẤT CÁNH")
    """
    with _cache_lock:
        cache = _load_cache_raw()

        if date_iso not in cache:
            cache[date_iso] = {}

        cache[date_iso][flight_no.upper()] = {
            "flight_no": flight_no.upper(),
            "status_time": status_time,
            "status": status,
            "gate": gate,
            "ck_row": ck_row,
            "route": route,
            "notes_en": notes_en,
            "notes_vn": notes_vn,
            "cached_at": datetime.now().isoformat(),
        }

        _save_cache_raw(cache)
        logger.debug(f"Saved cache for {flight_no} on {date_iso}")


def save_flight_from_api(
    date_iso: str,
    flight_no: str,
    scraped_flight: dict,
) -> None:
    """
    Save a complete flight from API data to cache.
    
    Args:
        date_iso: ISO date (YYYY-MM-DD)
        flight_no: Flight number
        scraped_flight: Dict with API flight data
    """
    save_flight_status(
        date_iso=date_iso,
        flight_no=flight_no,
        status_time=scraped_flight.get("status_time", ""),
        status=scraped_flight.get("status", ""),
        gate=scraped_flight.get("gate", ""),
        ck_row=scraped_flight.get("ck_row", ""),
        route=scraped_flight.get("route", ""),
        notes_en=scraped_flight.get("notes_en", ""),
        notes_vn=scraped_flight.get("notes_vn", ""),
    )


def remove_flight_cache(date_iso: str, flight_no: str) -> None:
    """Remove cached data for a specific flight."""
    with _cache_lock:
        cache = _load_cache_raw()
        
        if date_iso in cache and flight_no.upper() in cache[date_iso]:
            del cache[date_iso][flight_no.upper()]
            
            # Clean up empty date entries
            if not cache[date_iso]:
                del cache[date_iso]
            
            _save_cache_raw(cache)
            logger.debug(f"Removed cache for {flight_no} on {date_iso}")


def remove_past_flights(current_time_hhmm: str) -> int:
    """
    Remove cache entries for flights that have departed/are flying.
    
    A flight is considered departed if its status_time <= current_time.
    
    Args:
        current_time_hhmm: Current time in HHMM format (e.g., "1430")
    
    Returns:
        Number of entries removed.
    """
    removed_count = 0
    statuses_departed = {"DEPARTED", "FLYING", "LANDED", "ARRIVED"}
    
    with _cache_lock:
        cache = _load_cache_raw()
        dates_to_clean = []
        
        for date_iso, flights in list(cache.items()):
            flights_to_remove = []
            
            for flight_no, flight_data in flights.items():
                status = flight_data.get("status", "").upper()
                status_time = flight_data.get("status_time", "")
                
                # Remove if departed/landed, or if status_time is in the past
                if status in statuses_departed:
                    flights_to_remove.append(flight_no)
                elif status_time and status_time <= current_time_hhmm:
                    # Status time is in the past - assume departed
                    flights_to_remove.append(flight_no)
            
            for flight_no in flights_to_remove:
                del flights[flight_no]
                removed_count += 1
                logger.debug(f"Auto-removed past flight {flight_no} on {date_iso}")
            
            # Mark empty dates for cleanup
            if not flights:
                dates_to_clean.append(date_iso)
        
        for date_iso in dates_to_clean:
            del cache[date_iso]
        
        if removed_count > 0:
            _save_cache_raw(cache)
        
        return removed_count


def get_all_cached_dates() -> list[str]:
    """Return list of all dates with cached data."""
    with _cache_lock:
        cache = _load_cache_raw()
        return sorted(cache.keys())


def get_flights_for_date(date_iso: str) -> list[dict]:
    """Return all cached flights for a specific date."""
    with _cache_lock:
        cache = _load_cache_raw()
        return list(cache.get(date_iso, {}).values())
