from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import io
import re

from config import (
    RE_TIME_RANGE,
    RE_TIME,
    RE_PHONE,
    RE_ID6,
    ZONE_SEQUENCE,
    MIN_ITEMS_PER_ZONE,
)
from data_types import FlightRow, ParsedSheet, ParseContext
from parser.utils import (
    clean_val,
    is_valid_route,
    clean_time,
    is_valid_name_generic,
    norm_cell,
    check_name_match,
)


def parse_row_items(row_raw):
    # Keep empty cells to preserve column offsets for proximity detection
    return [clean_val(x) for x in row_raw[:50]]


def find_name_index_in_list(clean_items, alias_regex):
    for i, item in enumerate(clean_items):
        if check_name_match(item, alias_regex):
            return i
    return -1


# ==========================================
# MODULE: PARSER - PURE FUNCTIONS (Phase 6)
# LAYER: 5
# RESPONSIBILITY: Side-effect-free parsing for testability
# DEPENDS ON: TYPES, DATE_RESOLVER
# EXPORTS: PureParseResult, parse_shift_sheet_pure, parse_flight_sheet_pure, _extract_shift_row_pure, _extract_flight_rows_pure
# ==========================================
#
# PURE FUNCTION RULES:
#   1. NO DB access (no db.exec, no db.insert, etc.)
#   2. NO file I/O (no open(), no os.path operations)
#   3. NO network calls (no http requests)
#   4. NO globals (no APP_STATUS, ROSTER_VERSION, etc.)
#   5. NO logging (no log_debug, no print, no logging calls)
#   6. All dependencies passed as parameters
#   7. Return structured data (dataclasses preferred)
#   8. Deterministic: same inputs always produce same outputs
#
# ==========================================


@dataclass
class PureParseResult:
    """
    Result from pure parsing functions.

    Phase 6: Structured output for pure parser functions.
    Contains all extracted data without any side effects.
    """

    date: str
    shift: Optional[str] = None
    flights: List[FlightRow] = field(default_factory=list)
    sheet_name: str = ""
    # Diagnostic info for debugging (optional)
    rows_processed: int = 0
    zones_detected: List[str] = field(default_factory=list)
    parse_warnings: List[str] = field(default_factory=list)

    def to_parsed_sheet(self) -> "ParsedSheet":
        """Convert to ParsedSheet for DB storage."""
        return ParsedSheet(
            date=self.date,
            shift=self.shift,
            flights=self.flights,
            sheet_name=self.sheet_name,
        )


def _extract_shift_row_pure(
    clean_items: List,
    name_idx: int,
    shift_col: Optional[int],
    is_maca: bool = False,
    is_vsbx: bool = False,
) -> Optional[str]:
    """Extract shift time from a single row. Returns shift string or None."""
    if not clean_items:
        return None

    # Check for routes - if found, this is a flight row, not shift
    has_route = any(is_valid_route(x) for x in clean_items)
    if has_route:
        return None

    # STRICT MODE: Use shift_col if provided (Anchor-based)
    if shift_col is not None and shift_col < len(clean_items):
        item = clean_items[shift_col]
        v_upper = str(item or "").upper()

        # Time Range
        if RE_TIME_RANGE.search(v_upper):
            return clean_time(item)
        # Keyword
        if "HỌC" in v_upper:
            return "HỌC"
        if v_upper in ["OFF", "NGHỈ", "PHÉP"]:
            return v_upper

    # PROXIMITY FALLBACK: Restrict to 10 cells right of name
    right_side_items = clean_items[name_idx + 1 : name_idx + 11]

    # Weak Anchor: Time Range (Priority)
    for item in right_side_items:
        if RE_TIME_RANGE.search(str(item)):
            return clean_time(item)

    # Weak Anchor: Keyword
    for item in right_side_items:
        v_upper = str(item).upper()
        if "HỌC" in v_upper:
            return "HỌC"
        if v_upper in ["OFF", "NGHỈ", "PHÉP"]:
            return v_upper

    # Strong Anchor: Phone (Restricted range)
    # ONLY return OFF if no time was found and phone is present
    has_phone = any(
        RE_PHONE.match(str(x).replace(".", "").replace(" ", ""))
        for x in right_side_items
    )
    if has_phone:
        return "OFF"

    # Strict Column Fallback (if we had a shift_col but it was empty)
    if shift_col is not None and shift_col < len(clean_items):
        if not clean_val(clean_items[shift_col]):
            return "OFF"

    # MÃ CA sheet logic: if name is found but no time/phone, likely OFF
    if is_maca:
        other_cells = [x for i, x in enumerate(clean_items) if i != name_idx and x]
        if not other_cells:
            return "OFF"

    # VS-BX Name-based fallback
    if is_vsbx:
        return "OFF"

    return None


