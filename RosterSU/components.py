"""
UI components for RosterMaster.

Extracted from roster_single_user.py for maintainability.
Provides FastHTML components for roster display.
"""

import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from fasthtml.common import *

# Import patterns from config at module level (no circular dependency risk)
from config import RE_ZONE_PATTERN, RE_MULTIPLE_SPACES


# Lazily loaded dependencies (set during initialization)
_get_aircraft_config = None
_count_history = None
_load_history = None
_aircraft_config_cache = None
_PAGE_SIZE = 50


def _init_components(
    get_aircraft_config_fn, count_history_fn, load_history_fn, page_size=50
):
    """Initialize components module with dependencies from main module."""
    global _get_aircraft_config, _count_history, _load_history, _PAGE_SIZE, _aircraft_config_cache
    _get_aircraft_config = get_aircraft_config_fn
    _count_history = count_history_fn
    _load_history = load_history_fn
    _PAGE_SIZE = page_size
    # Cache aircraft config at init time — it never changes at runtime
    if _get_aircraft_config:
        _aircraft_config_cache = _get_aircraft_config()
    else:
        _aircraft_config_cache = None


def invalidate_aircraft_config_cache():
    """Invalidate the cached aircraft config (called after settings save)."""
    global _aircraft_config_cache
    if _get_aircraft_config:
        _aircraft_config_cache = _get_aircraft_config()


def format_date_vn(date_str):
    """Format date string to Vietnamese format (T2 10.02.26)."""
    try:
        dt = datetime.strptime(date_str, "%d.%m.%Y")
        days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
        return f"{days[dt.weekday()]} {dt.strftime('%d.%m.%y')}"
    except Exception:
        return date_str


def format_shift_display(date_str, shift_raw):
    """Format shift display with zone info."""
    zone = ""
    time_part = shift_raw or "--"
    match = RE_ZONE_PATTERN.search(time_part)
    if match:
        time_part = match.group(1).strip()
        zone = match.group(2).strip().capitalize()
    formatted_date = format_date_vn(date_str)
    if time_part in ("OFF", "HỌC"):
        return f"{formatted_date} | {time_part}"
    display = f"{formatted_date} | {time_part}"
    if zone:
        display += f" | {zone}"
    return display


def shift_color(shift):
    """Return color class based on shift value."""
    if shift == "OFF":
        return "negative"
    if shift and "HỌC" in shift:
        return "info"
    if shift and shift != "--":
        return "positive"
    return "grey-7"


def shift_text_class(shift):
    """Return text color class based on shift value."""
    if shift == "OFF":
        return "text-red-600"
    if shift and "HỌC" in shift:
        return "text-blue-600"
    if shift and shift != "--":
        return "text-green-700"
    return "text-grey-7"


def build_copy_text(date_str, shift_info, flights):
    """Build text for clipboard copy."""
    display = format_shift_display(date_str, shift_info)
    lines = [display]
    for f in flights:
        row = f"✈ {f.get('Type', '')} {f.get('Call', '')} {f.get('Route', '')} {f.get('Open', '')} {f.get('Close', '')} {f.get('Bay', '')} {f.get('Names', '')}"
        lines.append(RE_MULTIPLE_SPACES.sub(" ", row).strip())
    return "\n".join(lines)


def parse_time_to_minutes(time_str):
    """Parse time string like '08h30' or '08:30' to minutes from midnight."""
    if not time_str:
        return None
    match = re.search(r"(\d{1,2})[h:.](\d{2})", str(time_str))
    if not match:
        return None
    try:
        return int(match.group(1)) * 60 + int(match.group(2))
    except ValueError:
        return None


