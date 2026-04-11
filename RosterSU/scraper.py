"""
Web scraper for Sun Airport Phu Quoc flight departures.

Fetches real-time flight data via the airport's REST API,
cross-references with local DB, and calculates delay adjustments.
"""

import logging
import requests
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

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
        try:
            params = {
                "type": "D",
                "date": date,
                "limit": 100,
            }
            resp = requests.get(API_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            flights = []
            for item in data:
                flights.append(ScrapedFlight(
                    flight_no=item.get("flightNo", "").strip().upper(),
                    scheduled_time=item.get("scheduledTime", ""),
                    estimated_time=item.get("estimatedTime", ""),
                    actual_time=item.get("actualTime"),
                    ck_row=item.get("ckRow", ""),
                    gate=item.get("gate", ""),
                    status=item.get("notesEn", "") or item.get("status", ""),
                    route=item.get("route", ""),
                ))
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
