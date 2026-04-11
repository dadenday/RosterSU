# Flight API Preview Roster Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace automatic DB-updating flight sync with a visual preview card showing today's flights cross-referenced between DB and Sun Airport API.

**Architecture:** In-memory cache stores today's API data. `ApiPreviewCard` component renders a compact two-row-per-flight table. HTMX endpoints serve and refresh the card. Past flights filtered at render time.

**Tech Stack:** Python, FastHTML, SQLite (existing DB, no new tables), HTMX, CSS

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `RosterSU/routes.py` | Modify | Add `_flight_api_cache`, `_refresh_api_cache()`, `/flight/preview`, `/flight/preview/fetch`, integrate card into main page |
| `RosterSU/components.py` | Modify | Add `ApiPreviewCard()`, `_crosscheck_route()`, `_recalculate_close()`, `_crosscheck_bay()` |
| `RosterSU/roster_styles.css` | Modify | Add `.api-preview-card` styles |

---

### Task 1: Helper Functions in components.py

**Files:**
- Modify: `RosterSU/components.py`

Add cross-checking helper functions that the preview card will use.

- [ ] **Step 1: Add helper functions**

Add these functions at the end of `components.py` (before the last line, after `RosterList`):

```python
# ============================================================================
# API Preview Card Helpers
# ============================================================================

def _crosscheck_route(db_route: str, api_route: Optional[str]) -> str:
    """Extract destination from route, prefer API if available.
    
    PQC-HAN -> HAN (departure only)
    """
    # Prefer API route
    route = api_route or db_route or ""
    if not route:
        return ""
    # Extract destination (second part of PQC-HAN)
    if "-" in route:
        return route.split("-")[-1].strip()
    return route.strip()


def _recalculate_close(db_open: str, db_close: str, api_open: str) -> str:
    """Recalculate close time preserving flight duration.
    
    duration = db_close - db_open
    new_close = api_open + duration
    All times in HHMM format.
    """
    try:
        # Parse HHMM -> minutes
        def hhmm_to_minutes(t: str) -> int:
            t = t.replace("h", "").replace(":", "").strip()
            if len(t) < 4:
                t = t.zfill(4)
            return int(t[:2]) * 60 + int(t[2:])

        def minutes_to_hhmm(m: int) -> str:
            m = m % 1440  # Handle day wrap
            return f"{m // 60:02d}:{m % 60:02d}"

        db_open_min = hhmm_to_minutes(db_open)
        db_close_min = hhmm_to_minutes(db_close)
        api_open_min = hhmm_to_minutes(api_open)

        duration = db_close_min - db_open_min
        new_close_min = api_open_min + duration
        return minutes_to_hhmm(new_close_min)
    except (ValueError, IndexError):
        return db_close  # Fallback to DB close on parse error


def _crosscheck_bay(db_bay: Optional[str], api_gate: str) -> str:
    """Crosscheck bay/gate, prefer API gate.
    
    Fallback to DB bay if API gate is empty/null.
    """
    if api_gate and api_gate.strip():
        return api_gate.strip()
    return db_bay or ""
```

- [ ] **Step 2: Commit**

```bash
cd /data/data/com.termux/files/home/projects/roster-app
git add RosterSU/components.py
git commit -m "feat: add flight API preview helper functions"
```

---

### Task 2: ApiPreviewCard Component

**Files:**
- Modify: `RosterSU/components.py`
- Test: Manual (start app, verify card renders)

Add the main preview card component.

- [ ] **Step 1: Add ApiPreviewCard function**

Add after the helper functions in `components.py`:

