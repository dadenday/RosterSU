"""
Database layer for RosterMaster.

Extracted from roster_single_user.py for maintainability.
Provides SQLite persistence for roster data.
"""

import os
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple


# ============================================================================
# Corporation Month Helpers (26th to 25th payroll cycle)
# ============================================================================

def corp_month_to_date_range(yyyy_mm: str) -> Tuple[str, str]:
    """Convert a corporation month (YYYY-MM) to actual date range.

    Corporation month is named after its END month (the 25th).
    Example: "2026-04" means March 26 → April 25.

    Args:
        yyyy_mm: Month in "YYYY-MM" format (the END month)

    Returns:
        Tuple of (start_date_iso, end_date_iso) in "YYYY-MM-DD" format
    """
    year, month = map(int, yyyy_mm.split("-"))

    # End: 25th of the named month
    end_date = datetime(year, month, 25)

    # Start: 26th of the previous month
    if month == 1:
        start_date = datetime(year - 1, 12, 26)
    else:
        start_date = datetime(year, month - 1, 26)

    return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")


def date_to_corp_month(date_iso: str) -> str:
    """Convert a date to its corporation month label.

    Corporation month is named after the END month (the 25th).
    Dates from 26th onwards belong to the NEXT month.
    Dates 1st-25th belong to the CURRENT month.

    Example: "2026-03-26" → "2026-04" (March 26 starts April corp month)
             "2026-04-10" → "2026-04" (April 10 is in April corp month)
             "2026-04-25" → "2026-04" (April 25 ends April corp month)
             "2026-04-26" → "2026-05" (April 26 starts May corp month)

    Args:
        date_iso: Date in "YYYY-MM-DD" format

    Returns:
        Corporation month in "YYYY-MM" format (named after end month)
    """
    year, month, day = map(int, date_iso.split("-"))

    if day >= 26:
        # 26th onwards: belongs to NEXT month
        if month == 12:
            return f"{year + 1:04d}-01"
        else:
            return f"{year:04d}-{month + 1:02d}"
    else:
        # 1st-25th: belongs to current month
        return f"{year:04d}-{month:02d}"


def format_corp_month_display(yyyy_mm: str) -> str:
    """Format a corporation month for display.

    Example: "2026-04" → "Tháng 04.2026 (26/03 - 25/04)"

    Args:
        yyyy_mm: Month in "YYYY-MM" format (the END month)

    Returns:
        Human-readable display string
    """
    year, month = map(int, yyyy_mm.split("-"))

    # Calculate start month (previous month)
    if month == 1:
        start_year = year - 1
        start_month = 12
    else:
        start_year = year
        start_month = month - 1

    return f"Tháng {month:02d}.{year} (26/{start_month:02d} - 25/{month:02d})"

# Import from config (lazy import to avoid circular dependency)
_config_loaded = False
_DB_FILE = None
_DEFAULT_HISTORY_LIMIT = None

def _load_config():
    global _config_loaded, _DB_FILE, _DEFAULT_HISTORY_LIMIT
    if not _config_loaded:
        from config import DB_FILE, DEFAULT_HISTORY_LIMIT
        _DB_FILE = DB_FILE
        _DEFAULT_HISTORY_LIMIT = DEFAULT_HISTORY_LIMIT
        _config_loaded = True


def get_db_path():
    """Get the current database path, re-reading JSON config each call.

    This allows db_path changes via the settings UI to take effect on next
    DB access without requiring an app restart. Falls back to module-level
    _DB_FILE if config is unavailable.
    """
    global _DB_FILE
    try:
        from config import (
            DEFAULT_CONFIG, CONFIG_FILE, PROJECT_ROOT,
            _load_merged_config,
        )
        merged = _load_merged_config()
        db_path = merged.get("db_path", DEFAULT_CONFIG["db_path"])
        db_path = db_path if os.path.isabs(db_path) else os.path.join(PROJECT_ROOT, db_path)
        return os.path.expanduser(db_path)
    except Exception:
        return _DB_FILE


