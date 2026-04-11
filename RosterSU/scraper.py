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
