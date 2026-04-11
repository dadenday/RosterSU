# Flight API Preview Roster Card — Design Spec

## Overview

Replace the flight sync's automatic DB update with a visual preview card that shows today's flights cross-referenced between the DB and the Sun Airport API. The card appears in the schedule tab above the roster list, displays a compact two-row table per flight, and includes a manual "Cập nhật" (Update) button.

## Architecture

### Components
1. **`_flight_api_cache`** (module-level dict in `routes.py`) — in-memory cache for today's API data
2. **`ApiPreviewCard()`** function in `components.py` — renders the preview table
3. **`GET /flight/preview`** endpoint — serves the card via HTMX
4. **`POST /flight/preview/fetch`** endpoint — fetches fresh API data and triggers refresh

### Data Flow

**On App Startup:**
1. `_refresh_api_cache()` called after DB initialization (in `roster_single_user.py`)
2. Fetches today's departures from Sun Airport API
3. Stores result in `_flight_api_cache` dict
4. Bumps `db_rev` to trigger HTMX card render (if data fetched successfully)

**On Page Load:**
1. Main page (`@rt("/")`) calls `ApiPreviewCard()` inline
2. Card reads from `_flight_api_cache`
3. Filters out past flights (scheduled_time < current time)
4. Cross-references each flight with DB's `work_schedule` for today
5. Renders table rows

**On "Cập nhật" Button Click:**
1. POST to `/flight/preview/fetch`
2. Re-fetches API → updates `_flight_api_cache`
3. Bumps `db_rev` → card auto-refreshes via HTMX

### Cache Structure

```python
_flight_api_cache = {
    "date": "11.04.2026",       # DD.MM.YYYY
    "fetched_at": "2026-04-11T08:00:00",
    "flights": [ScrapedFlight, ...]  # list of dataclass instances
}
```

Cache is invalidated when:
- App restarts (fresh fetch)
- User clicks "Cập nhật" button
- Date changes (cache date != today's date)

## API Preview Card Table

### Layout

No header rows. Each flight renders as **two table rows**:

```html
<tr>
  <td>{Call from DB}</td>
  <td>{Open from API}</td>
  <td rowspan="2">{Status from API}</td>
  <td>{Names from DB}</td>
  <td>{Type from DB}</td>
</tr>
<tr>
  <td>{Route crosscheck}</td>
  <td>{Close recalculated}</td>
  <td>{CkRow from API}</td>
  <td>{Bay crosscheck}</td>
</tr>
```

### Data Mapping

| Cell | Source | Logic |
|------|--------|-------|
| **Call** | DB | `db_flight["Call"]` |
| **Route** | Crosscheck | Extract destination from route (`PQC-HAN` → `HAN`). Prefer API route's destination if available, fallback to DB. |
| **Open** | API | `scraped.estimated_time` or `scraped.scheduled_time` (HHMM → `HH:MM`). Fallback to DB open if API null. |
| **Close** | Calculated | `db_close - db_open = duration` → `api_open + duration = new_close`. Fallback to DB close if API null. |
| **Status** | API | `scraped.status`. Fallback to DB status if API null. |
| **Names** | DB | `db_flight["Names"]` |
| **CkRow** | API | `scraped.ck_row`. Fallback to DB ckrow if API null. |
| **Type** | DB | `db_flight["Type"]` |
| **Bay** | Crosscheck | Prefer `scraped.gate` (API), fallback to DB bay. |

### Past Flight Filtering

On every render:
```python
current_time = datetime.now().strftime("%H%M")  # e.g., "1430"
flight_time = scraped.scheduled_time  # e.g., "0830"
if flight_time >= current_time:  # Include future flights only
    render_flight()
```

### Empty State

If `_flight_api_cache` is empty or has no matching flights:
- Show "Không có chuyến bay nào trong hôm nay" (No flights today)
- Still show the "Cập nhật" button

## Endpoints

### GET /flight/preview

Returns the `ApiPreviewCard` component rendered as HTML. Used by HTMX to load/refresh the card.

```python
@rt("/flight/preview")
def get_flight_preview():
    return ApiPreviewCard(cache=_flight_api_cache)
```

### POST /flight/preview/fetch

Fetches fresh API data, updates cache, triggers UI refresh.

```python
@rt("/flight/preview/fetch", methods=["post"])
def post_flight_fetch():
    _refresh_api_cache()
    bump_db_rev()
    return ApiPreviewCard(cache=_flight_api_cache)
```

## File Changes

### `routes.py`
- Add `_flight_api_cache = None` module-level variable
- Add `_refresh_api_cache()` function
- Add `get_flight_preview()` endpoint
- Add `post_flight_fetch()` endpoint
- Modify `get()` to include `ApiPreviewCard()` above roster list

### `components.py`
- Add `ApiPreviewCard(cache)` function
- Add helper: `_crosscheck_route(db_route, api_route)`
- Add helper: `_recalculate_close(db_open, db_close, api_open)`
- Add helper: `_crosscheck_bay(db_bay, api_bay)`
- Add CSS class `api-preview-card` styling

### `roster_styles.css`
- Add styles for `.api-preview-card`
- Add styles for `.api-preview-card table`
- Add styles for `.api-preview-card td`

### `scraper.py`
- No changes (existing `ScrapedFlight`, `FlightScraper.fetch_departures()` reused)

## Error Handling

- **API timeout/failure**: Log error, show empty card with "Lỗi kết nối API" message
- **No DB flights for today**: Show API-only data with "⚠️ Không có lịch DB hôm nay"
- **Cache miss**: Fetch API on demand, don't block render
- **Malformed data**: Skip individual flights, don't crash

## Testing Strategy

1. **Unit**: Test `_crosscheck_route()`, `_recalculate_close()`, `_crosscheck_bay()` with various null/missing combinations
2. **Integration**: Mock `FlightScraper.fetch_departures()` → verify cache population
3. **Manual**: Start app → verify card shows → click "Cập nhật" → verify refresh

## Open Questions

_None — all decisions validated with user._