def get_db():
    """Get a database connection with WAL mode enabled."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn


# Import state locks (lazy import)
_state_loaded = False
_DB_LOCK = None
_debug_log_fn = None
_log_debug_fn = None

def _load_state():
    global _state_loaded, _DB_LOCK, _debug_log_fn, _log_debug_fn
    if not _state_loaded:
        from state import DB_LOCK
        _DB_LOCK = DB_LOCK
        _state_loaded = True

def _init_database(debug_log_fn=None, log_debug_fn=None, db_lock=None):
    """Initialize database module with dependencies from main module."""
    global _debug_log_fn, _log_debug_fn, _DB_LOCK
    _debug_log_fn = debug_log_fn
    _log_debug_fn = log_debug_fn
    if db_lock is not None:
        _DB_LOCK = db_lock

def debug_log(message, category="DATABASE"):
    if _debug_log_fn:
        _debug_log_fn(message, category)

def log_debug(event, data=None):
    if _log_debug_fn:
        _log_debug_fn(event, data)


# ============================================================================
# Connection Management
# ============================================================================

def get_db():
    """Get a database connection with WAL mode enabled."""
    _load_config()
    conn = sqlite3.connect(_DB_FILE, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

@contextmanager
def db_conn():
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


# ============================================================================
# Schema Initialization
# ============================================================================

def init_db():
    """Initialize SQLite tables for storing roster data."""
    debug_log("init_db called")
    conn = get_db()
    c = conn.cursor()
    
    # Main roster table
    c.execute('''CREATE TABLE IF NOT EXISTS work_schedule
                 (work_date TEXT PRIMARY KEY,
                  full_data TEXT,
                  date_iso TEXT,
                  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    debug_log("Created work_schedule table if not exists")
    c.execute("CREATE INDEX IF NOT EXISTS idx_work_schedule_date_iso ON work_schedule(date_iso)")
    debug_log("Created index on work_schedule.date_iso if not exists")
    
    # Feature D: Cross-File Fingerprint Gate
    c.execute('''CREATE TABLE IF NOT EXISTS flight_dataset_history
                 (fingerprint TEXT PRIMARY KEY,
                  true_date TEXT,
                  ingestion_id TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    debug_log("Created flight_dataset_history table if not exists")
    
    # Feature E: Authority Protection (Rebuild Safe)
    c.execute('''CREATE TABLE IF NOT EXISTS ingestion_manifest
                 (true_date TEXT PRIMARY KEY,
                  file_hash TEXT,
                  dataset_fingerprint TEXT,
                  file_timestamp TEXT,
                  is_active INTEGER DEFAULT 1,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    debug_log("Created ingestion_manifest table if not exists")
    c.execute("CREATE INDEX IF NOT EXISTS idx_ingestion_manifest_fingerprint ON ingestion_manifest(dataset_fingerprint)")

    # Migration: add ckrow column if missing
    add_ckrow_column()

    conn.commit()
    conn.close()
    debug_log("Database initialization completed")


def add_ckrow_column():
    """Add ckrow column to work_schedule if it doesn't exist (idempotent)."""
    with db_conn() as conn:
        try:
            conn.execute("ALTER TABLE work_schedule ADD COLUMN ckrow TEXT")
            conn.commit()
            debug_log("Added ckrow column to work_schedule")
        except Exception as e:
            # Column may already exist — ignore duplicate column errors
            if "duplicate column name" not in str(e).lower():
                debug_log(f"add_ckrow_column error: {str(e)}")


# ============================================================================
# CRUD Operations
# ============================================================================

def clear_db():
    """Wipe the entire database."""
    debug_log("clear_db called")
    with _DB_LOCK:
        conn = get_db()
        try:
            conn.execute("DELETE FROM work_schedule")
            conn.commit()
            debug_log("Deleted all records from work_schedule table")
        finally:
            conn.close()
    debug_log("Database cleared successfully")

def count_history(filter_month=None):
    """Count total entries for pagination.

    Uses corporation month (26th to 25th) when filter_month is provided.
    """
    with db_conn() as conn:
        c = conn.cursor()
        where = ""
        params = []
        if filter_month and filter_month != "All":
            # Convert corporation month to actual date range
            start_date, end_date = corp_month_to_date_range(filter_month)
            where = "WHERE date_iso >= ? AND date_iso <= ?"
            params = [start_date, end_date]
        query = f"SELECT COUNT(*) as cnt FROM work_schedule {where}"
        c.execute(query, params)
        return c.fetchone()['cnt']

