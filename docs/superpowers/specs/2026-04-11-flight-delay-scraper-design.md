# Design: Flight Delay Auto-Scraper for RosterSU

**Date:** 2026-04-11  
**Status:** Approved  
**Author:** Brainstorming Session

---

## 1. Overview

Add a configurable web scraping feature that fetches real-time flight departure data from Sun Airport Phu Quoc's API, cross-references it with the local schedule database, recalculates delay-adjusted times, updates the database, and adds a `ckRow` (check-in counter row) column to flight records.

**Config label (Vietnamese):** "Kích hoạt tự động dò web bãi đáp máy bay:"

---

## 2. Target API

**Endpoint:** `GET https://sunairport.com/phuquoc/cms/api/flights`

**Query parameters:**
| Param | Value | Purpose |
|-------|-------|---------|
| `type` | `D` | Departures |
| `date` | `YYYY-MM-DD` | Flight date (today) |
| `limit` | `100` | Max results |

**Response fields per flight:**
- `flightNo` — e.g., "ZE582"
- `scheduledTime` — "HHMM" format
- `estimatedTime` — "HHMM" format (differs when delayed)
- `actualTime` — "HHMM" format
- `ckRow` — e.g., "28-29"
- `gate` — boarding gate
- `status` / `notesVn` / `notesEn` — flight status
- `route`, `airlineName`, `cityName`, `aircraft`, etc.

---

## 3. Database Changes

### 3.1 Schema Migration

Add `ckrow` column to `work_schedule` table:
```sql
ALTER TABLE work_schedule ADD COLUMN ckrow TEXT;
```

This column is nullable and optional for backward compatibility.

### 3.2 Updated `full_data` JSON Structure

Each flight in the `flights` array now includes `ckRow`:

```json
{
  "date": "11.04.2026",
  "shift": "08:00-17:00",
  "flights": [
    {
      "Type": "B737",
      "Call": "ZE582",
      "Route": "PQC-ICN",
      "Open": "10h00",
      "Close": "14h30",
      "Bay": "9",
      "Names": "...",
      "ckRow": "28-29"
    }
  ]
}
```

---

## 4. Module Design: `RosterSU/scraper.py`

### 4.1 `FlightScraper` Class

Responsible for fetching and parsing API data.

```python
class FlightScraper:
    def fetch_departures(self, date: str) -> list[ScrapedFlight]
```

- `date` in `YYYY-MM-DD` format
- Returns list of `ScrapedFlight` dataclasses
- Handles HTTP errors gracefully (returns empty list + logs warning)
- Timeout: 15 seconds
- User-Agent: Standard requests header (no spoofing needed)

**`ScrapedFlight` dataclass:**
```python
@dataclass
class ScrapedFlight:
    flight_no: str
    scheduled_time: str    # "HHMM"
    estimated_time: str    # "HHMM"
    actual_time: str       # "HHMM" (nullable)
    ck_row: str            # e.g., "28-29"
    gate: str              # e.g., "9"
    status: str            # e.g., "DEPARTED"
    route: str             # e.g., "PQC-ICN"
```

### 4.2 `DelayCalculator` Class

Matches scraped flights with DB flights and calculates adjusted times.

```python
class DelayCalculator:
    def match_flights(self, scraped: list[ScrapedFlight], db_flights: list[dict]) -> list[MatchResult]
    def recalculate(self, match: MatchResult) -> UpdatedFlight | None
```

**Matching logic:**
- Normalize flight numbers (strip whitespace, uppercase)
- Match by `flightNo` + `date`
- One-to-one matching; if multiple DB flights match one scraped flight, pick the first

**Delay calculation:**
```
duration = db_close - db_open   (in minutes)
if scraped.scheduledTime != scraped.estimatedTime:
    new_open = scraped.estimatedTime
    new_close = new_open + duration
    update = True
else:
    new_open = scraped.scheduledTime  (or keep DB value)
    update = False  (no delay, no change needed)

new_ckrow = scraped.ckRow
```

