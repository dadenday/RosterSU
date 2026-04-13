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

# Cache entry TTL (time-to-live) in minutes
# Flight status data should refresh every 5-10 minutes
CACHE_TTL_MINUTES = 10


def _load_cache_raw() -> dict:
    """Load raw cache from disk. Returns empty dict on error."""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load status cache: {e}")
    return {}


def _is_cache_stale(cached_at: str, ttl_minutes: int = CACHE_TTL_MINUTES) -> bool:
    """Check if a cache entry is stale based on its timestamp.

    Args:
        cached_at: ISO timestamp when cache was written
        ttl_minutes: Time-to-live in minutes

    Returns:
        True if cache entry is older than TTL
    """
    try:
        cached_time = datetime.fromisoformat(cached_at)
        age = datetime.now() - cached_time
        return age.total_seconds() > (ttl_minutes * 60)
    except (ValueError, TypeError):
        # If we can't parse the timestamp, consider it stale
        return True


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

    Returns None if:
    - Not found in cache
    - Cache entry is stale (older than TTL)

    Args:
        date_iso: ISO date (YYYY-MM-DD)
        flight_no: Flight number (e.g., "VN123")

    Returns:
        Cached flight dict or None if not found or stale.
    """
    with _cache_lock:
        cache = _load_cache_raw()
        date_data = cache.get(date_iso, {})
        flight_data = date_data.get(flight_no.upper())

        if flight_data is None:
            return None

        # Check if cache entry is stale
        cached_at = flight_data.get("cached_at")
        if cached_at and _is_cache_stale(cached_at):
            logger.debug(f"Cache stale for {flight_no} on {date_iso} (cached at {cached_at})")
            # Remove stale entry
            del date_data[flight_no.upper()]
            if not date_data:
                del cache[date_iso]
            _save_cache_raw(cache)
            return None

        return flight_data


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

    This will overwrite any existing cached data for this flight,
    effectively refreshing the cache entry.

    Args:
        date_iso: ISO date (YYYY-MM-DD)
        flight_no: Flight number
        status_time: Time from status in HHMM format (e.g., "0830")
                     **IMPORTANT**: This should be the CHECK-IN OPEN TIME extracted
                     from notes_en (e.g., "CHECK-IN 14:25" → "1425"), NOT the
                     scheduled/estimated departure time.
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


def cleanup_stale_entries() -> int:
    """
    Remove all stale cache entries across all dates.

    Returns:
        Number of entries removed.
    """
    removed_count = 0

    with _cache_lock:
        cache = _load_cache_raw()
        dates_to_clean = []

        for date_iso in list(cache.keys()):
            flights = cache[date_iso]
            flights_to_remove = []

            for flight_no, flight_data in flights.items():
                cached_at = flight_data.get("cached_at")
                if cached_at and _is_cache_stale(cached_at):
                    flights_to_remove.append(flight_no)

            for flight_no in flights_to_remove:
                del flights[flight_no]
                removed_count += 1
                logger.debug(f"Cleaned stale cache for {flight_no} on {date_iso}")

            # Mark empty dates for cleanup
            if not flights:
                dates_to_clean.append(date_iso)

        for date_iso in dates_to_clean:
            del cache[date_iso]

        if removed_count > 0:
            _save_cache_raw(cache)
            logger.info(f"Cache cleanup: removed {removed_count} stale entries")

        return removed_count
