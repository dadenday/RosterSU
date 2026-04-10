"""
Parser Utilities

Cell normalization, validation, and text processing functions.
"""

import re
import unicodedata
from functools import lru_cache
from typing import Optional, List, Any

# Import regex patterns from config.py (single source of truth)
from config import RE_TIME_RANGE, RE_TIME, RE_ROUTE

# Cell Classification Bitmask
CELL_ROUTE = 1
CELL_TIME = 2
CELL_OFF = 4
CELL_NAME = 8

# Re-export patterns for backward compatibility
__all__ = ["RE_TIME_RANGE", "RE_TIME", "RE_ROUTE"]


@lru_cache(maxsize=2000)
def norm_cell(cell):
    """Normalize a cell value by converting to string, uppercasing, and stripping whitespace."""
    return str(cell).upper().strip()


def get_cell_flags(cell):
    """Classify cell content using bitmask to avoid repeated regex checks."""
    if not cell:
        return 0
    flags = 0
    s = norm_cell(cell)
    if RE_ROUTE.match(s):
        flags |= CELL_ROUTE
    if RE_TIME_RANGE.search(s):
        flags |= CELL_TIME
    if s in ["OFF", "HỌC", "NGHỈ", "PHÉP", "ĐI HỌC", "NGHI", "PHEP"]:
        flags |= CELL_OFF
    return flags


def clean_val(val):
    """Clean a cell value, removing trailing .0 and 'nan' strings."""
    if val is None:
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        return s[:-2]
    if s.lower() == "nan":
        return ""
    return s


def clean_time(t_str: str) -> str:
    """Normalize time string to consistent format."""
    if not t_str:
        return ""
    t_str = t_str.upper().replace("H", ":").replace(".", ":").replace("G", ":").strip()
    range_match = RE_TIME_RANGE.search(t_str)
    if range_match:
        try:
            start = RE_TIME.search(range_match.group(1)).group(1)
            end = RE_TIME.search(range_match.group(2)).group(1)
            return f"{start} - {end}"
        except (AttributeError, IndexError):
            return t_str
    match = RE_TIME.search(t_str)
    if match:
        return match.group(1)
    return t_str


def normalize_text(text: str) -> str:
    """Normalize text to NFC form and strip whitespace."""
    if text is None:
        return ""
    text = str(text)
    if text.endswith(".0"):
        text = text[:-2]
    return unicodedata.normalize("NFC", text).strip()


def is_valid_name_generic(text: str) -> bool:
    """Check if text looks like a valid person name."""
    if not text:
        return False
    text = str(text).replace("\n", " ").strip()
    if len(text) < 4:
        return False

    # Reject digits
    if any(char.isdigit() for char in text):
        return False

    # Must have some letters
    if not any(ch.isalpha() for ch in text):
        return False

    # Reject Flight Routes
    if RE_ROUTE.match(text.upper()):
        return False

    # Blocklist for metadata masquerading as names
    blocklist = {
        "AEROBRIDGE",
        "PASSENGER",
        "CHARTER",
        "CARGO",
        "COMMERCIAL",
        "SCHEDULE",
        "OPERATION",
        "AIRPORT",
        "CONTROL",
        "FLIGHT",
        "PLAN",
        "LIST",
        "FROM",
        "TO",
        "REMARK",
        "STATUS",
        "ACTUAL",
        "ESTIMATED",
        "DEPARTURE",
        "ARRIVAL",
        "TOTAL",
        "PAX",
        "SEAT",
        "NOTE",
        "BẢNG PHÂN CÔNG NHIỆM VỤ",
    }
    text_upper = text.upper()

    if text_upper in blocklist:
        return False

    if any(w in blocklist for w in text_upper.split()):
        return False

    if " " in text and any(
        x in text_upper for x in ["AIRPORT", "OPERATIONS", "CONTROL", "FLIGHT", "PLAN"]
    ):
        return False

    return True


def is_valid_route(s: Any) -> bool:
    """Check if string matches flight route pattern."""
    s = str(s).strip().upper()
    return bool(RE_ROUTE.match(s))


def is_route_pattern(cell: Any) -> bool:
    """Check if cell contains a flight route."""
    if not cell:
        return False
    s = str(cell).upper().strip()
    return bool(RE_ROUTE.match(s))


def is_day_off_token(cell: Any) -> bool:
    """Check if cell is a day-off marker."""
    if not cell:
        return False
    s = str(cell).upper().strip()
    return s in ["OFF", "HỌC", "NGHỈ", "PHÉP", "ĐI HỌC", "NGHI", "PHEP"]


def normalize_time_range(cell: Any) -> Optional[str]:
    """Extract and normalize time range from cell."""
    if not cell:
        return None
    s = str(cell).upper().strip()
    match = RE_TIME_RANGE.search(s)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return None


def compile_alias_regex(aliases: List[str]) -> Optional[Any]:
    """Combine all aliases into one optimized regex for matching."""
    clean_aliases = [
        normalize_text(a).strip() for a in aliases if normalize_text(a).strip()
    ]
    if not clean_aliases:
        return None
    # Sort by length desc to ensure longest match is preferred
    clean_aliases.sort(key=len, reverse=True)

    # Boundary characters (Vietnamese + Alphanumeric)
    chars = (
        "a-zA-Z0-9àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
    )
    boundary_start = f"(?:^|[^{chars}])"
    boundary_end = f"(?:$|[^{chars}])"

    pattern = (
        boundary_start
        + r"("
        + "|".join(map(re.escape, clean_aliases))
        + r")"
        + boundary_end
    )
    return re.compile(pattern, re.IGNORECASE)


def check_name_match(cell_content: Any, alias_regex: Any) -> bool:
    if not cell_content or not alias_regex:
        return False
    cell_text = normalize_text(cell_content)
    return bool(alias_regex.search(cell_text))
