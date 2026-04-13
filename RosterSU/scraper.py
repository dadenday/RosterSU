"""
Web scraper for Sun Airport Phu Quoc flight departures.

Fetches real-time flight data via the airport's REST API,
cross-references with local DB, and calculates delay adjustments.
"""

import logging
import sqlite3
import json
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

# Gracefully handle missing requests library
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None
    REQUESTS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("requests library not installed - flight sync feature disabled")

logger = logging.getLogger(__name__)

API_BASE_URL = "https://sunairport.com/phuquoc/cms/api/flights"
REQUEST_TIMEOUT = 15  # seconds


@dataclass
class ScrapedFlight:
    """A single flight record from the airport API."""
    flight_no: str           # e.g., "ZE582"
    scheduled_time: str      # "HHMM" format, e.g., "0830"
    estimated_time: str      # "HHMM" format, e.g., "1000"
    actual_time: Optional[str]  # "HHMM" or None
    ck_row: str              # e.g., "28-29"
    gate: str                # e.g., "9"
    status: str              # e.g., "DEPARTED"
    route: str               # e.g., "PQC-ICN"
    notes_en: str = ""       # e.g., "CHECK-IN 14:25"
    notes_vn: str = ""       # e.g., "LÀM THỦ TỤC LÚC 14:25"


@dataclass
class MatchResult:
    """A matched pair of scraped flight + DB flight."""
    scraped: ScrapedFlight
    db_flight: dict          # The flight dict from DB's full_data JSON
    db_date: str             # The work_date (DD.MM.YYYY)
    db_open: str             # Original open time, e.g., "08h00"
    db_close: str            # Original close time, e.g., "12h30"
    db_ckrow: Optional[str]  # Original ckrow (may be None)


@dataclass
class UpdatedFlight:
    """Result of delay recalculation."""
    flight_no: str
    new_open: str            # e.g., "10h00"
    new_close: str           # e.g., "14h30"
    new_ckrow: str           # e.g., "28-29"
    was_delayed: bool        # True if scheduled != estimated