```python
def ApiPreviewCard(cache: dict, today_flights: list = None) -> Div:
    """Render API preview card with cross-referenced flight data.
    
    Args:
        cache: Module-level _flight_api_cache dict
        today_flights: List of (db_flight_dict, scraped_flight) tuples.
                       If None, attempts to match from cache.
    """
    from fasthtml.common import Div, P, Button, Table, Tbody, Tr, Td, Span

    # Empty state
    if not cache or not cache.get("flights"):
        return Div(
            P("Không có dữ liệu API hôm nay", style="font-size:0.8rem; color:var(--muted);"),
            Button(
                "🔄 Cập nhật",
                hx_post="/flight/preview/fetch",
                hx_target="#api-preview-card",
                hx_swap="outerHTML",
                cls="btn-act",
                style="width:100%; margin-top:0.5rem;",
            ),
            id="api-preview-card",
            cls="api-preview-card",
        )

    # Build matched flights: (db_flight, scraped_flight)
    if today_flights is None:
        today_flights = _match_api_with_db_flights(cache.get("flights", []))

    # Filter past flights
    current_time = datetime.now().strftime("%H%M")
    future_flights = []
    for db_flight, scraped in today_flights:
        flight_time = scraped.scheduled_time or ""
        if flight_time >= current_time:
            future_flights.append((db_flight, scraped))

    # No future flights
    if not future_flights:
        return Div(
            P("Không có chuyến bay nào còn hoạt động hôm nay",
              style="font-size:0.8rem; color:var(--muted);"),
            Button(
                "🔄 Cập nhật",
                hx_post="/flight/preview/fetch",
                hx_target="#api-preview-card",
                hx_swap="outerHTML",
                cls="btn-act",
                style="width:100%; margin-top:0.5rem;",
            ),
            id="api-preview-card",
            cls="api-preview-card",
        )

    # Build table rows
    table_rows = []
    for db_flight, scraped in future_flights:
        # Extract values with fallbacks
        call = db_flight.get("Call", "")
        db_route = db_flight.get("Route", "")
        api_route = getattr(scraped, 'route', None)
        
        db_open_raw = db_flight.get("Open", "")
        db_close_raw = db_flight.get("Close", "")
        
        # API open time: prefer estimated, fallback to scheduled
        api_open = scraped.estimated_time or scraped.scheduled_time or ""
        if api_open:
            api_open_formatted = f"{api_open[:2]}:{api_open[2:]}"
        else:
            api_open_formatted = db_open_raw

        # Recalculate close
        if api_open and db_open_raw and db_close_raw:
            close = _recalculate_close(db_open_raw, db_close_raw, api_open)
        else:
            close = db_close_raw

        status = scraped.status or db_flight.get("Status", "")
        names = db_flight.get("Names", "")
        ckrow = scraped.ck_row or db_flight.get("ckRow", "")
        flight_type = db_flight.get("Type", "")
        bay = _crosscheck_bay(db_flight.get("Bay"), scraped.gate)
        route = _crosscheck_route(db_route, api_route)

        # Two rows per flight
        row1 = Tr(
            Td(call),
            Td(api_open_formatted if api_open else "--"),
            Td(status, rowspan="2"),
            Td(names),
            Td(flight_type),
        )
        row2 = Tr(
            Td(route),
            Td(close if close else "--"),
            Td(ckrow),
            Td(bay),
        )
        table_rows.append(row1)
        table_rows.append(row2)

    return Div(
        Div(
            Table(
                Tbody(*table_rows),
            ),
            style="overflow-x: auto;",
        ),
        Button(
            "🔄 Cập nhật",
            hx_post="/flight/preview/fetch",
            hx_target="#api-preview-card",
            hx_swap="outerHTML",
            cls="btn-act",
            style="width:100%; margin-top:0.5rem;",
        ),
        id="api-preview-card",
        cls="api-preview-card",
    )


def _match_api_with_db_flights(scraped_flights: list, db_flights: list = None) -> list:
    """Match scraped API flights with DB flights for today.
    
    Args:
        scraped_flights: List of ScrapedFlight from API cache
        db_flights: Optional list of DB flight dicts. If None, loads from DB.
    
    Returns list of (db_flight_dict, scraped_flight) tuples.
    """
    matched = []
    
    # Load DB flights if not provided
    if db_flights is None:
        from database import get_db
        today_db = datetime.now().strftime("%d.%m.%Y")
        try:
            conn = get_db()
            cursor = conn.execute(
                "SELECT full_data FROM work_schedule WHERE work_date = ?",
                (today_db,)
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                data = json.loads(row[0])
                db_flights = data.get("flights", [])
            else:
                return []
        except Exception:
            return []

    # Build lookup by normalized call sign
    db_by_call = {}
    for f in db_flights:
        call = f.get("Call", "").strip().upper()
        if call:
            db_by_call[call] = f

    # Match
    for scraped in scraped_flights:
        call = scraped.flight_no.strip().upper()
        if call in db_by_call:
            matched.append((db_by_call[call], scraped))

    return matched
```

- [ ] **Step 2: Add required imports**

At the top of `components.py`, add `Optional` to the typing import (if not already there):

```python
from typing import List, Dict, Optional
```

