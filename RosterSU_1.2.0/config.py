"""
Configuration constants and regex patterns for RosterMaster.

Extracted from roster_single_user.py for maintainability.

Design:
- Parser tuning constants (thresholds, markers, regexes) stay as Python constants.
  They are algorithm invariants, NOT user settings.
- Operational settings (port, paths, intervals, limits) live in DEFAULT_CONFIG
  and can be overridden via rosterSU_config.json.
- Module-level constants (DEFAULT_PORT, MAX_UPLOAD_MB, etc.) derive from
  DEFAULT_CONFIG merged with the JSON file at import time, so
  `from config import DEFAULT_PORT` always reflects user overrides.
"""

import re
import os
import json

# ============================================================================
# Application Configuration
# ============================================================================

# Calculate project root (one level up from RosterSU/ directory)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEBUG_FILE = os.path.join(PROJECT_ROOT, "roster_debug.json")
CONFIG_FILE = os.path.join(PROJECT_ROOT, "rosterSU_config.json")

# Default configuration — source of truth for all JSON-mergeable settings
DEFAULT_CONFIG = {
    # User preferences
    "aliases": ["Ấn", "ẨN", "Ẩn", "Nguyễn Ngọc Ấn", "NGỌC ẤN", "Nguyễn Ngọc Ẩn", "NGỌC ẨN", "Ân", "Án"],
    "aircraft": {
        "airbus": ["A300", "A310", "A318", "A319", "A320", "A321", "A330", "A340", "A350", "A380"],
        "boeing": ["B747", "B767", "B777", "B787"],
        "other": []
    },
    # Operational settings (user-overridable via JSON)
    "port": 8501,
    "history_limit": 60,
    "page_size": 50,
    "port_wait_timeout": 10,
    "ingest_interval": 5,
    "max_upload_mb": 20,
    "auto_ingest_dir": "~/storage/downloads/Zalo",
    "export_dir": "~/storage/downloads/Zalo",
    "processed_archive_dir": "processed_archive",
    # Paths (user-overridable via JSON settings UI)
    "db_path": "roster_history.db",
    # Static HTML Viewer
    "static_html_scope": "current_month",
    "static_html_count": 5,
    "static_html_output_dir": "~/storage/downloads/Zalo/viewer",
}

# ============================================================================
# JSON Merge — operational settings derive from config file + defaults
# ============================================================================

def _load_merged_config() -> dict:
    """Load JSON config and merge with DEFAULT_CONFIG."""
    merged = DEFAULT_CONFIG.copy()
    merged["aircraft"] = DEFAULT_CONFIG["aircraft"].copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            for key, val in user_config.items():
                if key == "aircraft" and isinstance(val, dict):
                    for sub_key in ["airbus", "boeing", "other"]:
                        if sub_key in val:
                            merged["aircraft"][sub_key] = val[sub_key]
                else:
                    merged[key] = val
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return merged

_MERGED = _load_merged_config()

# Module-level constants derived from merged config (backward-compatible imports)
# These reflect JSON overrides, so `from config import DEFAULT_PORT` works.
DEFAULT_PORT = int(_MERGED.get("port", DEFAULT_CONFIG["port"]))
DEFAULT_HISTORY_LIMIT = int(_MERGED.get("history_limit", DEFAULT_CONFIG["history_limit"]))
PAGE_SIZE = int(_MERGED.get("page_size", DEFAULT_CONFIG["page_size"]))
PORT_WAIT_TIMEOUT = int(_MERGED.get("port_wait_timeout", DEFAULT_CONFIG["port_wait_timeout"]))
INGEST_INTERVAL = int(_MERGED.get("ingest_interval", DEFAULT_CONFIG["ingest_interval"]))
MAX_UPLOAD_MB = int(_MERGED.get("max_upload_mb", DEFAULT_CONFIG["max_upload_mb"]))

# Paths — relative dirs are resolved relative to the JSON-configured base
_DB_PATH = _MERGED.get("db_path", DEFAULT_CONFIG["db_path"])
DB_FILE = _DB_PATH if os.path.isabs(_DB_PATH) else os.path.join(PROJECT_ROOT, _DB_PATH)
DB_FILE = os.path.expanduser(DB_FILE)