def _extract_flight_rows_pure(
    clean_items: List,
    route_idx: int,
    name_idx: int,
    alias_regex,
    inside_cols: Optional[List[int]] = None,
) -> List[FlightRow]:
    """
    PURE: Extract flight row(s) from a single row.

    No side effects. All parameters passed in. Returns list of FlightRow.

    Args:
        clean_items: Normalized row items
        route_idx: Index of route cell (AAA-BBB pattern)
        name_idx: Index of name cell (-1 for outbound probe)
        alias_regex: Compiled regex for name matching
        inside_cols: List of columns to check for names (strict mode)

    Returns:
        List of FlightRow objects (may be empty)
    """
    if not clean_items:
        return []

    call_val = clean_items[route_idx - 1] if route_idx > 0 else ""
    type_val = clean_items[route_idx - 2] if route_idx > 1 else ""

    # Find Anchor (Bay or Close Time)
    anchor_idx = -1
    for i in range(route_idx + 1, len(clean_items)):
        val = clean_items[i]
        # Time pattern
        if RE_TIME.search(val):
            anchor_idx = i
        # Bay pattern (short, follows time) - Must be non-empty
        if val and len(val) <= 4 and anchor_idx != -1:
            anchor_idx = i
            break  # Bay is the strongest anchor

    if anchor_idx == -1:
        anchor_idx = route_idx  # Fallback

    # Extract metadata relative to anchor
    times_found = []
    for i in range(anchor_idx, route_idx, -1):
        if RE_TIME.search(clean_items[i]):
            times_found.append(clean_time(clean_items[i]))

    row_close = times_found[0] if len(times_found) >= 1 else ""
    row_open = times_found[1] if len(times_found) >= 2 else ""
    row_bay = ""
    anchor_val = clean_items[anchor_idx] if anchor_idx < len(clean_items) else ""
    if anchor_val and len(anchor_val) <= 4 and not RE_TIME.search(anchor_val):
        row_bay = anchor_val

    found_flights: List[FlightRow] = []

    # ZONE_AUTHORITY: Flight parser does not assign zone
    # Zone is determined by shift sheet position only

    if inside_cols:
        # STRICT MODE: Only check identified columns
        for col_idx in inside_cols:
            if col_idx < len(clean_items):
                cand = clean_items[col_idx]
                if check_name_match(cand, alias_regex):
                    f_row = FlightRow(
                        type=type_val,
                        call=call_val,
                        route=clean_items[route_idx],
                        open=row_open,
                        close=row_close,
                        bay=row_bay,
                        names=cand,
                        zone="",
                    )
                    found_flights.append(f_row)

        # If no match in inside_cols and this is an outbound probe
        if not found_flights and name_idx == -1:
            return [
                FlightRow(
                    type=type_val,
                    call=call_val,
                    route=clean_items[route_idx],
                    open=row_open,
                    close=row_close,
                    bay=row_bay,
                    names="",
                    zone="",
                )
            ]

        return found_flights

    else:
        # LEGACY PROXIMITY MODE
        for offset in range(1, 5):  # Check next 4 items
            idx = anchor_idx + offset
            if idx >= len(clean_items):
                break

            cand = clean_items[idx]
            is_match = (
                check_name_match(cand, alias_regex)
                if alias_regex
                else is_valid_name_generic(cand)
            )

            if is_match:
                f_row = FlightRow(
                    type=type_val,
                    call=call_val,
                    route=clean_items[route_idx],
                    open=row_open,
                    close=row_close,
                    bay=row_bay,
                    names=cand,
                    zone="",
                )
                found_flights.append(f_row)

        if found_flights:
            return found_flights

        # Legacy Fallback
        if name_idx != -1 and name_idx < len(clean_items):
            return [
                FlightRow(
                    type=type_val,
                    call=call_val,
                    route=clean_items[route_idx],
                    open=row_open,
                    close=row_close,
                    bay=row_bay,
                    names=clean_items[name_idx],
                    zone="",
                )
            ]
        elif name_idx == -1:
            return [
                FlightRow(
                    type=type_val,
                    call=call_val,
                    route=clean_items[route_idx],
                    open=row_open,
                    close=row_close,
                    bay=row_bay,
                    names="",
                    zone="",
                )
            ]

    return []