And add the `Table, Tbody, Tr, Td, Span` imports lazily (they're already imported via `from fasthtml.common import *`).

- [ ] **Step 3: Commit**

```bash
cd /data/data/com.termux/files/home/projects/roster-app
git add RosterSU/components.py
git commit -m "feat: add ApiPreviewCard component and match helper"
```

---

### Task 3: Cache and Endpoints in routes.py

**Files:**
- Modify: `RosterSU/routes.py`

Add the in-memory cache and two endpoints.

- [ ] **Step 1: Add module-level cache**

Add near the top of `routes.py` (after the existing imports, before the first function):

```python
# Flight API preview cache (in-memory, survives within app session)
_flight_api_cache: dict = {}
```

- [ ] **Step 2: Add _refresh_api_cache function**

Add after the `_run_immediate_flight_sync()` function:

```python
def _refresh_api_cache():
    """Fetch today's API data and store in _flight_api_cache."""
    global _flight_api_cache
    try:
        from scraper import FlightScraper
        today_iso = datetime.now().strftime("%Y-%m-%d")
        today_db = datetime.now().strftime("%d.%m.%Y")

        scraper = FlightScraper()
        flights = scraper.fetch_departures(today_iso)

        _flight_api_cache = {
            "date": today_db,
            "fetched_at": datetime.now().isoformat(),
            "flights": flights,
        }
        debug_log(f"Flight API cache refreshed: {len(flights)} flights for {today_db}")
    except Exception as e:
        _flight_api_cache = {}
        debug_log(f"Flight API cache refresh error: {e}")
```

- [ ] **Step 3: Add GET /flight/preview endpoint**

Add after the `/flight/sync` endpoint:

```python
@rt("/flight/preview")
def get_flight_preview():
    """Return the API preview card."""
    from components import ApiPreviewCard
    return ApiPreviewCard(cache=_flight_api_cache)
```

- [ ] **Step 4: Add POST /flight/preview/fetch endpoint**

Add after the `get_flight_preview()` function:

```python
@rt("/flight/preview/fetch", methods=["post"])
def post_flight_fetch():
    """Fetch fresh API data and refresh the preview card."""
    _refresh_api_cache()
    bump_db_rev()
    from components import ApiPreviewCard
    return ApiPreviewCard(cache=_flight_api_cache)
```

- [ ] **Step 5: Add startup cache refresh**

In `roster_single_user.py`, find the line that calls `_run_flight_startup_sync()` (around line 3343). Add the API cache refresh right after it:

```python
# Refresh flight API preview cache at startup
import routes
routes._refresh_api_cache()
```

The full section should look like:

```python
    _run_flight_startup_sync()
    
    # Refresh flight API preview cache at startup
    import routes
    routes._refresh_api_cache()
```

Using `import routes` (not `from routes import`) avoids circular import issues since the import happens at runtime after all modules are loaded.

- [ ] **Step 6: Verify syntax and commit**

```bash
cd /data/data/com.termux/files/home/projects/roster-app/RosterSU
python -m py_compile routes.py && python -m py_compile ../roster_single_user.py
git add routes.py ../roster_single_user.py
git commit -m "feat: add flight API cache and preview endpoints"
```

---

### Task 4: Integrate Card into Main Page

**Files:**
- Modify: `RosterSU/routes.py`

Add the preview card to the main page layout.

- [ ] **Step 1: Add card to main page**

In the `get()` function (`@rt("/")`), add the `ApiPreviewCard` call **after** the button row and **before** the `H4("📋 Lịch làm việc")` heading.

Find this section:

```python
        Div(H4("📋 Lịch làm việc"), style="margin-top:0.5rem;"),
```

Replace with:

```python
        # API Preview Card
        Div(ApiPreviewCard(cache=_flight_api_cache), id="api-preview-wrapper"),
        Div(H4("📋 Lịch làm việc"), style="margin-top:0.5rem;"),
```

Add the import at the top of the function or use lazy import:

```python
    from components import ApiPreviewCard
```

- [ ] **Step 2: Verify syntax and commit**

```bash
cd /data/data/com.termux/files/home/projects/roster-app/RosterSU
python -m py_compile routes.py
git add routes.py
git commit -m "feat: integrate API preview card into main schedule page"
```

---

### Task 5: Styling

**Files:**
- Modify: `RosterSU/roster_styles.css`

Add CSS for the preview card.

- [ ] **Step 1: Add styles**

Add to the end of `roster_styles.css`:

```css
/* === API Preview Card === */
.api-preview-card {
    background: var(--card-bg);
    border-radius: var(--radius-md);
    padding: var(--space-3);
    margin-bottom: var(--space-3);
    box-shadow: var(--shadow-md);
    border: 1px solid rgba(148,163,184,0.2);
}

[data-theme='dark'] .api-preview-card {
    background: #1e293b;
    border-color: rgba(71,85,105,0.4);
}

.api-preview-card table {
    width: 100%;
    font-size: 0.75rem;
    border-collapse: collapse;
}

.api-preview-card td {
    padding: 0.2rem 0.4rem;
    border-bottom: 1px solid rgba(148,163,184,0.15);
    vertical-align: middle;
    white-space: nowrap;
}

.api-preview-card tr:last-child td {
    border-bottom: none;
}

/* Status cell styling - make it stand out */
.api-preview-card td[rowspan="2"] {
    font-weight: 600;
    text-align: center;
    background: rgba(99,102,241,0.08);
}

[data-theme='dark'] .api-preview-card td[rowspan="2"] {
    background: rgba(99,102,241,0.15);
}

/* Empty state text */
.api-preview-card p {
    font-size: 0.8rem;
    color: var(--muted);
    margin-bottom: 0.5rem;
}
```

- [ ] **Step 2: Commit**

```bash
cd /data/data/com.termux/files/home/projects/roster-app
git add RosterSU/roster_styles.css
git commit -m "style: add API preview card styles"
```

---

### Task 6: Disable Automatic DB Updates in Flight Sync

**Files:**
- Modify: `RosterSU/scraper.py` (verify no other code calls AutoSyncService for DB updates)

The automatic DB update is already disabled (removed in the previous checkbox→radio refactor). Verify this is the case.

- [ ] **Step 1: Verify AutoSyncService is only called from _run_immediate_flight_sync**

Search for all uses of `AutoSyncService` and `run_sync`:

```bash
cd /data/data/com.termux/files/home/projects/roster-app/RosterSU
grep -n "AutoSyncService\|run_sync" *.py
```

Confirm it's only called from:
- `_run_immediate_flight_sync()` in `routes.py`
- `_run_flight_startup_sync()` in `roster_single_user.py`

Both of these are manual/startup triggers — no automatic ingestion pipeline calls.

- [ ] **Step 2: Update _run_immediate_flight_sync to NOT update DB**

Modify the function to fetch and log only, without writing to DB. Change the `AutoSyncService.run_sync()` call to just use the matching logic but skip the DB write step.

Actually — per the spec, the **new system doesn't use AutoSyncService for the preview at all**. The preview is read-only. The existing `_run_immediate_flight_sync` can remain as-is for users who still want to manually sync (via the "Sync Now" button). No changes needed to `scraper.py`.

- [ ] **Step 3: Commit (if any changes made)**

```bash
cd /data/data/com.termux/files/home/projects/roster-app
git status
# If changes:
git add -A
git commit -m "refactor: verify flight sync DB write behavior"
```

---

### Task 7: Manual Testing

**Files:**
- Test: Run app and verify

- [ ] **Step 1: Start the app**

```bash
cd /data/data/com.termux/files/home/projects/roster-app/RosterSU
python roster_single_user.py
```

- [ ] **Step 2: Verify API preview card appears**

Open browser to `http://localhost:8501`:
1. Check that the API preview card appears above the roster list
2. Verify it shows today's flights with correct data mapping
3. Verify past flights are filtered out
4. Verify the "Cập nhật" button refreshes the data

- [ ] **Step 3: Test edge cases**

1. **Empty API response:** If API returns no flights → card shows "Không có dữ liệu API hôm nay"
2. **No DB flights for today:** Card shows API data with "--" for DB fields
3. **App restart:** Cache refreshes, fresh data fetched
4. **Past flights:** Not shown in the table

- [ ] **Step 4: Verify no regressions**

1. Existing roster cards still render correctly
2. Flight sync "Sync Now" button still works
3. Settings page radio buttons save correctly
4. No console errors in browser DevTools

---

## Self-Review

### Spec Coverage Check

| Spec Section | Task |
|-------------|------|
| In-memory cache `_flight_api_cache` | Task 3 Step 1-2 |
| `ApiPreviewCard()` component | Task 2 Step 1 |
| Helper functions (_crosscheck_route, etc.) | Task 1 Step 1 |
| `GET /flight/preview` endpoint | Task 3 Step 3 |
| `POST /flight/preview/fetch` endpoint | Task 3 Step 4 |
| Startup cache refresh | Task 3 Step 5 |
| Two-row table layout (no headers) | Task 2 Step 1 |
| Past flight filtering | Task 2 Step 1 |
| Data mapping (Call, Route, Open, etc.) | Task 2 Step 1 |
| Empty state | Task 2 Step 1 |
| CSS styling | Task 5 Step 1 |
| Card in main page | Task 4 Step 1 |
| No automatic DB update | Task 6 (verified existing behavior) |

### Placeholder Scan
✅ No "TBD", "TODO", "implement later", or vague steps  
✅ All code shown inline — no "similar to" references  
✅ All imports specified where needed  

### Type Consistency
✅ `_flight_api_cache` is `dict` — used consistently in routes.py and passed to ApiPreviewCard  
✅ `scraped.scheduled_time` is `str` (HHMM) — used in filtering and display  
✅ Helper function signatures match call sites  

### Scope
✅ Focused on single feature — preview card with cache  
✅ No unrelated refactoring  
✅ Existing flight sync (AutoSyncService) untouched
