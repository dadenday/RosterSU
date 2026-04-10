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
