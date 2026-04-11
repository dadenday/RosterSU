# Flight Delay Auto-Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a configurable web scraping feature that fetches flight departure data from Sun Airport Phu Quoc API, recalculates delay-adjusted times, updates the database, and adds ckRow (check-in counter row) to flight records.

**Architecture:** Direct API calls via Python `requests` library to `https://sunairport.com/phuquoc/cms/api/flights`, cross-reference with local DB by flight number + date, recalculate open/close times based on delay, update `full_data` JSON and `ckrow` column.

**Tech Stack:** Python 3, `requests`, SQLite, FastHTML (for config UI toggle)

---

### Task 1: Add `enable_flight_sync` to config and DB migration

**Files:**
- Modify: `/data/data/com.termux/files/home/projects/roster-app/RosterSU/config.py`
- Modify: `/data/data/com.termux/files/home/projects/roster-app/RosterSU/database.py`

- [ ] **Step 1: Add `enable_flight_sync` to DEFAULT_CONFIG in config.py**

Add `"enable_flight_sync": False` to the `DEFAULT_CONFIG` dict in the "User preferences" section:

```python
DEFAULT_CONFIG = {
    # User preferences
    "aliases": ["Ấn", "ẨN", "Ẩn", "Nguyễn Ngọc Ấn", "NGỌC ẤN", "Nguyễn Ngọc Ẩn", "NGỌC ẨN", "Ân", "Án"],
    "enable_flight_sync": False,  # NEW: Toggle for flight delay auto-sync
    "aircraft": {
```

- [ ] **Step 2: Add `ckrow` column migration in database.py**

Add a new function `add_ckrow_column()` after the `init_db()` function:

```python
def add_ckrow_column():
    """Add ckrow column to work_schedule if it doesn't exist (idempotent)."""
    with db_conn() as conn:
        try:
            conn.execute("ALTER TABLE work_schedule ADD COLUMN ckrow TEXT")
            conn.commit()
            debug_log("Added ckrow column to work_schedule")
        except Exception as e:
            # Column may already exist — ignore duplicate column errors
            if "duplicate column name" not in str(e).lower():
                debug_log(f"add_ckrow_column error: {str(e)}")
```

- [ ] **Step 3: Call `add_ckrow_column()` at end of `init_db()`**

At the end of the `init_db()` function, before `conn.close()`, add:

```python
    # Migration: add ckrow column if missing
    try:
        conn.execute("ALTER TABLE work_schedule ADD COLUMN ckrow TEXT")
        conn.commit()
        debug_log("Added ckrow column to work_schedule")
    except Exception as e:
        if "duplicate column name" not in str(e).lower():
            debug_log(f"ckrow migration skipped: {str(e)}")
```

- [ ] **Step 4: Verify no syntax errors**

Run: `python3 -c "import sys; sys.path.insert(0, 'RosterSU'); import config; print('enable_flight_sync' in config.DEFAULT_CONFIG)"`
Expected: `True`