_AUTO_INGEST_BASE = os.path.expanduser(_MERGED.get("auto_ingest_dir", DEFAULT_CONFIG["auto_ingest_dir"]))
_EXPORT_BASE = os.path.expanduser(_MERGED.get("export_dir", DEFAULT_CONFIG["export_dir"]))

AUTO_INGEST_DIR = _AUTO_INGEST_BASE
EXPORT_DIR = _EXPORT_BASE
_PROCESSED_SUB = _MERGED.get("processed_archive_dir", DEFAULT_CONFIG["processed_archive_dir"])
PROCESSED_ARCHIVE_DIR = os.path.join(_AUTO_INGEST_BASE, _PROCESSED_SUB) if not os.path.isabs(_PROCESSED_SUB) else os.path.expanduser(_PROCESSED_SUB)

# Static HTML Viewer
_STATIC_OUTPUT_BASE = _MERGED.get("static_html_output_dir", DEFAULT_CONFIG["static_html_output_dir"])
STATIC_HTML_OUTPUT_DIR = os.path.expanduser(_STATIC_OUTPUT_BASE) if _STATIC_OUTPUT_BASE else os.path.join(_EXPORT_BASE, "viewer")
STATIC_HTML_FILENAME = "schedule.html"
STATIC_HTML_META_FILENAME = "schedule_meta.json"

# Static Viewer scope options (code constants, not user-overridable)
VALID_STATIC_SCOPES = ("all", "current_month", "latest", "latest_n")
DEFAULT_STATIC_SCOPE = "current_month"
DEFAULT_STATIC_COUNT = 5  # Default N for "latest_n" mode

APP_TOKEN_FILE = ".app_token"
FILE_READ_CHUNK_SIZE = 65536
TOKEN_LENGTH_BYTES = 16
TOKEN_LENGTH_HEX = 32

# ============================================================================
# Parser Configuration
# ============================================================================

ZONE_SEQUENCE = ["SÂN ĐỖ", "BĂNG CHUYỀN", "TRẢ HÀNH LÝ"]
MIN_ITEMS_PER_ZONE = 15

# ============================================================================
# Detection Thresholds (Tunable Constants)
# ============================================================================

# Shift Detection Thresholds
SHIFT_TIME_MIN_ENTRIES = 4      # Minimum time range entries to consider shift sheet
SHIFT_OFF_MIN_COUNT = 3         # Minimum OFF tokens to confirm shift sheet
SHIFT_TIME_MIN_CLUSTER = 4      # Minimum cluster count for time patterns
SHIFT_NAME_MIN_CANDIDATES = 10  # Minimum name candidates for statistical detection
SHIFT_TOTAL_MIN_SIGNALS = 5     # Minimum total signals for shift detection
SHIFT_COL_CONSISTENCY = 0.50    # Minimum column consistency ratio
SHIFT_WORKDAY_RATIO = 0.30      # Minimum workday ratio

# Flight Detection Thresholds
FLIGHT_ROUTE_MIN_COUNT = 3      # Minimum routes to consider flight sheet
FLIGHT_NAME_NEAR_ROUTE_MIN = 2  # Minimum names near routes
FLIGHT_DISTINCT_NAMES_MIN = 2   # Minimum distinct names
FLIGHT_HEADER_HITS_MIN = 2      # Minimum header keyword matches
FLIGHT_WINDOW_ROUTE_HITS = 6    # Route hits in windowed scan
FLIGHT_WINDOW_CALLSIGN_HITS = 4 # Callsign hits in windowed scan

# Fuzzy Matching
FUZZY_MATCH_THRESHOLD = 85      # Default fuzzy match threshold

# Date Resolution
DATE_MAJORITY_RATIO = 0.7       # Strong consensus ratio
DATE_PLURALITY_RATIO = 0.5      # Majority ratio
DATE_ANOMALY_RATIO = 0.6        # Anomaly trigger ratio

# Ingestion Safety
SAFE_THRESHOLD = 0.4            # Confidence threshold for safe ingestion
QUARANTINE_DIR = "quarantine"   # Directory for suspicious files