def sort_flights_by_open_time(flights, shift_info=None):
    """Sort flights by open time in ascending order, handling overnight shifts.

    For overnight shifts (e.g., 18h00 - 02h00), flights after midnight (00h00-06h00)
    are sorted at the END, not the beginning.
    """
    if not flights:
        return flights

    # Detect if this is an overnight shift
    is_overnight_shift = False
    if shift_info:
        shift_match = re.search(
            r"(\d{1,2})[h:.](\d{2})\s*[-–]\s*(\d{1,2})[h:.](\d{2})", str(shift_info)
        )
        if shift_match:
            shift_start = int(shift_match.group(1)) * 60 + int(shift_match.group(2))
            shift_end = int(shift_match.group(3)) * 60 + int(shift_match.group(4))
            is_overnight_shift = shift_end < shift_start

    def get_sort_key(f):
        open_time = f.get("Open", "")
        mins = parse_time_to_minutes(open_time)

        if mins is None:
            return (2, 9999)  # Put unparseable at very end

        if is_overnight_shift and mins < 6 * 60:  # Before 06h00
            return (1, mins)  # Group 1: overnight flights
        else:
            return (0, mins)  # Group 0: same-day flights

    return sorted(flights, key=get_sort_key)


def is_flight_card_active(date_str, flights):
    """Check if a flight card should be auto-expanded based on current time.

    A card is active if the LAST flight's close time is still within or after current time.
    This handles overnight flights (e.g., 23h30 - 02h30).
    """
    if not flights:
        return False

    now = datetime.now()
    current_mins = now.hour * 60 + now.minute

    try:
        card_date = datetime.strptime(date_str, "%d.%m.%Y")
    except (ValueError, TypeError):
        return False

    today = now.date()
    card_day = card_date.date()

    last_flight = flights[-1]
    close_time = last_flight.get("Close", "")
    close_mins = parse_time_to_minutes(close_time)

    if close_mins is None:
        return False

    open_time = last_flight.get("Open", "")
    open_mins = parse_time_to_minutes(open_time)
    is_overnight = open_mins is not None and close_mins < open_mins

    if card_day == today:
        if is_overnight:
            return current_mins < 30 * 60  # Before 00:30
        else:
            return current_mins < close_mins + 15
    else:
        yesterday = today - timedelta(days=1)
        if card_day == yesterday and is_overnight:
            return 0 <= current_mins <= 150  # 00:00 - 02:30

    return False


def RosterCard(r, is_first=False, parsed_data=None):
    """Render a roster card with optional auto-expand for first card.

    Args:
        r: Row dict with 'work_date' and 'full_data' keys
        is_first: If True, auto-expand the card
        parsed_data: Optional pre-parsed data dict (avoids double JSON parse)
    """
    date_str = r["work_date"]
    if parsed_data is not None:
        data = parsed_data
    else:
        data = json.loads(r["full_data"])
    shift_info = data.get("shift", "--")
    flights = data.get("flights", [])

    # Sort flights by open time ascending, passing shift_info for overnight detection
    flights = sort_flights_by_open_time(flights, shift_info=shift_info)

    vn_date = format_date_vn(date_str)
    s_info = str(shift_info or "")

    # Determine card style
    sc = "rc-on"
    if s_info == "OFF":
        sc = "rc-off"
    elif "HỌC" in s_info:
        sc = "rc-edu"
    elif s_info == "--":
        sc = "rc-nil"

    shift_time = s_info
    zone = ""
    zone_match = RE_ZONE_PATTERN.search(s_info)
    if zone_match:
        shift_time = zone_match.group(1).strip()
        zone = zone_match.group(2).strip()

    date_col = Div(P(vn_date, cls="rc-date"), cls="rc-date-col")

    shift_col_items = [P(shift_time or "--", cls="rc-shift")]
    if zone:
        shift_col_items.append(P(zone, cls="rc-zone"))
    shift_col = Div(*shift_col_items, cls="rc-shift-col")

    flight_badge = ""
    if flights:
        count = len(flights)
        flight_badge = Span(f"{count} chuyến", cls="rc-badge")

    card = Div(
        Input(
            type="checkbox",
            name="selected_dates",
            value=date_str,
            onclick="event.stopPropagation()",
        ),
        date_col,
        shift_col,
        flight_badge,
        cls=f"rc {sc}",
    )

    def get_flight_type_class(flight_type):
        """Return CSS class based on aircraft type."""
        if not flight_type:
            return ""
        ft_upper = str(flight_type).upper().strip()

        config = _aircraft_config_cache
        if not config:
            return ""

        for aircraft_type in config.get("airbus", []):
            if ft_upper.startswith(aircraft_type.upper()):
                return "flight-airbus"

        for aircraft_type in config.get("boeing", []):
            if ft_upper.startswith(aircraft_type.upper()):
                return "flight-boeing"

        for aircraft_type in config.get("other", []):
            if ft_upper.startswith(aircraft_type.upper()):
                return "flight-other"

        return ""

    if flights:
        return Details(
            Summary(card),
            Div(
                Table(
                    Thead(
                        Tr(
                            Th("Type"),
                            Th("Call"),
                            Th("Route"),
                            Th("Open"),
                            Th("Close"),
                            Th("Bay"),
                            Th("Names"),
                        )
                    ),
                    Tbody(
                        *[
                            Tr(
                                Td(Span(f.get("Type", ""), cls="td-span-type")),
                                Td(Span(f.get("Call", ""), cls="td-span-call")),
                                Td(f.get("Route", "")),
                                Td(Span(f.get("Open", ""), cls="td-span-time")),
                                Td(Span(f.get("Close", ""), cls="td-span-time")),
                                Td(Span(f.get("Bay", ""), cls="td-span-bay")),
                                Td(Span(f.get("Names", ""), cls="td-span-names")),
                                cls=get_flight_type_class(f.get("Type", "")),
                            )
                            for f in flights
                        ]
                    ),
                ),
                cls="fd",
            ),
            cls="rd",
            open=is_first,
        )
    return Div(card, cls="rd")