class FlightScraper:
    """Fetches departure data from the Sun Airport API."""

    def fetch_departures(self, date: str) -> list[ScrapedFlight]:
        """
        Fetch departures for a given date.

        Args:
            date: ISO date string, e.g., "2026-04-11"

        Returns:
            List of ScrapedFlight objects. Empty list on error.
        """
        if not REQUESTS_AVAILABLE:
            logger.warning("requests library not available - cannot fetch flights")
            return []

        # Note: We intentionally do NOT call cleanup_stale_entries() here.
        # Stale entries are automatically handled by get_cached_flight() which
        # checks TTL and removes stale entries on access. Running cleanup on
        # every fetch would unnecessarily delete valid cache entries.

        try:
            params = {
                "type": "D",
                "date": date,
                # NOTE: limit=100 causes API to exclude some flights (e.g., ZF2602).
                # Omitting limit returns the correct dataset (61 flights for 2026-04-13).
            }
            resp = requests.get(API_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
            # API returns {"success": true, "data": [...]} — extract the array
            flights_data = payload.get("data", []) if isinstance(payload, dict) else payload
            if not isinstance(flights_data, list):
                logger.warning(f"Unexpected API response type: {type(flights_data)}")
                return []

            flights = []
            for item in flights_data:
                scraped_flight = ScrapedFlight(
                    flight_no=item.get("flightNo", "").strip().upper(),
                    scheduled_time=item.get("scheduledTime", ""),
                    estimated_time=item.get("estimatedTime", ""),
                    actual_time=item.get("actualTime"),
                    ck_row=item.get("ckRow") or "",
                    gate=item.get("gate", ""),
                    status=item.get("notesEn", "") or item.get("status", ""),
                    route=item.get("route", ""),
                    notes_en=item.get("notesEn", "") or "",
                    notes_vn=item.get("notesVn", "") or "",
                )
                flights.append(scraped_flight)

                # CRITICAL: Save to cache so it survives app restarts and provides
                # fallback when API is down. This also ensures cache stays current
                # when flight times are updated (e.g., delay announcements).
                #
                # IMPORTANT: Extract check-in open time from notesEn if available,
                # NOT the scheduled/estimated departure times!
                try:
                    from status_cache import save_flight_from_api
                    import re

                    notes_en = item.get("notesEn", "") or ""
                    # Extract check-in time from notesEn like "CHECK-IN 14:25"
                    status_time_for_cache = item.get("scheduledTime", "")  # Default to departure time
                    checkin_match = re.search(r'CHECK-IN\s+(\d{1,2})[:h](\d{2})', notes_en, re.IGNORECASE)
                    if checkin_match:
                        # Store check-in time as the primary status_time
                        hours = int(checkin_match.group(1))
                        minutes = int(checkin_match.group(2))
                        status_time_for_cache = f"{hours:02d}{minutes:02d}"

                    save_flight_from_api(date, item.get("flightNo", "").strip().upper(), {
                        "status_time": status_time_for_cache,
                        "status": item.get("notesEn", "") or item.get("status", ""),
                        "gate": item.get("gate", ""),
                        "ck_row": item.get("ckRow") or "",
                        "route": item.get("route", ""),
                        "notes_en": notes_en,
                        "notes_vn": item.get("notesVn", "") or "",
                    })
                except Exception as e:
                    logger.warning(f"Failed to cache flight {scraped_flight.flight_no}: {e}")

            logger.info(f"Fetched {len(flights)} departures for {date}")
            return flights

        except requests.exceptions.Timeout:
            logger.warning(f"Flight API timeout after {REQUEST_TIMEOUT}s")
            return []
        except requests.exceptions.RequestException as e:
            logger.warning(f"Flight API error: {e}")
            return []
        except (ValueError, KeyError) as e:
            logger.warning(f"Flight API parse error: {e}")
            return []

    def get_flights_with_cache(self, date_iso: str) -> list[tuple[ScrapedFlight, Optional[dict]]]:
        """Fetch API departures and merge with cached status data.

        Used ONLY by the API preview card. Falls back to disk cache
        when API is unavailable. Does NOT write to DB.
        """
        from status_cache import (
            get_cached_flight,
            get_flights_for_date,
            remove_past_flights,
        )

        # Clean up departed flights from cache
        current_time = datetime.now().strftime("%H%M")
        try:
            removed = remove_past_flights(current_time)
            if removed > 0:
                logger.info(f"Removed {removed} past flights from cache")
        except Exception as e:
            logger.warning(f"Failed to clean past flights from cache: {e}")

        # Fetch API data
        api_flights = self.fetch_departures(date_iso)

        if api_flights:
            # Merge API flights with cached status data
            results = []
            for api_flight in api_flights:
                cached = get_cached_flight(date_iso, api_flight.flight_no)
                results.append((api_flight, cached))
            logger.info(f"API fetch: {len(results)} flights for {date_iso} ({sum(1 for _, c in results if c)} have cache)")
            return results
        else:
            # API empty/timeout — fall back to disk cache for display
            cached_flights = get_flights_for_date(date_iso)
            if cached_flights:
                results = []
                for cf in cached_flights:
                    sf = ScrapedFlight(
                        flight_no=cf.get("flight_no", ""),
                        scheduled_time=cf.get("status_time", ""),
                        estimated_time=cf.get("status_time", ""),
                        actual_time=None,
                        ck_row=cf.get("ck_row", ""),
                        gate=cf.get("gate", ""),
                        status=cf.get("status", ""),
                        route=cf.get("route", ""),
                        notes_en=cf.get("notes_en", ""),
                        notes_vn=cf.get("notes_vn", ""),
                    )
                    results.append((sf, cf))
                logger.info(f"API empty, using {len(results)} cached flights for {date_iso}")
                return results
            else:
                logger.info(f"No API or cached data for {date_iso}")
                return []


# ---------------------------------------------------------------------------
# Time parsing helpers
# ---------------------------------------------------------------------------


def parse_time_hhmm(time_str: str) -> Optional[int]:
    """Parse 'HHMM' or 'HHhMM' to total minutes since midnight.

    Returns None if unparseable, 0 for midnight.

    Examples:
        '0830' -> 510
        '08h30' -> 510
        '1000' -> 600
        '00h00' -> 0
        '' -> None
    """
    if not time_str:
        return None
    # Normalize: replace 'h' or ':' with nothing
    cleaned = time_str.replace("h", "").replace(":", "").strip()
    if len(cleaned) < 3:
        return None
    # Pad if needed (e.g., "830" -> "0830")
    cleaned = cleaned.zfill(4)
    try:
        hours = int(cleaned[:2])
        minutes = int(cleaned[2:4])
        return hours * 60 + minutes
    except ValueError:
        return None


def format_time_hhmm_style(total_minutes: int) -> str:
    """Format total minutes to 'HHhMM' style.

    Handles next-day rollover via modulo 24h.

    Examples:
        510 -> "08h30"
        600 -> "10h00"
        1500 -> "01h00" (25h00 wraps to next day)
    """
    if total_minutes < 0:
        total_minutes = 0
    # Handle next-day rollover
    total_minutes = total_minutes % (24 * 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}h{minutes:02d}"


# ---------------------------------------------------------------------------
# DelayCalculator
# ---------------------------------------------------------------------------


class DelayCalculator:
    """Matches scraped flights with DB flights and calculates delay adjustments."""

    @staticmethod
    def normalize_flight_no(flight_no: str) -> str:
        """Normalize flight number for matching."""
        return flight_no.strip().upper()

    def match_flights(
        self,
        scraped: list[ScrapedFlight],
        db_flights: list[dict],
        db_date: str,
    ) -> list[MatchResult]:
        """
        Match scraped flights with DB flights by normalized flight number.

        Args:
            scraped: Flights from the API
            db_flights: Flight dicts from DB's full_data JSON
            db_date: The work_date (DD.MM.YYYY) for logging

        Returns:
            List of MatchResult for matched flights.
        """
        # Build lookup by normalized flight number
        db_lookup = {}
        for db_f in db_flights:
            call = self.normalize_flight_no(db_f.get("Call", ""))
            if call:
                if call in db_lookup:
                    logger.warning(f"Duplicate DB flight for {call} — last entry wins")
                db_lookup[call] = db_f

        results = []
        for s in scraped:
            key = self.normalize_flight_no(s.flight_no)
            if key in db_lookup:
                db_f = db_lookup[key]
                db_open = db_f.get("Open", "")
                db_close = db_f.get("Close", "")
                if db_open and db_close:  # Skip if missing times
                    results.append(MatchResult(
                        scraped=s,
                        db_flight=db_f,
                        db_date=db_date,
                        db_open=db_open,
                        db_close=db_close,
                        db_ckrow=db_f.get("ckRow"),
                    ))
                else:
                    logger.info(f"Skipping {key}: missing Open/Close times")

        logger.info(f"Matched {len(results)}/{len(scraped)} scraped flights to DB")
        return results

    def recalculate(self, match: MatchResult) -> Optional[UpdatedFlight]:
        """
        Recalculate open/close times based on delay.

        Logic:
            duration = db_close - db_open
            if scheduledTime != estimatedTime:
                new_open = estimatedTime
                new_close = new_open + duration
            else:
                no change needed (return None)

        Args:
            match: A matched flight pair

        Returns:
            UpdatedFlight if changes are needed, else None
        """
        s = match.scraped
        db_open_min = parse_time_hhmm(match.db_open)
        db_close_min = parse_time_hhmm(match.db_close)

        if db_open_min is None or db_close_min is None:
            logger.warning(
                f"Cannot parse times for {s.flight_no}: "
                f"Open={match.db_open}, Close={match.db_close}"
            )
            return None

        duration = db_close_min - db_open_min
        if duration < 0:
            duration += 24 * 60  # Handle midnight crossing
        if duration < 0:
            logger.warning(f"Still negative duration for {s.flight_no}: {duration}")
            return None

        # Check if there's a delay
        sched = parse_time_hhmm(s.scheduled_time)
        estim = parse_time_hhmm(s.estimated_time)

        if not s.estimated_time or sched == estim:
            # No delay - but still update ckRow if it changed
            new_ckrow = s.ck_row
            old_ckrow = match.db_ckrow or ""
            if new_ckrow and new_ckrow != old_ckrow:
                return UpdatedFlight(
                    flight_no=s.flight_no,
                    new_open=match.db_open,
                    new_close=match.db_close,
                    new_ckrow=new_ckrow,
                    was_delayed=False,
                )
            return None  # No changes needed

        # There is a delay - recalculate
        new_open = estim
        new_close = new_open + duration

        return UpdatedFlight(
            flight_no=s.flight_no,
            new_open=format_time_hhmm_style(new_open),
            new_close=format_time_hhmm_style(new_close),
            new_ckrow=s.ck_row,
            was_delayed=True,
        )


# ---------------------------------------------------------------------------
# AutoSyncService
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    """Summary of a sync run."""
    matched: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    details: list[str] = field(default_factory=list)


class AutoSyncService:
    """Orchestrates the full scrape -> match -> update pipeline."""

    def __init__(self, scraper=None, calculator=None):
        self.scraper = scraper or FlightScraper()
        self.calculator = calculator or DelayCalculator()

    def run_sync(self, db_conn, today_iso: str, today_ddmmyyyy: str) -> SyncResult:
        """
        Run the full sync pipeline.

        Args:
            db_conn: SQLite connection
            today_iso: Today's date in YYYY-MM-DD format
            today_ddmmyyyy: Today's date in DD.MM.YYYY format

        Returns:
            SyncResult with counts and detail log messages
        """
        result = SyncResult()

        # Step 1: Fetch departures from API
        logger.info(f"Starting flight sync for {today_iso}")
        scraped = self.scraper.fetch_departures(today_iso)
        if not scraped:
            result.details.append(f"No departures fetched for {today_iso}")
            return result

        # Step 2: Get today's schedule from DB
        cursor = db_conn.execute(
            "SELECT work_date, full_data FROM work_schedule WHERE work_date = ?",
            (today_ddmmyyyy,)
        )
        row = cursor.fetchone()

        if not row:
            result.details.append(f"No schedule in DB for {today_ddmmyyyy}")
            return result

        # Use positional access for safety (row[1] = full_data)
        try:
            data = json.loads(row[1])
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in DB for {today_ddmmyyyy}: {e}")
            result.errors += 1
            result.details.append(f"DB JSON error: {e}")
            return result
        db_flights = data.get("flights", [])
        if not db_flights:
            result.details.append(f"No flights in DB schedule for {today_ddmmyyyy}")
            return result

        # Step 3: Match scraped flights with DB flights
        matches = self.calculator.match_flights(scraped, db_flights, today_ddmmyyyy)
        result.matched = len(matches)

        # Step 4: Recalculate (display-only, DO NOT write to DB)
        recalculated = []
        for match in matches:
            updated = self.calculator.recalculate(match)
            if updated:
                recalculated.append(updated)
                delay_tag = "DELAY" if updated.was_delayed else "ckRow"
                result.details.append(
                    f"{delay_tag} {updated.flight_no}: "
                    f"{match.db_open}->{updated.new_open}, "
                    f"{match.db_close}->{updated.new_close}, "
                    f"ckRow={updated.new_ckrow}"
                )
            else:
                result.skipped += 1

        # Step 5: DO NOT write back to DB — API data is display-only
        # DB is populated exclusively by Excel roster file parsers
        if recalculated:
            result.details.append(f"{len(recalculated)} flights recalculated (display-only, DB untouched)")
        else:
            result.details.append(f"No changes needed ({result.skipped} flights checked)")

        logger.info(f"Flight sync complete: matched={result.matched}, updated={result.updated}, skipped={result.skipped}, errors={result.errors}")
        return result
