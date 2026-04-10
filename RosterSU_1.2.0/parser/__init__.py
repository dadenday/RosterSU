"""
RosterMaster Parser Module

Extracted from roster_single_user.py for maintainability.
Contains sheet detection, date resolution, and row parsing logic.
"""

# Thresholds imported directly from config (single source of truth)
from config import (
    SHIFT_TIME_MIN_ENTRIES,
    SHIFT_OFF_MIN_COUNT,
    SHIFT_TIME_MIN_CLUSTER,
    SHIFT_NAME_MIN_CANDIDATES,
    SHIFT_TOTAL_MIN_SIGNALS,
    SHIFT_COL_CONSISTENCY,
    SHIFT_WORKDAY_RATIO,
    FLIGHT_ROUTE_MIN_COUNT,
    FLIGHT_NAME_NEAR_ROUTE_MIN,
    FLIGHT_DISTINCT_NAMES_MIN,
    FLIGHT_HEADER_HITS_MIN,
    FLIGHT_WINDOW_ROUTE_HITS,
    FLIGHT_WINDOW_CALLSIGN_HITS,
    FUZZY_MATCH_THRESHOLD,
    DATE_MAJORITY_RATIO,
    DATE_PLURALITY_RATIO,
    DATE_ANOMALY_RATIO,
    SAFE_THRESHOLD,
)
from .detection import (
    detect_shift_sheet_by_invariants,
    detect_flight_personnel_sheet_by_invariants,
    identify_sheet_type,
    identify_sheet_type_legacy,
    build_row_signals,
    identify_shift_sheet_statistical,
)
from .engine import detect_zones_from_merged_ranges
from .utils import (
    norm_cell,
    get_cell_flags,
    clean_val,
    clean_time,
    normalize_text,
    is_valid_name_generic,
    is_valid_route,
    is_route_pattern,
    is_day_off_token,
    normalize_time_range,
    CELL_ROUTE,
    CELL_TIME,
    CELL_OFF,
    CELL_NAME,
)

__all__ = [
    # Thresholds
    'SHIFT_TIME_MIN_ENTRIES',
    'SHIFT_OFF_MIN_COUNT',
    'SHIFT_TIME_MIN_CLUSTER',
    'SHIFT_NAME_MIN_CANDIDATES',
    'SHIFT_TOTAL_MIN_SIGNALS',
    'SHIFT_COL_CONSISTENCY',
    'SHIFT_WORKDAY_RATIO',
    'FLIGHT_ROUTE_MIN_COUNT',
    'FLIGHT_NAME_NEAR_ROUTE_MIN',
    'FLIGHT_DISTINCT_NAMES_MIN',
    'FLIGHT_HEADER_HITS_MIN',
    'FLIGHT_WINDOW_ROUTE_HITS',
    'FLIGHT_WINDOW_CALLSIGN_HITS',
    'FUZZY_MATCH_THRESHOLD',
    'DATE_MAJORITY_RATIO',
    'DATE_PLURALITY_RATIO',
    'DATE_ANOMALY_RATIO',
    'SAFE_THRESHOLD',
    # Detection
    'detect_shift_sheet_by_invariants',
    'detect_flight_personnel_sheet_by_invariants',
    'identify_sheet_type',
    'identify_sheet_type_legacy',
    'build_row_signals',
    'identify_shift_sheet_statistical',
    'detect_zones_from_merged_ranges',
    # Utils
    'norm_cell',
    'get_cell_flags',
    'clean_val',
    'clean_time',
    'normalize_text',
    'is_valid_name_generic',
    'is_valid_route',
    'is_route_pattern',
    'is_day_off_token',
    'normalize_time_range',
    'CELL_ROUTE',
    'CELL_TIME',
    'CELL_OFF',
    'CELL_NAME',
]
