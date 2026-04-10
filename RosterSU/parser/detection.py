"""
Sheet Detection Module

Functions for identifying sheet types (SHIFT vs FLIGHT vs SKIP).
Implements statistical detection and invariant-based classification.
"""

import re
from collections import defaultdict
from typing import Dict, List, Tuple, Any

from config import (
    SHIFT_TIME_MIN_ENTRIES,
    SHIFT_OFF_MIN_COUNT,
    SHIFT_TIME_MIN_CLUSTER,
    FLIGHT_ROUTE_MIN_COUNT,
    FLIGHT_NAME_NEAR_ROUTE_MIN,
    FLIGHT_DISTINCT_NAMES_MIN,
    FLIGHT_HEADER_HITS_MIN,
    FLIGHT_WINDOW_ROUTE_HITS,
    FLIGHT_WINDOW_CALLSIGN_HITS,
)
from .utils import (
    norm_cell,
    get_cell_flags,
    is_valid_name_generic,
    is_route_pattern,
    normalize_time_range,
    is_day_off_token,
    CELL_ROUTE,
    CELL_TIME,
    CELL_OFF,
    RE_ROUTE,
)

# Precompiled patterns
RE_SHIFT_TIME_PATTERN = re.compile(
    r"\d{1,2}[:hH]\d{2}(?::\d{2})?\s*[-–]\s*\d{1,2}[:hH]\d{2}(?::\d{2})?"
)


def build_row_signals(rows: List[List[Any]], max_rows: int = 200) -> Dict[str, Any]:
    """
    Analyze rows to build detection signals.
    Returns dict with time/route/name statistics.
    """
    time_counts = defaultdict(int)
    off_count = 0
    total_time_entries = 0

    route_rows = set()
    name_near_route = set()
    all_names = defaultdict(int)

    for r_idx, row in enumerate(rows[:max_rows]):
        for c_idx, cell in enumerate(row):
            if not cell:
                continue

            flags = get_cell_flags(cell)

            if flags & CELL_TIME:
                time_range = normalize_time_range(cell)
                if time_range:
                    time_counts[time_range] += 1
                    total_time_entries += 1
                continue

            if flags & CELL_OFF:
                off_count += 1

            if flags & CELL_ROUTE:
                route_rows.add(r_idx)

                for offset in (-2, -1, 1, 2):
                    if 0 <= c_idx + offset < len(row):
                        neighbor = row[c_idx + offset]
                        if is_valid_name_generic(neighbor):
                            name_near_route.add(str(neighbor).strip())
                            all_names[str(neighbor).strip()] += 1

        # Early exit thresholds
        if total_time_entries >= 10 and off_count >= 10:
            break
        if len(route_rows) >= 10 and len(name_near_route) >= 5:
            break

        # Dead sheet early exit — no signals after 60 rows
        if r_idx >= 60 and total_time_entries == 0 and len(route_rows) == 0 and len(all_names) == 0:
            break

    return {
        "time_counts": time_counts,
        "total_time_entries": total_time_entries,
        "off_count": off_count,
        "route_count": len(route_rows),
        "distinct_names": len(all_names),
        "name_near_route_count": len(name_near_route),
        "repeated_names": sum(1 for n in all_names.values() if n > 1),
    }


def detect_shift_sheet_by_invariants(
    rows: List[List[Any]], signals: Dict[str, Any] = None
) -> bool:
    """
    Detect SHIFT sheets using statistical invariants.
    Returns True if sheet appears to be a shift roster.
    """
    if signals is None:
        signals = build_row_signals(rows)

    if signals["total_time_entries"] < SHIFT_TIME_MIN_ENTRIES:
        return False

    if not signals["time_counts"]:
        return False

    max_count = max(signals["time_counts"].values()) if signals["time_counts"] else 0

    if max_count < SHIFT_TIME_MIN_CLUSTER:
        return False

    if signals["off_count"] < SHIFT_OFF_MIN_COUNT:
        return False

    return True


def detect_flight_personnel_sheet_by_invariants(
    rows: List[List[Any]], signals: Dict[str, Any] = None
) -> bool:
    """
    Detect FLIGHT_PERSONNEL sheets using statistical invariants.
    Returns True if sheet appears to be a flight roster.
    """
    if signals is None:
        signals = build_row_signals(rows)

    if signals["route_count"] < FLIGHT_ROUTE_MIN_COUNT:
        return False

    if signals["name_near_route_count"] < FLIGHT_NAME_NEAR_ROUTE_MIN:
        return False

    if signals["distinct_names"] < FLIGHT_DISTINCT_NAMES_MIN:
        return False

    return True


def _windowed_flight_scan(rows, window_size=25, step=10):
    """
    Detect flight tables embedded inside mixed sheets.
    Looks for dense route/callsign clusters.
    """
    total_rows = len(rows)

    for start in range(0, total_rows, step):
        window = rows[start : start + window_size]

        route_hits = 0
        callsign_hits = 0

        for r in window:
            for cell in r:
                if not cell:
                    continue

                text = str(cell).upper()

                if "-" in text and len(text) <= 10:
                    route_hits += 1

                if text[:2].isalpha() and text[2:].isdigit():
                    callsign_hits += 1

        if (
            route_hits >= FLIGHT_WINDOW_ROUTE_HITS
            and callsign_hits >= FLIGHT_WINDOW_CALLSIGN_HITS
        ):
            return True

    return False