Run: `python3 -c "import sys; sys.path.insert(0, 'RosterSU'); import database; print('add_ckrow_column' in dir(database))"`
Expected: `True` (or just check it doesn't crash)

- [ ] **Step 5: Commit**

```bash
git add RosterSU/config.py RosterSU/database.py
git commit -m "feat: add enable_flight_sync config and ckrow column migration"
```

---

### Task 2: Create scraper module with data types and API client

**Files:**
- Create: `/data/data/com.termux/files/home/projects/roster-app/RosterSU/scraper.py`

- [ ] **Step 1: Create scraper.py with dataclasses and FlightScraper class**

```python
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
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import sys; sys.path.insert(0, 'RosterSU'); import scraper; print('FlightScraper loaded')"`
Expected: `FlightScraper loaded`

- [ ] **Step 3: Add `requests` to requirements.txt if not present**

Check `/data/data/com.termux/files/home/projects/roster-app/RosterSU/requirements.txt` for `requests`. If missing, add it.

- [ ] **Step 4: Commit**

```bash
git add RosterSU/scraper.py RosterSU/requirements.txt
git commit -m "feat: add FlightScraper module with API client"
```

---

### Task 3: Implement DelayCalculator with matching and recalculation logic

**Files:**
- Modify: `/data/data/com.termux/files/home/projects/roster-app/RosterSU/scraper.py` (append to end)

- [ ] **Step 1: Add time parsing helper functions**

Add these utility functions before the `DelayCalculator` class:

```python
def parse_time_hhmm(time_str: str) -> int:
    """Parse 'HHMM' or 'HHhMM' to total minutes since midnight.

    Examples:
        '0830' → 510
        '08h30' → 510
        '1000' → 600
    """
    if not time_str:
        return 0
    # Normalize: replace 'h' or ':' with nothing
    cleaned = time_str.replace("h", "").replace(":", "").strip()
    if len(cleaned) < 3:
        return 0
    # Pad if needed (e.g., "830" → "0830")
    cleaned = cleaned.zfill(4)
    try:
        hours = int(cleaned[:2])
        minutes = int(cleaned[2:4])
        return hours * 60 + minutes
    except ValueError:
        return 0


def format_time_hhmm_style(total_minutes: int) -> str:
    """Format total minutes to 'HHhMM' style.

    Examples:
        510 → "08h30"
        600 → "10h00"
    """
    if total_minutes < 0:
        total_minutes = 0
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours:02d}h{minutes:02d}"
```

- [ ] **Step 2: Add DelayCalculator class**

Append after the helper functions:

```python
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

        if db_open_min == 0 or db_close_min == 0:
            logger.warning(f"Cannot parse times for {s.flight_no}: Open={match.db_open}, Close={match.db_close}")
            return None

        duration = db_close_min - db_open_min
        if duration < 0:
            logger.warning(f"Negative duration for {s.flight_no}: {match.db_open}-{match.db_close}")
            return None

        # Check if there's a delay
        sched = parse_time_hhmm(s.scheduled_time)
        estim = parse_time_hhmm(s.estimated_time)

        if sched == estim or estim == 0:
            # No delay — but still update ckRow if it changed
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

        # There is a delay — recalculate
        new_open = estim
        new_close = new_open + duration

        return UpdatedFlight(
            flight_no=s.flight_no,
            new_open=format_time_hhmm_style(new_open),
            new_close=format_time_hhmm_style(new_close),
            new_ckrow=s.ck_row,
            was_delayed=True,
        )
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import sys; sys.path.insert(0, 'RosterSU'); from scraper import DelayCalculator; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Quick unit test inline**

Run: `python3 -c "
import sys; sys.path.insert(0, 'RosterSU')
from scraper import parse_time_hhmm, format_time_hhmm_style
assert parse_time_hhmm('0830') == 510
assert parse_time_hhmm('08h30') == 510
assert parse_time_hhmm('1000') == 600
assert format_time_hhmm_style(510) == '08h30'
assert format_time_hhmm_style(600) == '10h00'
print('Time parsing tests passed')
"`
Expected: `Time parsing tests passed`

- [ ] **Step 5: Commit**

```bash
git add RosterSU/scraper.py
git commit -m "feat: add DelayCalculator with matching and recalculation logic"
```

---

### Task 4: Implement AutoSyncService to orchestrate the full pipeline

**Files:**
- Modify: `/data/data/com.termux/files/home/projects/roster-app/RosterSU/scraper.py` (append to end)

- [ ] **Step 1: Add dataclasses for sync result and AutoSyncService class**

```python
from dataclasses import dataclass, field
import json


@dataclass
class SyncResult:
    """Summary of a sync run."""
    matched: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    details: list[str] = field(default_factory=list)


class AutoSyncService:
    """Orchestrates the full scrape → match → update pipeline."""

    def __init__(self):
        self.scraper = FlightScraper()
        self.calculator = DelayCalculator()

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
            result.details.append(f"⚠️ No departures fetched for {today_iso}")
            return result

        # Step 2: Get today's schedule from DB
        row = db_conn.execute(
            "SELECT work_date, full_data FROM work_schedule WHERE work_date = ?",
            (today_ddmmyyyy,)
        ).fetchone()

        if not row:
            result.details.append(f"ℹ️ No schedule in DB for {today_ddmmyyyy}")
            return result

        data = json.loads(row["full_data"])
        db_flights = data.get("flights", [])
        if not db_flights:
            result.details.append(f"ℹ️ No flights in DB schedule for {today_ddmmyyyy}")
            return result

        # Step 3: Match scraped flights with DB flights
        matches = self.calculator.match_flights(scraped, db_flights, today_ddmmyyyy)
        result.matched = len(matches)

        # Step 4: Recalculate and apply updates
        updated_flights = []
        for match in matches:
            updated = self.calculator.recalculate(match)
            if updated:
                # Update the original db_flight dict
                match.db_flight["Open"] = updated.new_open
                match.db_flight["Close"] = updated.new_close
                match.db_flight["ckRow"] = updated.new_ckrow
                updated_flights.append(match.db_flight)
                result.updated += 0  # Count below

                delay_tag = "✏️ DELAY" if updated.was_delayed else "📍 ckRow"
                result.details.append(
                    f"{delay_tag} {updated.flight_no}: "
                    f"{match.db_open}→{updated.new_open}, "
                    f"{match.db_close}→{updated.new_close}, "
                    f"ckRow={updated.new_ckrow}"
                )
            else:
                result.skipped += 1

        # Step 5: Write back to DB if any changes
        if updated_flights:
            try:
                data["flights"] = db_flights  # Already mutated in-place
                new_json = json.dumps(data, ensure_ascii=False, default=str)
                db_conn.execute(
                    "UPDATE work_schedule SET full_data = ?, last_updated = CURRENT_TIMESTAMP WHERE work_date = ?",
                    (new_json, today_ddmmyyyy)
                )
                db_conn.commit()
                result.details.append(f"✅ DB updated: {len(updated_flights)} flights changed")
            except Exception as e:
                logger.error(f"DB write error during sync: {e}")
                result.errors += 1
                result.details.append(f"❌ DB write error: {e}")
        else:
            result.details.append(f"ℹ️ No changes needed ({result.skipped} flights checked)")

        logger.info(f"Flight sync complete: matched={result.matched}, updated={result.updated}, skipped={result.skipped}")
        return result
```

- [ ] **Step 2: Verify syntax**

Run: `python3 -c "import sys; sys.path.insert(0, 'RosterSU'); from scraper import AutoSyncService; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add RosterSU/scraper.py
git commit -m "feat: add AutoSyncService for full pipeline orchestration"
```

---

### Task 5: Integrate sync into app startup in roster_single_user.py

**Files:**
- Modify: `/data/data/com.termux/files/home/projects/roster-app/RosterSU/roster_single_user.py`

- [ ] **Step 1: Find the app startup location**

Search for where the app initializes — look for `app = fast_app(...)`, or the `before`/`startup` hook, or the main block at the bottom of the file. Look for where `init_db()` is called.

- [ ] **Step 2: Add sync call after init_db**

After `init_db()` is called (or in the startup sequence), add:

```python
# --- Flight Delay Auto-Sync ---
def _run_flight_startup_sync():
    """Run flight sync at startup if enabled. Non-blocking, logs results."""
    try:
        merged = _load_merged_config()
        if not merged.get("enable_flight_sync", False):
            debug_log("Flight sync: disabled in config, skipping")
            return

        from scraper import AutoSyncService
        from database import get_db

        today_iso = datetime.now().strftime("%Y-%m-%d")
        today_ddmmyyyy = datetime.now().strftime("%d.%m.%y")

        conn = get_db()
        try:
            service = AutoSyncService()
            sync_result = service.run_sync(conn, today_iso, today_ddmmyyyy)
            for detail in sync_result.details:
                debug_log(f"Flight sync: {detail}")
        finally:
            conn.close()

        # Bump revision to trigger UI refresh
        from state import bump_db_rev
        bump_db_rev()
    except Exception as e:
        debug_log(f"Flight sync startup error: {e}")
        # Do NOT crash — app continues without sync

# Call it after init_db
_run_flight_startup_sync()
```

**Note:** Place this import at the top of `roster_single_user.py` if not already present:
```python
from config import _load_merged_config
```

And ensure `datetime` is imported:
```python
from datetime import datetime
```

- [ ] **Step 3: Verify imports don't cause circular dependency**

The `_run_flight_startup_sync` function uses lazy imports (`from scraper import ...`, `from database import get_db`) to avoid circular imports. Verify the app still starts:

Run: `cd /data/data/com.termux/files/home/projects/roster-app/RosterSU && python3 -c "import roster_single_user; print('Module loads OK')"`

Expected: `Module loads OK` (app doesn't need to run, just import cleanly)

- [ ] **Step 4: Commit**

```bash
git add RosterSU/roster_single_user.py
git commit -m "feat: integrate flight sync into app startup"
```

---

### Task 6: Add UI toggle for enable_flight_sync in Settings tab

**Files:**
- Modify: `/data/data/com.termux/files/home/projects/roster-app/RosterSU/routes.py`

- [ ] **Step 1: Add the toggle checkbox to the settings form**

In the `settings_page()` function, after the "Data section" card and before the "Export section" card, add a new card for Flight Sync. Insert this between the Data section div and the Export section div:

```python
        # Flight Delay Auto-Sync toggle
        Div(
            H5("🛫 Quét web sân bay"),
            P("Tự động cập nhật giờ bay và quầy check-in từ web sân bay.",
              style="font-size:0.8rem; color:var(--muted); margin-bottom:0.5rem;"),
            Div(
                CheckboxX(
                    id="enable-flight-sync",
                    name="enable_flight_sync",
                    value="1",
                    checked=config.get("enable_flight_sync", False),
                ),
                Label(
                    "Kích hoạt tự động dò web bãi đáp máy bay:",
                    for_="enable-flight-sync",
                    style="margin-left:0.3rem; font-weight:500;",
                ),
                style="display:flex; align-items:center; margin-bottom:0.5rem;"
            ),
            cls="card mb-3"
        ),
```

- [ ] **Step 2: Add `enable_flight_sync` parameter to the route handler**

Update the `settings_page()` function signature to accept the new checkbox value. Add `enable_flight_sync: str = ""` to the parameter list:

```python
@rt("/settings", methods=["get", "post"])
def settings_page(request: Request, aliases:str="", aircraft_airbus:str="", aircraft_boeing:str="", aircraft_other:str="",
                  static_html_scope:str="", static_html_count:str="",
                  db_path:str="", auto_ingest_dir:str="", export_dir:str="",
                  static_html_output_dir:str="", processed_archive_dir:str="",
                  enable_flight_sync: str = ""):  # NEW PARAM
```

- [ ] **Step 3: Save the toggle value in POST handler**

In the POST handling section of `settings_page()`, after the `config["processed_archive_dir"]` save block, add:

```python
        # Save flight sync toggle
        config["enable_flight_sync"] = enable_flight_sync == "1"
```

Insert it right after this block:
```python
        if processed_archive_dir:
            config["processed_archive_dir"] = processed_archive_dir
```

So it becomes:
```python
        if processed_archive_dir:
            config["processed_archive_dir"] = processed_archive_dir

        # Save flight sync toggle
        config["enable_flight_sync"] = enable_flight_sync == "1"
```

- [ ] **Step 4: Verify syntax**

Run: `python3 -c "import sys; sys.path.insert(0, 'RosterSU'); import routes; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add RosterSU/routes.py
git commit -m "feat: add flight sync toggle to settings UI"
```

---

### Task 7: End-to-end manual test

**Files:** None (manual testing)

- [ ] **Step 1: Install `requests` dependency**

Run: `pip install requests`

- [ ] **Step 2: Enable flight sync in config JSON for testing**

Edit `/data/data/com.termux/files/home/projects/roster-app/rosterSU_config.json` and add:

```json
{
  "enable_flight_sync": true
}
```

(Or use the settings UI after starting the app.)

- [ ] **Step 3: Start the app and check logs**

Run the app: `python3 RosterSU/roster_single_user.py`

Look in the console output for lines like:
```
Flight sync: Starting flight sync for 2026-04-11
Flight sync: Fetched 45 departures for 2026-04-11
Flight sync: Matched 5/45 scraped flights to DB
Flight sync: ✏️ DELAY ZE582: 08h00→10h00, 12h30→14h30, ckRow=28-29
Flight sync: ✅ DB updated: 1 flights changed
Flight sync complete: matched=5, updated=1, skipped=4
```

- [ ] **Step 4: Verify DB update**

Run: `python3 -c "
import sys; sys.path.insert(0, 'RosterSU')
from database import get_db, load_history
from config import _load_merged_config
import json

rows = load_history(limit=5)
for row in rows:
    data = json.loads(row['full_data'])
    for f in data.get('flights', []):
        if 'ckRow' in f:
            print(f\"{data['date']} | {f.get('Call')} | Open={f.get('Open')} | Close={f.get('Close')} | ckRow={f.get('ckRow')}\")
"`

- [ ] **Step 5: Verify UI toggle works**

Open the app in browser → Settings tab → Check/uncheck "Kích hoạt tự động dò web bãi đáp máy bay" → Save → Verify config JSON updated.

- [ ] **Step 6: Commit any test config changes** (optional — don't commit `enable_flight_sync: true` if you want default-off)

```bash
git status
```

---

### Task 8: Final cleanup and verification

- [ ] **Step 1: Run all verification checks**

Run: `python3 -c "
import sys
sys.path.insert(0, 'RosterSU')
from scraper import FlightScraper, DelayCalculator, AutoSyncService
from scraper import parse_time_hhmm, format_time_hhmm_style

# Time parsing tests
assert parse_time_hhmm('0830') == 510
assert parse_time_hhmm('08h30') == 510
assert parse_time_hhmm('1000') == 600
assert format_time_hhmm_style(510) == '08h30'
assert format_time_hhmm_style(600) == '10h00'
assert format_time_hhmm_style(870) == '14h30'

print('All unit tests passed')
"`

Expected: `All unit tests passed`

- [ ] **Step 2: Verify all files load without errors**

Run: `python3 -c "
import sys
sys.path.insert(0, 'RosterSU')
import config
import database
import scraper
print('All modules load cleanly')
"`

Expected: `All modules load cleanly`

- [ ] **Step 3: Commit all remaining changes**

```bash
git add -A
git commit -m "feat: flight delay scraper — complete implementation"
```

---

## Summary of Files Changed

| File | Action | Purpose |
|------|--------|---------|
| `RosterSU/config.py` | Modified | Added `enable_flight_sync` to DEFAULT_CONFIG |
| `RosterSU/database.py` | Modified | Added `ckrow` column migration in `init_db()` |
| `RosterSU/scraper.py` | Created | New module: FlightScraper, DelayCalculator, AutoSyncService |
| `RosterSU/roster_single_user.py` | Modified | Added startup sync call |
| `RosterSU/routes.py` | Modified | Added settings UI toggle for flight sync |
| `RosterSU/requirements.txt` | Modified (maybe) | Added `requests` if not present |