def parse_shift_sheet_pure(
    rows: List,
    global_date: str,
    alias_regex,
    sheet_name: str = "",
    zone_blocks: Optional[List] = None,
) -> PureParseResult:
    """
    PURE: Parse a shift sheet without any side effects.

    This is the core shift parsing logic extracted from process_sheet_v3.
    All dependencies are passed as parameters. No globals, no DB access,
    no logging, no file I/O.

    Args:
        rows: Raw sheet rows (list of lists)
        global_date: Pre-resolved global date (DD.MM.YYYY format)
        alias_regex: Compiled regex for name matching
        sheet_name: Name of the sheet (for reference)
        zone_blocks: Optional zone blocks for structural zone detection

    Returns:
        PureParseResult with shift and flights data

    Example:
        >>> result = parse_shift_sheet_pure(rows, "15.01.2026", alias_regex)
        >>> print(result.shift)  # "08:00-17:00 (SÂN ĐỖ)"
        >>> print(result.flights)  # [FlightRow(...), ...]
    """
    result = PureParseResult(date=global_date, sheet_name=sheet_name)

    if not rows or global_date == "Unknown":
        result.parse_warnings.append("EMPTY_ROWS_OR_UNKNOWN_DATE")
        return result

    row_count = len(rows)
    result.rows_processed = row_count
    processed_indices = set()

    # Zone detection setup
    use_structural_zones = zone_blocks is not None and len(zone_blocks) > 0
    current_zone = ""
    ZONE_SEQUENCE = ["SÂN ĐỖ", "BĂNG CHUYỀN", "TRẢ HÀNH LÝ"]
    zone_sequence_idx = 0
    last_start_hour = -1
    active_ca_type = None
    last_active_ca_type = None

    # Count-based zone progression
    MIN_ITEMS_PER_ZONE = 15
    zone_shift_counts = {"SÂN ĐỖ": 0, "BĂNG CHUYỀN": 0, "TRẢ HÀNH LÝ": 0}
    first_zone_marker_row = -1

    # Header discovery
    header_row_idx, col_mapping = find_header_mapping(rows)
    shift_col = col_mapping.get("shift")

    # Sheet-level identification
    sheet_header_text = ""
    for row in rows[:15]:
        sheet_header_text += " ".join([norm_cell(c or "") for c in row[:50]]) + " "

    is_vsbx = "VỆ SINH" in sheet_header_text or "VS-BX" in sheet_header_text
    is_maca = sheet_name and "MÃ CA" in norm_cell(sheet_name)

    # Header mapping for flight filtering
    inside_cols = []
    outside_cols = []
    header_found = False

    for r_idx in range(row_count):
        if r_idx in processed_indices:
            continue
        row = rows[r_idx]
        items_curr = parse_row_items(row)
        cells_upper = [norm_cell(x) for x in items_curr if x]

        def row_has(substr):
            return any(substr in cell for cell in cells_upper)

        zone_cols_upper = [norm_cell(x) for x in items_curr[:2] if x]

        def zone_cols_have(substr):
            return any(substr in cell for cell in zone_cols_upper)

        # Dynamic Header Detection (legacy flight logic support)
        if not header_found and row_has("SERIAL") and row_has("CALLSIGN"):
            for c_idx, cell in enumerate(items_curr):
                c_val = norm_cell(cell or "")
                if any(
                    x in c_val
                    for x in [
                        "HL ĐI",
                        "HÀNH LÝ ĐI",
                        "TRẢ HL ĐẾN",
                        "QUÁ KHỔ",
                        "CHẤT XẾP HL",
                    ]
                ):
                    inside_cols.append(c_idx)
                elif any(
                    x in c_val for x in ["SÂN ĐỖ", "CẢNH GIỚI", "XI NHAN", "TÀU BAY"]
                ):
                    outside_cols.append(c_idx)
            header_found = True
            continue

        # Zone switching logic
        found_explicit_zone = False

        if use_structural_zones:
            structural_zone = get_zone_for_row(r_idx, zone_blocks)
            if structural_zone:
                current_zone = structural_zone
                found_explicit_zone = True
                if structural_zone == "SÂN ĐỖ":
                    zone_sequence_idx = 0
                elif structural_zone == "BĂNG CHUYỀN":
                    zone_sequence_idx = 1
                elif structural_zone == "TRẢ HÀNH LÝ":
                    zone_sequence_idx = 2

        if not use_structural_zones or not found_explicit_zone:
            if zone_cols_have("TRẢ HÀNH LÝ") or zone_cols_have("TRA HANH LY"):
                current_zone = "TRẢ HÀNH LÝ"
                zone_sequence_idx = 2
                found_explicit_zone = True
                last_start_hour = -1
                active_ca_type = None
                last_active_ca_type = None
            elif (
                zone_cols_have("SÂN ĐỖ")
                or zone_cols_have("SAN DO")
                or zone_cols_have("SÂN ĐỔ")
            ):
                if first_zone_marker_row == -1:
                    first_zone_marker_row = r_idx
                current_zone = "SÂN ĐỖ"
                zone_sequence_idx = 0
                found_explicit_zone = True
                last_start_hour = -1
                active_ca_type = None
                last_active_ca_type = None
            elif zone_cols_have("BĂNG CHUYỀN") or zone_cols_have("BANG CHUYEN"):
                current_zone = "BĂNG CHUYỀN"
                zone_sequence_idx = 1
                found_explicit_zone = True
                last_start_hour = -1
                active_ca_type = None
                last_active_ca_type = None

        # Identify CA type
        if row_has("CA SÁNG") or row_has("CA SANG") or row_has("CA 1"):
            active_ca_type = "SANG"
        elif row_has("CA TỐI") or row_has("CA TOI") or row_has("CA 2"):
            active_ca_type = "TOI"

        # Find any name for zone tracking
        any_name_idx = -1
        for i, item in enumerate(items_curr):
            if is_valid_name_generic(item):
                any_name_idx = i
                break

        if any_name_idx != -1:
            has_phone_any = any(
                RE_PHONE.match(x.replace(".", "").replace(" ", "")) for x in items_curr
            )
            has_id_any = any(RE_ID6.match(x) for x in items_curr)

            if has_phone_any or has_id_any or is_vsbx or is_maca:
                # Use pure shift extraction
                final_shift_any = _extract_shift_row_pure(
                    items_curr, any_name_idx, shift_col, is_maca, is_vsbx
                )
                if final_shift_any and final_shift_any not in ["OFF", "HỌC"]:
                    # Count shift item for current zone
                    if not found_explicit_zone and zone_sequence_idx < len(
                        ZONE_SEQUENCE
                    ):
                        current_zone_name = ZONE_SEQUENCE[zone_sequence_idx]
                        zone_shift_counts[current_zone_name] += 1

                    try:
                        h_str = (
                            final_shift_any[:2]
                            .replace(":", "")
                            .replace("H", "")
                            .strip()
                        )
                        if h_str.isdigit():
                            current_start_hour = int(h_str)
                            if last_start_hour != -1 and not found_explicit_zone:
                                current_zone_name = ZONE_SEQUENCE[zone_sequence_idx]
                                should_advance = False

                                if zone_sequence_idx == 0:
                                    if (
                                        zone_shift_counts["SÂN ĐỖ"]
                                        >= MIN_ITEMS_PER_ZONE
                                    ):
                                        is_ca_reset = (
                                            last_active_ca_type in ["TOI", "LO"]
                                            and active_ca_type == "SANG"
                                        )
                                        is_late_reset = (
                                            last_start_hour >= 11
                                            and current_start_hour <= 9
                                        )
                                        is_hint_reset = (
                                            current_start_hour < last_start_hour - 3
                                            and active_ca_type == "SANG"
                                        )
                                        if (
                                            last_active_ca_type is None
                                            and active_ca_type == "SANG"
                                        ):
                                            should_advance = False
                                        else:
                                            should_advance = (
                                                is_ca_reset
                                                or is_late_reset
                                                or is_hint_reset
                                            )

                                elif zone_sequence_idx == 1:
                                    if (
                                        zone_shift_counts["BĂNG CHUYỀN"]
                                        >= MIN_ITEMS_PER_ZONE
                                    ):
                                        is_ca_reset = (
                                            last_active_ca_type in ["TOI", "LO"]
                                            and active_ca_type == "SANG"
                                        )
                                        should_advance = is_ca_reset

                                if should_advance:
                                    zone_sequence_idx = min(
                                        zone_sequence_idx + 1, len(ZONE_SEQUENCE) - 1
                                    )
                                    last_start_hour = -1
                                    last_active_ca_type = None
                                else:
                                    last_start_hour = current_start_hour
                                    last_active_ca_type = active_ca_type
                            else:
                                last_start_hour = current_start_hour
                                last_active_ca_type = active_ca_type
                    except (ValueError, IndexError):
                        pass  # Ignore time parsing errors in pure function

        # Apply fallback zone
        if not found_explicit_zone:
            if first_zone_marker_row == -1 or r_idx < first_zone_marker_row:
                current_zone = "SÂN ĐỖ"
                zone_sequence_idx = 0
            elif zone_sequence_idx < len(ZONE_SEQUENCE):
                current_zone = ZONE_SEQUENCE[zone_sequence_idx]

        # Track zones detected
        if current_zone and current_zone not in result.zones_detected:
            result.zones_detected.append(current_zone)

        # Target user matching
        name_idx_curr = find_name_index_in_list(items_curr, alias_regex)
        if name_idx_curr == -1:
            continue

        has_phone = any(
            RE_PHONE.match(x.replace(".", "").replace(" ", "")) for x in items_curr
        )
        has_id = any(RE_ID6.match(x) for x in items_curr)

        # Check for routes to determine if this is a flight row
        route_idx = -1
        for i, item in enumerate(items_curr):
            if is_valid_route(item):
                route_idx = i
                break

        if route_idx != -1:
            # Flight row - use pure flight extraction
            found_flights = _extract_flight_rows_pure(
                items_curr, route_idx, name_idx_curr, alias_regex, inside_cols
            )

            # Check next row for outbound leg
            outbound: Optional[FlightRow] = None
            next_r = r_idx + 1
            if next_r < row_count:
                row_next = rows[next_r]
                items_next = parse_row_items(row_next)
                # Scan for route in next row
                next_route_idx = -1
                for i, item in enumerate(items_next):
                    if is_valid_route(item):
                        next_route_idx = i
                        break
                if next_route_idx != -1:
                    outbound_flights = _extract_flight_rows_pure(
                        items_next, next_route_idx, -1, alias_regex, inside_cols
                    )
                    if outbound_flights:
                        outbound = outbound_flights[0]
                        processed_indices.add(next_r)

            for final_flight in found_flights:
                if outbound:
                    final_flight = FlightRow(
                        type=final_flight.type,
                        call=outbound.call,
                        route=outbound.route,
                        open=final_flight.open,
                        close=final_flight.close,
                        bay=final_flight.bay,
                        names=final_flight.names,
                        zone=final_flight.zone,
                    )
                result.flights.append(final_flight)
        else:
            # Shift row - use pure shift extraction
            if has_phone or has_id or is_vsbx or is_maca:
                final_shift = _extract_shift_row_pure(
                    items_curr, name_idx_curr, shift_col, is_maca, is_vsbx
                )
                if final_shift:
                    if current_zone and final_shift not in ["OFF", "HỌC"]:
                        final_shift = f"{final_shift} ({current_zone})"
                    result.shift = final_shift

    return result