def load_history(limit=None, filter_month=None, offset=0):
    """Fetch entries, sorted by date, with SQL limiting and pagination support.

    Uses corporation month (26th to 25th) when filter_month is provided.
    """
    _load_config()
    if limit is None:
        limit = _DEFAULT_HISTORY_LIMIT
    debug_log(f"load_history called with limit={limit}, filter_month={filter_month}, offset={offset}")
    with db_conn() as conn:
        c = conn.cursor()
        try:
            where = ""
            params = []

            if filter_month and filter_month != "All":
                # Convert corporation month to actual date range
                start_date, end_date = corp_month_to_date_range(filter_month)
                where = "WHERE date_iso >= ? AND date_iso <= ?"
                params = [start_date, end_date]
                debug_log(f"Applied corp month filter: {filter_month} ({start_date} to {end_date})")

            # SAFE: 'where' is controlled via logic above, params are bound
            query = f"""
                SELECT work_date, full_data, last_updated
                FROM work_schedule
                {where}
                ORDER BY date_iso DESC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])
            debug_log(f"Executing query with {len(params)} parameters")
            c.execute(query, params)
            result = [dict(r) for r in c.fetchall()]
            debug_log(f"Loaded {len(result)} history entries")
            return result
        except Exception as e:
            debug_log(f"DB Load Error: {str(e)}")
            print(f"DB Load Error: {e}")
            raise

def get_available_months():
    """Get list of corporation months available in the database.

    Returns corporation months (YYYY-MM) sorted DESC, where each month
    represents the payroll period from 26th to 25th.
    """
    with db_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT date_iso FROM work_schedule ORDER BY date_iso DESC")
        dates = [r['date_iso'] for r in c.fetchall()]

    # Convert each date to its corporation month and deduplicate
    corp_months = set()
    for date_iso in dates:
        corp_months.add(date_to_corp_month(date_iso))

    return sorted(corp_months, reverse=True)


# ============================================================================
# Date Utilities
# ============================================================================

def is_valid_roster_year(date_obj):
    """
    Validates if a date object or string is within the expected roster range (2020-2100).
    Specifically targets the 01.01.1900 Excel zero-date artifact.
    """
    if not date_obj: return False
    
    try:
        if isinstance(date_obj, datetime):
            year = date_obj.year
        elif isinstance(date_obj, str):
            # Try parsing from normalized format DD.MM.YYYY
            norm = normalize_date_str(date_obj)
            parts = norm.split(".")
            if len(parts) == 3:
                year = int(parts[2])
            else:
                return False
        else:
            return False
            
        return 2020 <= year <= 2100
    except (ValueError, IndexError, AttributeError):
        return False

def normalize_date_str(date_str):
    """
    Normalizes date strings to DD.MM.YYYY format.
    Example: 10.2.2026 -> 10.02.2026
    Example: 10/02/26 -> 10.02.2026
    """
    if not date_str or date_str == "Unknown": return date_str
    # Replace common separators with dots
    cleaned = date_str.replace("/", ".").replace("-", ".").replace(" ", ".")
    # Clean up any double dots from multiple spaces or mixed separators
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
        
    parts = cleaned.split(".")
    if len(parts) == 3:
        d, m, y = parts
        # Ensure 2 digits for day and month
        d = d.zfill(2)
        m = m.zfill(2)
        # Handle 2-digit years
        if len(y) == 2:
            y = "20" + y
        elif len(y) == 4:
            pass  # Already correct
        else:
            # Unexpected year length — log and return original
            pass
        return f"{d}.{m}.{y}"
    return cleaned

def to_iso_date(date_str):
    norm_date = normalize_date_str(date_str)
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(norm_date, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    log_debug("date_parse_error", {"date": date_str})
    raise ValueError(f"Invalid date: {date_str}")


# ============================================================================
# Write Operations
# ============================================================================

def save_entry_overwrite(date_str, new_data, context=None):
    """
    STRICT OVERWRITE POLICY:
    Delete existing entry for this date, replace with new data.
    
    LAYER 1 COMPLIANCE: If context is provided, validates date matches global_date.
    """
    date_str = normalize_date_str(date_str)
    
    # === DB SAFETY GUARD ===
    # Prevent writes with dates that don't match the global truth
    if context is not None and context.global_date != "Unknown":
        if date_str != context.global_date:
            log_debug('DB_WRITE_REJECTED', {
                'reason': 'date_mismatch',
                'entry_date': date_str,
                'global_date': context.global_date,
                'source_file': context.source_filename
            })
            raise ValueError(f"Date mismatch: entry has {date_str} but global_date is {context.global_date}")
    
    debug_log(f"save_entry_overwrite called with date_str='{date_str}', new_data keys={list(new_data.keys()) if isinstance(new_data, dict) else type(new_data)}")
    final_data = {
        "date": date_str,
        "shift": new_data.get('shift'),
        "flights": new_data.get('flights', [])
    }

    if final_data.get('shift') == "OFF":
        final_data['flights'] = []
        debug_log("Set flights to empty list because shift is OFF")

    with _DB_LOCK:
        with db_conn() as conn:
            try:
                json_data = json.dumps(final_data, ensure_ascii=False, default=str)
                iso_date = to_iso_date(date_str)
                debug_log(f"Saving entry with work_date='{date_str}', date_iso='{iso_date}'")
                conn.execute("INSERT OR REPLACE INTO work_schedule (work_date, full_data, date_iso) VALUES (?, ?, ?)",
                          (date_str, json_data, iso_date))
                conn.commit()
                debug_log(f"Successfully saved entry for date {date_str}")
            except Exception as e:
                debug_log(f"Error saving entry for date {date_str}: {str(e)}")
                log_debug("db_write_error", {"date": date_str, "error": str(e)})
                raise

def save_entries_bulk(entries, context=None):
    """
    Saves multiple entries in a single transaction.
    STRICT OVERWRITE POLICY.
    
    LAYER 1 COMPLIANCE: If context is provided, validates all dates match global_date.
    """
    if not entries: return
    
    # === DB SAFETY GUARD ===
    # Validate all entry dates match the global truth date
    if context is not None and context.global_date != "Unknown":
        global_date = context.global_date
        for entry in entries:
            entry_date = normalize_date_str(entry.get('date', ''))
            if entry_date != global_date:
                log_debug('DB_WRITE_REJECTED', {
                    'reason': 'date_mismatch_in_bulk',
                    'entry_date': entry_date,
                    'global_date': global_date,
                    'source_file': context.source_filename
                })
                raise ValueError(f"Date mismatch in bulk save: entry has {entry_date} but global_date is {global_date}")
    
    with _DB_LOCK:
        with db_conn() as conn:
            try:
                conn.execute("BEGIN TRANSACTION")
                for res in entries:
                    date_str = normalize_date_str(res['date'])
                    
                    # Secondary guard (belt and suspenders)
                    if context is not None and context.global_date != "Unknown":
                        assert date_str == context.global_date, f"Date assertion failed: {date_str} != {context.global_date}"
                    
                    final_data = {
                        "date": date_str,
                        "shift": res.get('shift'),
                        "flights": res.get('flights', [])
                    }
                    if final_data.get('shift') == "OFF":
                        final_data['flights'] = []
                    
                    json_data = json.dumps(final_data, ensure_ascii=False, default=str)
                    iso_date = to_iso_date(date_str)
                    conn.execute("INSERT OR REPLACE INTO work_schedule (work_date, full_data, date_iso) VALUES (?, ?, ?)",
                              (date_str, json_data, iso_date))
                conn.commit()
                debug_log(f"Bulk saved {len(entries)} entries")
            except Exception as e:
                try:
                    conn.execute("ROLLBACK")
                except Exception as rb_err:
                    debug_log(f"Rollback also failed: {rb_err}")
                    log_debug("bulk_db_rollback_error", str(rb_err))
                debug_log(f"Bulk Save Error: {str(e)}")
                log_debug("bulk_db_error", str(e))
                raise

def delete_entries(dates):
    """Delete multiple entries by their work_date."""
    debug_log(f"delete_entries called with {len(dates)} dates")
    with _DB_LOCK:
        with db_conn() as conn:
            try:
                conn.executemany("DELETE FROM work_schedule WHERE work_date = ?", [(d,) for d in dates])
                conn.commit()
                debug_log(f"Successfully deleted {len(dates)} entries")
            except Exception as e:
                debug_log(f"Delete Error: {str(e)}")
                log_debug("db_delete_error", str(e))
                raise


# ============================================================================
# Fingerprint Gate Functions (Feature D & E)
# ============================================================================

def check_fingerprint_seen(fingerprint: str) -> bool:
    """
    Feature D: Check if a dataset fingerprint has already been ingested.
    Returns True if fingerprint exists in history (already seen).

    NOTE: This is an OPTIMIZATION only. System correctness must NOT depend on it.
    NOTE: Read-only SELECT in WAL mode — no DB_LOCK needed.
    """
    if not fingerprint:
        return False

    with db_conn() as conn:
        try:
            c = conn.cursor()
            c.execute("SELECT 1 FROM flight_dataset_history WHERE fingerprint = ?", (fingerprint,))
            return c.fetchone() is not None
        except Exception as e:
            debug_log(f"Fingerprint check error: {str(e)}")
            return False


def record_fingerprint(fingerprint: str, true_date: str, ingestion_id: str) -> None:
    """
    Record a dataset fingerprint in the history.
    Feature D: Cross-File Fingerprint Gate.
    """
    if not fingerprint:
        return
    
    with _DB_LOCK:
        with db_conn() as conn:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO flight_dataset_history (fingerprint, true_date, ingestion_id) VALUES (?, ?, ?)",
                    (fingerprint, true_date, ingestion_id)
                )
                conn.commit()
                debug_log(f"Recorded fingerprint for date {true_date}")
            except Exception as e:
                debug_log(f"Fingerprint record error: {str(e)}")


def get_active_ingestion(true_date: str) -> Optional[Dict]:
    """
    Feature E: Get the active ingestion for a given date.
    Returns the manifest row if exists, None otherwise.
    """
    with _DB_LOCK:
        with db_conn() as conn:
            try:
                c = conn.cursor()
                c.execute(
                    "SELECT * FROM ingestion_manifest WHERE true_date = ? AND is_active = 1",
                    (true_date,)
                )
                row = c.fetchone()
                return dict(row) if row else None
            except Exception as e:
                debug_log(f"Get active ingestion error: {str(e)}")
                return None


def update_ingestion_manifest(
    true_date: str,
    file_hash: str,
    dataset_fingerprint: str,
    file_timestamp: str
) -> bool:
    """
    Feature E: Authority Protection (Rebuild Safe).
    
    For each TRUE_DATE, only one ingestion version may be ACTIVE.
    
    Rule:
    - If new.timestamp > active.timestamp: replace active dataset
    - Else: ignore ingestion (older data)
    
    Returns True if this ingestion should proceed, False if it should be skipped.
    """
    with _DB_LOCK:
        with db_conn() as conn:
            try:
                c = conn.cursor()
                
                # Get current active ingestion for this date
                c.execute(
                    "SELECT * FROM ingestion_manifest WHERE true_date = ? AND is_active = 1",
                    (true_date,)
                )
                existing = c.fetchone()
                
                if existing:
                    existing_ts = existing['file_timestamp']
                    # Compare timestamps
                    if file_timestamp and existing_ts:
                        if file_timestamp > existing_ts:
                            # New data is newer - deactivate old and insert new
                            c.execute(
                                "UPDATE ingestion_manifest SET is_active = 0 WHERE true_date = ?",
                                (true_date,)
                            )
                            c.execute(
                                """INSERT INTO ingestion_manifest 
                                   (true_date, file_hash, dataset_fingerprint, file_timestamp, is_active)
                                   VALUES (?, ?, ?, ?, 1)""",
                                (true_date, file_hash, dataset_fingerprint, file_timestamp)
                            )
                            conn.commit()
                            debug_log(f"Replaced ingestion for date {true_date}")
                            return True
                        else:
                            # Existing data is newer or same - skip
                            debug_log(f"Skipping older ingestion for date {true_date}")
                            return False
                    else:
                        # No timestamp comparison possible - allow (optimization only)
                        return True
                else:
                    # No existing ingestion - insert new
                    c.execute(
                        """INSERT INTO ingestion_manifest 
                           (true_date, file_hash, dataset_fingerprint, file_timestamp, is_active)
                           VALUES (?, ?, ?, ?, 1)""",
                        (true_date, file_hash, dataset_fingerprint, file_timestamp)
                    )
                    conn.commit()
                    return True
                    
            except Exception as e:
                debug_log(f"Update ingestion manifest error: {str(e)}")
                return True  # On error, allow ingestion (optimization only)


def clear_ingestion_manifest() -> None:
    """Clear all ingestion manifest records (for testing/rebuild)."""
    with _DB_LOCK:
        with db_conn() as conn:
            try:
                conn.execute("DELETE FROM ingestion_manifest")
                conn.execute("DELETE FROM flight_dataset_history")
                conn.commit()
                debug_log("Cleared ingestion manifest tables")
            except Exception as e:
                debug_log(f"Clear manifest error: {str(e)}")