**Time format conversion:**
- Input: `"HHMM"` → `"HHhMM"` (e.g., `"0830"` → `"08h30"`)
- Arithmetic: Parse to `datetime.timedelta` or raw minutes

### 4.3 `AutoSyncService` Class

Orchestrates the full pipeline on app startup.

```python
class AutoSyncService:
    def run_sync(self, config: dict, db_conn, state_lock, bump_rev) -> SyncResult
```

**Pipeline:**
1. Check `config["enable_flight_sync"]` — if false, skip
2. Determine today's date in `YYYY-MM-DD`
3. Call `FlightScraper.fetch_departures(today)`
4. Query DB for today's `work_schedule` rows
5. For each row, parse `full_data` JSON, extract flights
6. Call `DelayCalculator.match_flights()` + `recalculate()`
7. For each match with changes:
   - Update `Open`, `Close`, `ckRow` in flight dict
   - Write updated `full_data` JSON back to DB
   - Log: `"✏️ ZE582: 08h00→10h00, 12h30→14h30, ckRow=28-29"`
8. Call `bump_db_rev()` to trigger UI refresh
9. Return `SyncResult` with counts: `{matched, updated, skipped, errors}`

---

## 5. Startup Integration

In `roster_single_user.py`, after app initialization and DB setup:

```python
if config.get("enable_flight_sync", False):
    sync_service = AutoSyncService()
    result = sync_service.run_sync(
        config=merged_config,
        db_conn=db,
        state_lock=STATE_LOCK,
        bump_rev=bump_db_rev
    )
    logger.info(f"Flight sync complete: {result}")
```

This runs **once on startup** in the main thread (blocking, but fast — ~2-3 seconds). If it fails, it logs a warning and continues (does not crash the app).

---

## 6. Config System Changes

### 6.1 `rosterSU_config.json`

New field:
```json
{
  "enable_flight_sync": false
}
```

Default: `false` (opt-in)

### 6.2 `config.py`

Add to `DEFAULT_CONFIG`:
```python
"enable_flight_sync": False,
```

### 6.3 Settings UI (routes.py / components.py)

Add a toggle checkbox in the Settings tab:

```python
CheckboxX(id="enable-flight-sync", checked=config.get("enable_flight_sync", False))
Label("Kích hoạt tự động dò web bãi đáp máy bay:", for="enable-flight-sync")
```

On save, write to `rosterSU_config.json` via existing config update endpoint.

---

## 7. Error Handling

| Scenario | Behavior |
|----------|----------|
| API unreachable | Log warning, skip sync, continue app startup |
| API returns empty list | Log info ("No departures found for today"), skip |
| No matching DB flights | Log info ("No matching flights in DB for today") |
| Network timeout (>15s) | Log warning, skip sync, continue |
| Malformed JSON response | Log error, skip sync, continue |
| DB write fails | Log error, rollback, continue |

**No app crashes.** All errors are caught, logged, and gracefully degraded.

---

## 8. Dependencies

New dependency: `requests` (already likely installed, but add to `requirements.txt`)

No browser automation, no headless Chrome, no proot-distro needed.

---

## 9. Migration Path

1. Add `ckrow` column via `ALTER TABLE` (idempotent — catch "duplicate column" error)
2. Add `enable_flight_sync` to config (default: `false`)
3. Add scraper module
4. Integrate into startup
5. Add UI toggle
6. Test end-to-end

---

## 10. Testing Strategy

- **Unit tests:** `DelayCalculator.match_flights()`, `recalculate()` with sample data
- **Integration test:** Mock API response, verify DB updates
- **Manual test:** Run app with `enable_flight_sync: true`, check logs and UI

---

## 11. Future Considerations (Out of Scope)

- Fetching arrivals (`type=A`) in addition to departures
- Fetching future dates (not just today)
- Visual diff modal before applying changes
- Periodic re-sync (e.g., every 30 minutes via background thread)