def parse_flight_sheet_pure(
    rows: List, global_date: str, alias_regex, sheet_name: str = ""
) -> PureParseResult:
    """
    PURE: Parse a flight sheet without any side effects.

    Flight sheets contain flight assignments without shift information.
    This is the core flight parsing logic extracted from process_sheet_v3.

    Args:
        rows: Raw sheet rows (list of lists)
        global_date: Pre-resolved global date (DD.MM.YYYY format)
        alias_regex: Compiled regex for name matching
        sheet_name: Name of the sheet (for reference)

    Returns:
        PureParseResult with flights data (shift will be None)

    Example:
        >>> result = parse_flight_sheet_pure(rows, "15.01.2026", alias_regex)
        >>> print(result.shift)  # None
        >>> print(result.flights)  # [FlightRow(...), ...]
    """
    result = PureParseResult(date=global_date, sheet_name=sheet_name)

    if not rows or global_date == "Unknown":
        result.parse_warnings.append("EMPTY_ROWS_OR_UNKNOWN_DATE")
        return result

    row_count = len(rows)
    result.rows_processed = row_count
    processed_indices = set()

    # Header mapping for strict column filtering
    inside_cols = []
    header_found = False

    for r_idx in range(row_count):
        if r_idx in processed_indices:
            continue
        row = rows[r_idx]
        items_curr = parse_row_items(row)

        cells_upper = [norm_cell(x) for x in items_curr if x]

        def row_has(substr):
            return any(substr in cell for cell in cells_upper)

        # Header detection for inside columns
        if not header_found and row_has("SERIAL") and row_has("CALLSIGN"):
            for c_idx, cell in enumerate(items_curr):
                c_val = norm_cell(cell or "")
                if any(
                    x in c_val
                    for x in [
                        "HL ĐI",
                        "HÀNH LÝ ĐI",
                        "TRẢ HL ĐẾN",
                        "QUÁ KHỔ",
                        "CHẤT XẾP HL",
                    ]
                ):
                    inside_cols.append(c_idx)
            header_found = True
            continue

        # Find route in this row
        route_idx = -1
        for i, item in enumerate(items_curr):
            if is_valid_route(item):
                route_idx = i
                break

        if route_idx == -1:
            continue

        # REFERENCE PARITY: Only process rows where target user's name is found.
        # The reference prototype's process_sheet_v3 only processes rows where
        # any_name_idx != -1 AND (has_phone or has_id). Without this guard,
        # we extract all flights including ones where the user isn't assigned.
        name_idx_curr = find_name_index_in_list(items_curr, alias_regex)

        # Skip rows where target user's name is not found
        if name_idx_curr == -1:
            continue

        # Extract flights using pure function
        found_flights = _extract_flight_rows_pure(
            items_curr, route_idx, name_idx_curr, alias_regex, inside_cols
        )

        # Check next row for outbound leg
        outbound: Optional[FlightRow] = None
        next_r = r_idx + 1
        if next_r < row_count:
            row_next = rows[next_r]
            items_next = parse_row_items(row_next)
            next_route_idx = -1
            for i, item in enumerate(items_next):
                if is_valid_route(item):
                    next_route_idx = i
                    break
            if next_route_idx != -1:
                outbound_flights = _extract_flight_rows_pure(
                    items_next, next_route_idx, -1, alias_regex, inside_cols
                )
                if outbound_flights:
                    outbound = outbound_flights[0]
                    processed_indices.add(next_r)

        for final_flight in found_flights:
            if outbound:
                final_flight = FlightRow(
                    type=final_flight.type,
                    call=outbound.call,
                    route=outbound.route,
                    open=final_flight.open,
                    close=final_flight.close,
                    bay=final_flight.bay,
                    names=final_flight.names,
                    zone=final_flight.zone,
                )
            result.flights.append(final_flight)

    return result