def identify_sheet_type(rows: List[List[Any]], sheet_name: str = "") -> str:
    """
    Main sheet type identification function.
    Returns: "SHIFT", "FLIGHT", or "SKIP"
    """
    if not rows:
        return "SKIP"

    # Flight Header Override (CSV-safe)
    try:
        preview_rows = rows[:12]
        header_preview = " ".join(
            " ".join(str(c or "") for c in r[:20]) for r in preview_rows
        ).upper()

        flight_header_hits = sum(
            [
                "CALLSIGN" in header_preview,
                "ROUTE" in header_preview,
                "DEP" in header_preview or "ETD" in header_preview,
                "ARR" in header_preview or "ETA" in header_preview,
            ]
        )

        if flight_header_hits >= FLIGHT_HEADER_HITS_MIN:
            return "FLIGHT"

    except Exception:
        pass

    signals = build_row_signals(rows)

    # Windowed Flight Detection — only when route signals are weak
    if signals["route_count"] < FLIGHT_ROUTE_MIN_COUNT:
        if _windowed_flight_scan(rows):
            return "FLIGHT"

    # Prioritize Flight (more specific patterns)
    if detect_flight_personnel_sheet_by_invariants(rows, signals):
        return "FLIGHT"

    if detect_shift_sheet_by_invariants(rows, signals):
        return "SHIFT"

    # Early Exit
    if signals.get("route_count", 0) >= FLIGHT_ROUTE_MIN_COUNT:
        return "FLIGHT"
    if signals.get("total_time_entries", 0) >= 10:
        return "SHIFT"

    return identify_sheet_type_legacy(rows, sheet_name)


def identify_sheet_type_legacy(rows, sheet_name=""):
    """
    Legacy identification using header text matching.
    Strict Identification Matrix (v5.6).
    """
    if not rows:
        return "SKIP"

    header_text = ""
    for row in rows[:15]:
        header_text += " ".join([str(c or "") for c in row[:50]]).upper() + " "

    # SHIFT SHEET DETECTION (Strict)
    is_shift_header = (
        "LỊCH LÀM VIỆC" in header_text
        or "LỊCH THỰC TẬP" in header_text
        or "DANH SÁCH" in header_text
        or "LỊCH PHÂN CA" in header_text
        or "TÊN CA MÃ CA" in header_text
        or "HỌ VÀ TÊN NV" in header_text
        or "MÃ CA" in header_text.upper()
    )
    is_ghost = "BẢNG PHÂN CÔNG NHIỆM VỤ" in header_text

    if is_shift_header and not is_ghost:
        return "SHIFT"

    # FLIGHT SHEET DETECTION (Strict)
    flight_markers = ["SERIAL", "CALLSIGN", "ROUTE"]
    found_flight_markers = sum(1 for m in flight_markers if m in header_text)

    is_flight_sheet_name = sheet_name.upper() in ["PVHL", "LICH BAY", "LỊCH BAY"]

    if (
        is_flight_sheet_name or "TRỰC CHẤT XẾP" in header_text
    ) and found_flight_markers >= FLIGHT_HEADER_HITS_MIN:
        return "FLIGHT"

    # SECONDARY SHIFT DETECTION
    is_secondary_marker = (
        "BẢNG PHÂN CÔNG CA LÀM VIỆC" in header_text
        or "CA SÁNG" in header_text
        or "CA TỐI" in header_text
    )

    if is_secondary_marker and not is_ghost:
        return "SHIFT"

    return "SKIP"


def identify_shift_sheet_statistical(
    rows: List[List[Any]],
) -> Tuple[bool, Dict[str, Any]]:
    """
    Statistical shift sheet detection (alternative method).
    Returns (is_valid, stats_dict).
    """
    name_candidates = []
    for r_idx, row in enumerate(rows[:100]):
        for c_idx, cell in enumerate(row[:50]):
            if is_valid_name_generic(cell):
                name_candidates.append((r_idx, c_idx))

    if len(name_candidates) < 10:
        return False, {}

    time_column_votes = defaultdict(int)
    workday_count = 0
    offday_count = 0

    for r_idx, c_idx in name_candidates:
        if r_idx >= len(rows):
            continue
        row = rows[r_idx]

        for offset in range(1, 10):
            check_col = c_idx + offset
            if check_col >= len(row):
                continue

            val = str(row[check_col] if row[check_col] else "").strip().upper()

            if RE_SHIFT_TIME_PATTERN.search(val) or any(
                x in val
                for x in ["CA SÁNG", "CA TỐI", "CA SANG", "CA TOI", "CA 1", "CA 2"]
            ):
                time_column_votes[check_col] += 1
                workday_count += 1
            elif val in ["OFF", "HỌC", "NGHỈ", "PHÉP", "ĐI HỌC"]:
                time_column_votes[check_col] += 1
                offday_count += 1

    total = workday_count + offday_count
    if total < 5:
        return False, {}

    if not time_column_votes:
        return False, {}

    dominant_col = max(time_column_votes, key=time_column_votes.get)
    col_consistency = time_column_votes[dominant_col] / total
    workday_ratio = workday_count / total

    stats = {"total": total, "ratio": workday_ratio, "consistency": col_consistency}

    is_valid = col_consistency >= 0.50 and workday_ratio >= 0.30
    return is_valid, stats