# ============================================================================
# Sheet Detection Markers
# ============================================================================

SHIFT_SHEET_MARKERS = {
    "required": [
        "CẢNG HÀNG KHÔNG QUỐC TẾ PHÚ QUỐC",
        "LỊCH LÀM VIỆC ĐỘI VỆ SINH",
        "LỊCH LÀM VIỆC BỘ PHẬN CXHL"
    ],
    "optional": [
        "TRẢ HÀNH LÝ",
        "SÂN ĐỖ",
        "BĂNG CHUYỀN",
        "PVHL Phân công nhiệm vụ",
        "BẢNG PHÂN CÔNG CA LÀM VIỆC"
    ]
}

# ============================================================================
# Regex Patterns (Precompiled for Performance)
# ============================================================================

# Matches time ranges like "08:00 - 16:30" or "8h00-17h00"
# INTENT: permissive time matching from messy spreadsheets - DO NOT tighten without dataset regression
RE_TIME_RANGE = re.compile(r'(\d{1,2}[:hH]\d{2}(?::\d{2})?)\s*[-–]\s*(\d{1,2}[:hH]\d{2}(?::\d{2})?)')

# Matches single time values like "08:00" or "14h30"
# INTENT: permissive time matching from messy spreadsheets - DO NOT tighten without dataset regression
RE_TIME = re.compile(r'(\d{1,2}[:hH]\d{2})')

# Matches flight routes like "SGN - PQC" or multi-stop "AKX-DMB-PQC"
# INTENT: permissive route matching from messy spreadsheets - DO NOT tighten without dataset regression
# Supports single routes (XXX-YYY) and multi-stop routes (XXX-YYY-ZZZ)
RE_ROUTE = re.compile(r'^[A-Z]{3}\s*(?:-|–|—)\s*[A-Z]{3}(?:\s*(?:-|–|—)\s*[A-Z]{3})*$')

# Matches Vietnamese phone numbers starting with 0
# INTENT: permissive phone number matching from messy spreadsheets - DO NOT tighten without dataset regression
RE_PHONE = re.compile(r'^0\d{9,11}$')

# Matches 6-digit staff IDs
# INTENT: permissive ID matching from messy spreadsheets - DO NOT tighten without dataset regression
RE_ID6 = re.compile(r'^\d{6}$')

# Matches dates in formats like DD.MM.YYYY, DD/MM/YY, etc.
# INTENT: permissive date matching from messy spreadsheets - DO NOT tighten without dataset regression
RE_DATE = re.compile(r'(\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2}))')

# Specific pattern for shift times in roster sheets
# INTENT: permissive shift time matching from messy spreadsheets - DO NOT tighten without dataset regression
RE_SHIFT_TIME_PATTERN = re.compile(r'\d{1,2}[:hH]\d{2}(?::\d{2})?\s*[-–]\s*\d{1,2}[:hH]\d{2}(?::\d{2})?')

# Matches date markers in sheet headers (e.g., "NGÀY 10/02/2026")
# INTENT: permissive header date matching from messy spreadsheets - DO NOT tighten without dataset regression
RE_HEADER_DATE_PATTERN = re.compile(r'NGÀY.*?(\d{1,2}[./-]\d{1,2}[./-](?:\d{4}|\d{2}))')

# Matches English date headers like "FLIGHT PLAN: FRI, 13 FEB 2026"
RE_ENGLISH_DATE_PATTERN = re.compile(r'(?:DATE|PLAN|FOR|ON).*?(\d{1,2})\s*([A-Z]{3})\s*(\d{4}|\d{2})', re.I)

# Matches zone patterns like "Sân đỗ (Gate 1)"
# INTENT: permissive zone matching from messy spreadsheets - DO NOT tighten without dataset regression
RE_ZONE_PATTERN = re.compile(r'(.*)\((.*)\)')

# Used for cleaning up multiple spaces
# INTENT: permissive space cleanup from messy spreadsheets - DO NOT tighten without dataset regression
RE_MULTIPLE_SPACES = re.compile(r' +')

# ============================================================================
# English Month Mapping
# ============================================================================

ENGLISH_MONTHS = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"
}