def RosterList(filter_month=None, page=1, count_history_fn=None, load_history_fn=None):
    """Render roster cards with pagination support when 'All' is selected.

    Args:
        filter_month: Month filter (YYYY-MM format) or "All"
        page: Page number for pagination
        count_history_fn: Optional function to count history
        load_history_fn: Optional function to load history
    """
    # Use provided functions or fall back to module-level
    count_fn = count_history_fn or _count_history
    load_fn = load_history_fn or _load_history

    if count_fn is None or load_fn is None:
        raise RuntimeError("Components not initialized. Call _init_components() first.")

    is_paginated = filter_month is None or filter_month == "All"
    page = max(1, int(page)) if page else 1

    if is_paginated:
        total_count = count_fn()
        total_pages = max(1, (total_count + _PAGE_SIZE - 1) // _PAGE_SIZE)
        page = min(page, total_pages)
        offset = (page - 1) * _PAGE_SIZE
        rows = load_fn(limit=_PAGE_SIZE, filter_month=filter_month, offset=offset)
    else:
        total_count = count_fn(filter_month)
        total_pages = 1
        rows = load_fn(filter_month=filter_month)

    # Import FastHTML components lazily
    from fasthtml.common import Div, P, Button, Span, Option, Select, H4, Form, Input, A

    htmx = dict(
        id="roster-list",
        hx_get="/list",
        hx_trigger="db-changed from:body",
        hx_include="[name='filter_month'], [name='page']",
    )

    if not rows:
        return Div(
            P("📭 Chưa có dữ liệu lịch làm việc"),
            P("Nhấn 'Quét Zalo' để tìm file hoặc 'Tải lên' để chọn file thủ công."),
            cls="empty",
            **htmx,
        )

    cards = []
    for r in rows:
        data = json.loads(r["full_data"])
        flights = data.get("flights", [])
        shift_info = data.get("shift")
        sorted_flights = sort_flights_by_open_time(flights, shift_info=shift_info)
        should_expand = is_flight_card_active(r["work_date"], sorted_flights)
        cards.append(
            RosterCard(
                r, is_first=should_expand, parsed_data=data
            )
        )

    if is_paginated and total_pages > 1:
        prev_disabled = page <= 1
        next_disabled = page >= total_pages

        pagination = Div(
            Button(
                "‹",
                hx_get=f"/list?filter_month=All&page={page - 1}"
                if not prev_disabled
                else None,
                hx_target="#roster-list",
                disabled=prev_disabled,
                cls="btn-paginate pagination-btn",
            ),
            Span(f" {page}/{total_pages} ", cls="pagination-info"),
            Button(
                "›",
                hx_get=f"/list?filter_month=All&page={page + 1}"
                if not next_disabled
                else None,
                hx_target="#roster-list",
                disabled=next_disabled,
                cls="btn-paginate pagination-btn",
            ),
            cls="pagination",
        )
        return Div(pagination, *cards, **htmx)

    return Div(*cards, **htmx)


# ============================================================================
# API Preview Card Helpers
# ============================================================================

def _crosscheck_route(db_route: Optional[str], api_route: Optional[str]) -> str:
    """Extract destination from route, prefer API if available.

    PQC-HAN -> HAN (destination only)
    """
    # Prefer API route
    route = api_route or db_route or ""
    if not route:
        return ""
    # Extract destination (second part of PQC-HAN)
    if "-" in route:
        return route.split("-")[-1].strip()
    return route.strip()


def _extract_checkin_time_from_notes(notes_en: str, notes_vn: str) -> Optional[str]:
    """Extract check-in time from notesEn or notesVn.

    Only extracts time from messages like "CHECK-IN 14:25" or "LÀM THỦ TỤC LÚC 14:25".
    Returns None for live status messages like "ĐANG LÀM THỦ TỤC", "ĐÃ CẤT CÁNH", etc.

    Args:
        notes_en: English notes (e.g., "CHECK-IN 14:25" or "DEPARTED")
        notes_vn: Vietnamese notes (e.g., "LÀM THỦ TỤC LÚC 14:25" or "ĐÃ CẤT CÁNH")

    Returns:
        Time in HHMM format (e.g., "1425") or None if not found.
    """
    import re

    # Try notes_vn first (has "LÚC" marker), then notes_en
    notes = notes_vn or notes_en or ""
    if not notes:
        return None

    # Only extract time if it contains "LÚC" (Vietnamese) or follows "CHECK-IN HH:MM" pattern
    # This filters out live status like "ĐANG LÀM THỦ TỤC", "ĐÃ CẤT CÁNH", etc.
    if "LÚC" in notes.upper():
        # Vietnamese: "LÀM THỦ TỤC LÚC 14:25"
        match = re.search(r'LÚC\s+(\d{1,2})[:h](\d{2})', notes, re.IGNORECASE)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            return f"{hours:02d}{minutes:02d}"
    elif re.match(r'CHECK-IN\s+\d{1,2}[:h]\d{2}', notes, re.IGNORECASE):
        # English: "CHECK-IN 14:25"
        match = re.search(r'(\d{1,2})[:h](\d{2})', notes)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            return f"{hours:02d}{minutes:02d}"

    return None


def _calculate_delayed_checkin(
    db_open: str,
    scheduled_time: str,
    estimated_time: str,
) -> Optional[str]:
    """Calculate delayed check-in open time based on departure delay.

    When the API doesn't provide an explicit check-in time in notesEn/notesVn,
    we calculate it by applying the same delay offset to the original check-in time.

    Formula:
        delay = estimatedTime - scheduledTime
        new_checkin = db_open + delay

    Args:
        db_open: Original check-in open time from DB (e.g., "09:10" or "09h10")
        scheduled_time: Original departure time from API (e.g., "1210")
        estimated_time: Updated departure time from API (e.g., "1350")

    Returns:
        New check-in open time in HHMM format, or None if calculation fails.
    """
    if not scheduled_time or not estimated_time or not db_open:
        return None

    # Parse times to minutes
    def to_minutes(t: str) -> Optional[int]:
        t = t.replace("h", "").replace(":", "").strip()
        if len(t) < 3:
            return None
        t = t.zfill(4)
        try:
            return int(t[:2]) * 60 + int(t[2:4])
        except ValueError:
            return None

    db_open_min = to_minutes(db_open)
    sched_min = to_minutes(scheduled_time)
    estim_min = to_minutes(estimated_time)

    if db_open_min is None or sched_min is None or estim_min is None:
        return None

    # Calculate delay
    delay = estim_min - sched_min
    if delay <= 0:
        return None  # No delay

    # Apply delay to check-in open time
    new_open_min = db_open_min + delay
    new_open_min = new_open_min % (24 * 60)  # Handle day wrap

    return f"{new_open_min // 60:02d}{new_open_min % 60:02d}"


def _recalculate_close(db_open: str, db_close: str, api_open: str) -> str:
    """Recalculate close time preserving flight duration.

    duration = db_close - db_open
    new_close = api_open + duration
    API open time is in HHMM format (e.g. "0830"), DB times in HH:MM or HHhMM.
    Returns empty string on parse error (caller should handle).
    """
    # Normalize API time from HHMM to HH:MM format
    if api_open and len(api_open) == 4 and api_open.isdigit():
        api_open = f"{api_open[:2]}:{api_open[2:]}"

    db_open_min = parse_time_to_minutes(db_open)
    db_close_min = parse_time_to_minutes(db_close)
    api_open_min = parse_time_to_minutes(api_open)

    if db_open_min is None or db_close_min is None or api_open_min is None:
        return ""

    def minutes_to_hhmm(m: int) -> str:
        m = m % 1440  # Handle day wrap
        return f"{m // 60:02d}:{m % 60:02d}"

    duration = db_close_min - db_open_min
    new_close_min = api_open_min + duration
    return minutes_to_hhmm(new_close_min)


def _crosscheck_bay(db_bay: Optional[str], api_gate: str) -> str:
    """Crosscheck bay/gate, prefer API gate.

    Fallback to DB bay if API gate is empty/null.
    """
    if api_gate and api_gate.strip():
        return api_gate.strip()
    return db_bay or ""


def _load_db_flights_for_date(date_db: str) -> list:
    """Load flights from DB for a specific date. Returns empty list on error."""
    try:
        from database import get_db

        conn = get_db()
        cursor = conn.execute(
            "SELECT full_data FROM work_schedule WHERE work_date = ?",
            (date_db,),
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            data = json.loads(row[0])
            return data.get("flights", [])
        return []
    except Exception as e:
        import logging

        logging.warning(f"Failed to load DB flights for {date_db}: {e}")
        return []


def _compact_status_lines(status_text: str) -> Div:
    """Break status text into compact lines for the rowspan=2 cell.

    Splits text to fit within 2 table rows while keeping it readable.
    Examples:
        "LÀM THỦ TỤC LÚC 14:25" → "LÀM THỦ<br>TỤC LÚC<br>14:25"
        "ĐANG LÀM THỦ TỤC" → "ĐANG LÀM<br>THỦ TỤC"
        "CHECK-IN 14:25" → "CHECK-IN<br>14:25"

    Args:
        status_text: Raw status string

    Returns:
        Div with <br>-separated content for HTML rendering
    """
    if not status_text:
        return Div("--", style="opacity:0.4;")

    # Normalize whitespace
    text = status_text.strip()

    # If already short (fits in 2 rows), keep as-is
    if len(text) <= 15:
        return Div(text)

    # Split "LÀM THỦ TỤC LÚC HH:MM" pattern
    import re
    match = re.match(r'(LÀM THỦ TỤC)\s+LÚC\s+(\d{1,2}[:h]\d{2})', text, re.IGNORECASE)
    if match:
        action = match.group(1)  # "LÀM THỦ TỤC"
        time_val = match.group(2)
        # Split into 3 compact lines
        words = action.split()
        if len(words) >= 2:
            line1 = words[0]  # "LÀM"
            line2 = " ".join(words[1:]) + " LÚC"  # "THỦ TỤC LÚC"
            line3 = time_val  # "14:25"
            return Div(
                Span(line1),
                Br(),
                Span(line2),
                Br(),
                Span(line3, style="font-weight:800;"),
            )

    # Split "CHECK-IN HH:MM" pattern
    match = re.match(r'CHECK-IN\s+(\d{1,2}[:h]\d{2})', text, re.IGNORECASE)
    if match:
        return Div(
            Span("CHECK-IN"),
            Br(),
            Span(match.group(1), style="font-weight:800;"),
        )

    # Generic fallback: split into chunks of ~12 chars
    if len(text) > 15:
        chunks = []
        for i in range(0, len(text), 12):
            chunk = text[i:i+12]
            # Try to break at word boundary
            if i + 12 < len(text):
                space_pos = chunk.rfind(' ')
                if space_pos > 4:
                    chunk = chunk[:space_pos]
            chunks.append(chunk)
        elements = []
        for i, chunk in enumerate(chunks):
            if i > 0:
                elements.append(Br())
            elements.append(Span(chunk))
        return Div(*elements)

    return Div(text)


def ApiPreviewCard(cache: dict, days: int = 3) -> Div:
    """Render API preview card with cross-referenced flight data for multiple days.

    Args:
        cache: Module-level _flight_api_cache dict with "dates" key.
               Flights can be:
               - list[ScrapedFlight] (original format)
               - list[tuple[ScrapedFlight, cached_data_or_None]] (cache-aware format)
        days: Number of days to show (default 3: today + 2 future)
    """
    dates_data = cache.get("dates", {})

    if not dates_data:
        # Complete empty state
        return Div(
            P("Không có dữ liệu", style="font-size:0.8rem; color:var(--muted);"),
            _api_preview_refresh_button(),
            id="api-preview-card",
            cls="api-preview-card",
        )

    # Render each date section - ONLY show dates with actual matched flights
    date_sections = []
    current_time = datetime.now().strftime("%H%M")

    for i in range(days):
        date_obj = datetime.now() + timedelta(days=i)
        date_db = date_obj.strftime("%d.%m.%Y")
        date_display = date_obj.strftime("%A %d/%m")  # e.g., "Saturday 11/04"

        if date_db not in dates_data:
            continue

        day_data = dates_data[date_db]

        # Skip errors
        if day_data.get("error"):
            continue

        # Skip if no API flights
        if not day_data.get("flights"):
            continue

        # Match with DB
        db_flights = _load_db_flights_for_date(date_db)

        # Skip if no DB schedule
        if not db_flights:
            continue

        # Build matched flights
        db_by_call = {}
        for f in db_flights:
            call = f.get("Call", "").strip().upper()
            if call:
                db_by_call[call] = f

        matched = []
        flights_data = day_data["flights"]

        for flight_entry in flights_data:
            # Handle new tuple format: (ScrapedFlight, cached_data_or_None)
            if isinstance(flight_entry, tuple) and len(flight_entry) == 2:
                scraped, cached = flight_entry
            else:
                # Original format: just ScrapedFlight
                scraped = flight_entry
                cached = None

            call = scraped.flight_no.strip().upper()
            if call in db_by_call:
                matched.append((db_by_call[call], scraped, cached))

        # Filter past flights (only for today)
        # IMPORTANT: Use DEPARTURE TIME (scheduled_time), NOT check-in open time!
        # A flight with check-in at 09:10 and departure at 12:10 should NOT be
        # filtered out at 10:00 just because check-in time has passed.
        if i == 0:  # Today - filter past
            future_flights = []
            for db_flight, scraped, cached in matched:
                # Always use scheduled departure time for filtering
                flight_time = scraped.scheduled_time or ""
                if not flight_time:
                    continue
                if flight_time >= current_time:
                    future_flights.append((db_flight, scraped, cached))
            matched = future_flights
        # Future days - show all flights

        # Skip if no matched flights
        if not matched:
            continue

        # Build table rows
        table_rows = []
        for db_flight, scraped, cached in matched:
            call = db_flight.get("Call", "")
            db_route = db_flight.get("Route", "")
            api_route = getattr(scraped, "route", None)

            db_open_raw = db_flight.get("Open", "")
            db_close_raw = db_flight.get("Close", "")

            # Get notes from scraped or cached data
            notes_en = getattr(scraped, "notes_en", "") or (cached.get("notes_en", "") if cached else "")
            notes_vn = getattr(scraped, "notes_vn", "") or (cached.get("notes_vn", "") if cached else "")

            # === ENHANCED CHECK-IN TIME EXTRACTION ===
            # Priority 1: Extract from notesEn/notesVn (explicit time like "CHECK-IN 14:25")
            # Priority 2: Calculate from delay if departure is delayed
            # Priority 3: Use cached status_time
            # Priority 4: Fallback to DB open time

            notes_checkin_time = _extract_checkin_time_from_notes(notes_en, notes_vn)

            api_open = ""
            is_from_cache = False
            is_calculated = False

            if notes_checkin_time:
                # Priority 1: Explicit check-in time from notes
                api_open = notes_checkin_time
            elif scraped.scheduled_time and scraped.estimated_time:
                # Priority 2: Calculate from delay offset
                calculated_open = _calculate_delayed_checkin(
                    db_open_raw,
                    scraped.scheduled_time,
                    scraped.estimated_time,
                )
                if calculated_open:
                    api_open = calculated_open
                    is_calculated = True

            # Priority 3: Fallback to cached status time
            if not api_open and cached and cached.get("status_time"):
                api_open = cached["status_time"]
                is_from_cache = True

            # Priority 4: Use DB open time as-is
            if api_open:
                api_open_z = api_open.zfill(4)
                api_open_formatted = f"{api_open_z[:2]}:{api_open_z[2:]}"
            else:
                api_open_formatted = db_open_raw

            # Recalculate close for display only (never touches DB)
            if api_open and db_open_raw and db_close_raw:
                close = _recalculate_close(db_open_raw, db_close_raw, api_open)
            else:
                close = db_close_raw

            # Status: show notesVn value, fallback to regular status
            status = notes_vn or (cached.get("status", "") if cached else (scraped.status or db_flight.get("Status", "")))
            # Break status text into compact lines for the rowspan=2 cell
            status_lines = _compact_status_lines(status)
            names = db_flight.get("Names", "")
            ckrow = cached.get("ck_row", "") if cached else (scraped.ck_row or db_flight.get("ckRow", ""))
            flight_type = db_flight.get("Type", "")
            bay = _crosscheck_bay(db_flight.get("Bay"), cached.get("gate", "") if cached else scraped.gate)
            route = _crosscheck_route(db_route, cached.get("route", "") if cached else api_route)

            # Cache indicator badge
            cache_badge = ""
            if is_from_cache:
                cache_badge = Span(
                    "💾",
                    style="font-size:0.6rem; margin-left:0.2rem; opacity:0.6;",
                    title="From status cache",
                )

            row1 = Tr(
                Td(Span(call), cache_badge),
                Td(api_open_formatted if api_open else "--"),
                Td(status_lines, rowspan="2"),
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

        date_sections.append(
            Div(
                P(
                    f"\U0001f4c5 {date_display}",
                    style="font-weight:600; margin-bottom:0.3rem;",
                ),
                Div(
                    Table(Tbody(*table_rows)),
                    style="overflow-x: auto;",
                ),
                cls="date-section",
            )
        )

    # If no dates have flights, show empty state
    if not date_sections:
        return Div(
            P("Không có chuyến bay nào trong 3 ngày tới",
              style="font-size:0.8rem; color:#94a3b8;"),
            _api_preview_refresh_button(),
            id="api-preview-card",
            cls="api-preview-card",
        )

    return Div(
        Div(*date_sections),
        _api_preview_refresh_button(),
        id="api-preview-card",
        cls="api-preview-card",
    )


def _api_preview_refresh_button() -> Button:
    """Return the standard refresh button for API preview card."""
    return Button(
        "🔄 Cập nhật",
        hx_post="/flight/preview/fetch",
        hx_target="#api-preview-card",
        hx_swap="outerHTML",
        cls="btn-act",
        style="width:100%; margin-top:0.5rem;",
    )