def find_header_mapping(rows):
    """
    Scans first 20 rows to find the header row and map critical columns.
    Returns: (row_index, mapping_dict)
    mapping: { 'name': idx, 'id': idx, 'shift': idx, 'phone': idx }
    """
    TARGET_KEYWORDS = {
        "name": ["HỌ VÀ TÊN", "HO VA TEN", "TÊN NHÂN VIÊN", "FULLNAME", "HỌ TÊN"],
        "id": ["MÃ NV", "MA NV", "MANV", "ID", "MÃ SỐ"],
        "shift": ["CA LÀM VIỆC", "TÊN CA", "MÃ CA", "SHIFT", "CA"],
        "phone": ["SĐT", "SỐ ĐIỆN THOẠI", "PHONE", "MOBILE", "TELEPHONE"],
    }

    best_row_idx = -1
    best_score = 0
    final_mapping = {}

    for r_idx in range(min(20, len(rows))):
        row = [str(c or "").strip().upper() for c in rows[r_idx]]
        current_mapping = {}
        score = 0

        for key, keywords in TARGET_KEYWORDS.items():
            for c_idx, cell in enumerate(row):
                if any(kw in cell for kw in keywords):
                    current_mapping[key] = c_idx
                    score += 1
                    break  # Found this key for this row

        if score > best_score:
            best_score = score
            best_row_idx = r_idx
            final_mapping = current_mapping

    return best_row_idx, final_mapping


def detect_zones_from_merged_ranges(sheet) -> list:
    """
    Detect zone blocks from merged cell ranges in column A.

    Structural Assumptions:
    - Column A contains zone blocks as large merged cells
    - Typical zone size: ~40 rows
    - Zone blocks are sorted by start_row

    Returns:
        List of zone blocks, each containing:
        - start_row: int (0-indexed)
        - end_row: int (0-indexed, inclusive)
        - zone_name: str (SÂN ĐỖ, BĂNG CHUYỀN, or TRẢ HÀNH LÝ)
    """
    ZONE_COLUMN = 0
    MIN_ZONE_ROWS = 15

    zone_blocks = []

    try:
        merged_ranges = sheet.merged_cells.ranges

        for merged_range in merged_ranges:
            if merged_range.min_col == 1 and merged_range.max_col == 1:
                row_span = merged_range.max_row - merged_range.min_row + 1

                if row_span >= MIN_ZONE_ROWS:
                    start_row = merged_range.min_row - 1
                    end_row = merged_range.max_row - 1

                    cell_value = (
                        str(sheet.cell(merged_range.min_row, 1).value or "")
                        .strip()
                        .upper()
                    )

                    zone_blocks.append(
                        {
                            "start_row": start_row,
                            "end_row": end_row,
                            "zone_name": None,
                            "raw_value": cell_value,
                        }
                    )
    except Exception as e:
        log_debug(
            "ZONE_MERGE_DETECTION_ERROR",
            {"error": str(e), "function": "detect_zones_from_merged_ranges"},
        )
        return []

    zone_blocks.sort(key=lambda x: x["start_row"])

    for idx, block in enumerate(zone_blocks):
        cell_value = block["raw_value"]

        if cell_value:
            if (
                "SÂN ĐỖ" in cell_value
                or "SAN DO" in cell_value
                or "SÂN ĐỔ" in cell_value
            ):
                block["zone_name"] = "SÂN ĐỖ"
            elif "BĂNG CHUYỀN" in cell_value or "BANG CHUYEN" in cell_value:
                block["zone_name"] = "BĂNG CHUYỀN"
            elif "TRẢ HÀNH LÝ" in cell_value or "TRA HANH LY" in cell_value:
                block["zone_name"] = "TRẢ HÀNH LÝ"

        if block["zone_name"] is None:
            if idx == 0:
                block["zone_name"] = "SÂN ĐỖ"
            elif idx == 1:
                block["zone_name"] = "BĂNG CHUYỀN"
            else:
                block["zone_name"] = "BĂNG CHUYỀN"

    log_debug(
        "ZONE_BLOCKS_DETECTED",
        {
            "count": len(zone_blocks),
            "blocks": [
                {"start": b["start_row"], "end": b["end_row"], "zone": b["zone_name"]}
                for b in zone_blocks
            ],
        },
    )

    return zone_blocks


def get_zone_for_row(row_index: int, zone_blocks: list) -> Optional[str]:
    """
    Get the zone name for a given row index from zone blocks.

    Containment rule: block.start_row <= row <= block.end_row
    """
    for block in zone_blocks:
        if block["start_row"] <= row_index <= block["end_row"]:
            return block["zone_name"]
    return None


def process_file_content(content, filename, alias_regex):
    """Parse file content and return (results, error, manifest)."""
    file_stream = io.BytesIO(content)
    return parse_file(file_stream, filename, alias_regex)
