# RosterSU Codebase Review — 2026-04-08

**Scope:** All files under `RosterSU/` including `parser/` subpackage
**Type:** Research-only, no execution
**Auditor:** Qwen Code

---

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Security | 1 | 1 | 2 | 1 | 5 |
| Code Quality | 0 | 2 | 4 | 4 | 10 |
| Logic/Correctness | 0 | 2 | 3 | 2 | 7 |
| Performance | 0 | 1 | 3 | 2 | 6 |
| **TOTAL** | **1** | **6** | **12** | **9** | **28** |

---

## 1. SECURITY

### SEC-1 (Critical): XSS via unescaped `data-*` attributes in HTMX

**File:** `routes.py` — `post_scan` result rendering, `/upload` error messages  
**Severity:** Critical

User-controlled filenames from the Zalo downloads folder are rendered into HTML without escaping. If a file is named `<script>alert(1)</script>.xlsx`, it could execute XSS in the browser context.

**Evidence:**
```python
# routes.py — error/status messages embed filename directly
update_status("Idle", f"Uploaded: {filename}")
update_status("Error", f"Upload error: {err}")
```

The `update_status()` function stores this in `APP_STATUS`, which is later rendered by the status route. If `filename` contains HTML, it will be injected into the page.

**Fix:** Always `html.escape(filename, quote=True)` before embedding into status strings or UI elements.

---

### SEC-2 (High): `safe_path()` symlink check is incomplete on Android

**File:** `roster_single_user.py` — `safe_path()` function  
**Severity:** High

The `safe_path()` function checks `os.path.islink()` but on Android/Termux, symlinks can be nested within directory components. A path like `~/storage/downloads/Zalo/symlink_dir/file.xlsx` could bypass the check if `symlink_dir` itself is a symlink but the final file is not.

**Fix:** Use `os.path.realpath()` on the full combined path AND each intermediate component, then verify the resolved path starts with the resolved base directory.

---

### SEC-3 (Medium): Formula injection in export modules uses custom sanitizer

**File:** `export.py` — `generate_csv_content()`, `generate_ical_content()`  
**Severity:** Medium

The `sanitize_formula()` function is used for CSV/iCal export to prevent formula injection (`=CMD(...)` attacks). This function is defined elsewhere and passed via dependency injection (`_init_exports()`). If it has any gaps, all exported files inherit the vulnerability.

**Status:** The sanitizer is called on every field in both export functions — this is good. The risk is deferred to wherever `sanitize_formula` is defined.

---

### SEC-4 (Medium): App token stored in plaintext file

**File:** `config.py` — `APP_TOKEN_FILE = ".app_token"`  
**Severity:** Medium

The app token is stored in a plaintext file in the project root. On a shared Android device, any app with storage access could read it.

**Mitigation:** Low for single-user localhost-only app, but worth noting.

---

### SEC-5 (Low): Debug log file may contain sensitive data

**File:** `config.py` — `DEBUG_FILE`, `roster_single_user.py` — debug logging  
**Severity:** Low

The `roster_debug.json` file may contain filenames, user names, and parsed roster data. No redaction is applied before writing.

---

## 2. CODE QUALITY

### CQ-1 (High): Dual state management — legacy globals AND `AppState`

**File:** `state.py`  
**Severity:** High

Two parallel state systems exist:
1. **Legacy globals:** `APP_STATUS` (dict), `ROSTER_VERSION` (int), `INGEST_RUNNING` (Event)
2. **New `AppState`:** Thread-safe dataclass with lock-protected getters/setters

The legacy globals are still used directly in `_run_ingest_once()`:
```python
INGEST_RUNNING.set()  # Direct access to global Event
```

Meanwhile `state.py` has `AppState.ingest_running` property. This duplication means state can become inconsistent if one path writes to the global and another reads from `AppState`.

**Fix:** Migrate all direct global access to use `APP.ingest_running` consistently. Remove legacy globals after migration.

---

### CQ-2 (High): `parser/thresholds.py` is a redundant re-export layer

**File:** `parser/thresholds.py` (60 lines)  
**Severity:** High

This module does nothing but import from `config.py` and re-export. `parser/__init__.py` also re-exports from `thresholds.py`. This creates:
- `config.py` → `parser/thresholds.py` → `parser/__init__.py` → `roster_single_user.py`
- AND `config.py` → `roster_single_user.py` (direct import of same values)

The same threshold value exists in 3 namespaces. Tuning `FLIGHT_ROUTE_MIN_COUNT` in `config.py` works, but the intermediate modules add import latency and confusion.

**Fix:** Delete `parser/thresholds.py`. Have `parser/__init__.py` import directly from `config.py`.

---

### CQ-3 (Medium): `config.py` uses `sys.path.insert()` hack in submodules

**File:** `parser/thresholds.py`, `parser/utils.py`  
**Severity:** Medium

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

This modifies Python's import path at runtime. If the package is ever imported differently (e.g., as a package vs. as individual modules), this can cause import confusion or load the wrong `config.py`.

**Fix:** Use relative imports (`from ..config import ...`) or run the app as a proper Python package (`python -m RosterSU.roster_single_user`).

---

### CQ-4 (Medium): `identify_sheet_type_legacy()` is dead code shadowing

**File:** `parser/detection.py` — `identify_sheet_type_legacy()`  
**Severity:** Medium

`identify_sheet_type_legacy()` is only called as a final fallback from `identify_sheet_type()`. Its header matching logic (`"LỊCH LÀM VIỆC"`, `"SERIAL"`, `"CALLSIGN"`) is also duplicated in the `flight_header_hits` check above it. The legacy function is ~60 lines that will rarely execute.

**Fix:** Either remove it entirely or document the specific edge case it handles that the main function doesn't.

---

### CQ-5 (Medium): `data_types.py` duplicates constants from `config.py`

**File:** `data_types.py` — lines 17-18  
**Severity:** Medium

```python
SAFE_THRESHOLD = 0.4
QUARANTINE_DIR = "quarantine"
```

These are defined in `config.py` and re-defined in `data_types.py`. They happen to match now, but there's no guarantee they'll stay in sync.

**Fix:** Remove the duplicates in `data_types.py`, import from `config`.

---

### CQ-6 (Medium): `database.py` lazy import chain is fragile

**File:** `database.py` — `_load_config()`, `_load_state()`  
**Severity:** Medium

The module uses lazy loading with `_config_loaded`/`_state_loaded` flags:
```python
def _load_config():
    global _config_loaded, _DB_FILE, _DEFAULT_HISTORY_LIMIT
    if not _config_loaded:
        from config import DB_FILE, DEFAULT_HISTORY_LIMIT
```

This pattern means if `config.py` has an import error, it won't surface until the first DB operation at runtime — potentially mid-request with no useful stack trace.

**Fix:** Use direct imports at module level. The circular dependency concern that motivated this is no longer relevant after the modularization.

---

### CQ-7 (Low): `export.py` uses bare `print()` for errors

**File:** `export.py` — lines 100, 162  
**Severity:** Low

```python
print(f"iCal export error for row {r}: {e}")
print(f"CSV export error for row {r}: {e}")
```

These should use the `log_debug()` function instead for consistent logging and traceability.

---

### CQ-8 (Low): `components.py` uses bare `except:` clause

**File:** `components.py` — `is_flight_card_active()`  
**Severity:** Low

```python
try:
    card_date = datetime.strptime(date_str, "%d.%m.%Y")
except:
    return False
```

Bare `except:` catches `KeyboardInterrupt` and `SystemExit`, which should propagate.

**Fix:** `except (ValueError, TypeError):`

---

### CQ-9 (Low): `_load_patterns()` in `components.py` loads from global `config` import

**File:** `components.py` — `_load_patterns()`  
**Severity:** Low

```python
def _load_patterns():
    global _RE_ZONE_PATTERN, _RE_MULTIPLE_SPACES
    if _RE_ZONE_PATTERN is None:
        from config import RE_ZONE_PATTERN, RE_MULTIPLE_SPACES
        _RE_ZONE_PATTERN = RE_ZONE_PATTERN
```

This lazy import is called inside every component rendering function (`format_shift_display`, `build_copy_text`, `RosterCard`). On a hot render path, this adds a function call and global check every time.

**Fix:** Import at module level (no circular dependency risk here).

---

### CQ-10 (Low): `__init__.py` in `parser/` uses `from .thresholds import *`

**File:** `parser/__init__.py`  
**Severity:** Low

Star imports make it unclear what symbols are actually exported. If `thresholds.py` adds a new variable, it silently becomes part of the public API.

**Fix:** Explicit imports: `from .thresholds import SHIFT_TIME_MIN_ENTRIES, ...`

---

## 3. LOGIC / CORRECTNESS

### LC-1 (High): `save_entries_bulk()` catches all exceptions and re-raises — but swallows rollback errors

**File:** `database.py` — `save_entries_bulk()`  
**Severity:** High

```python
except Exception as e:
    conn.execute("ROLLBACK")
    debug_log(f"Bulk Save Error: {str(e)}")
    raise
```

If the `ROLLBACK` itself fails (e.g., connection already in a bad state), the original exception is lost and a new one is raised. The caller only sees the rollback error, not the root cause.

**Fix:** Wrap rollback in its own try/except:
```python
except Exception as e:
    try:
        conn.execute("ROLLBACK")
    except Exception as rb_err:
        debug_log(f"Rollback also failed: {rb_err}")
    raise
```

---

### LC-2 (High): `ParseContext.global_date` can be `"Unknown"` but parsers still run

**File:** `roster_single_user.py` — `process_one_sheet_data()`  
**Severity:** High

```python
if parse_context.global_date == "Unknown":
    log_debug("SHEET_SKIPPED", {...})
    return None
```

This check exists, but the `ParseContext` dataclass has `global_date: str` with no validation. If some code path constructs a `ParseContext` without going through `resolve_global_date()`, the date could be any arbitrary string, and sheets would be parsed with a wrong date.

**Fix:** Add a `__post_init__` validation in `ParseContext` that rejects empty or `"Unknown"` dates.

---

### LC-3 (Medium): `check_fingerprint_seen()` acquires `DB_LOCK` for a read-only SELECT

**File:** `database.py` — `check_fingerprint_seen()`  
**Severity:** Medium

```python
def check_fingerprint_seen(fingerprint: str) -> bool:
    with _DB_LOCK:
        with db_conn() as conn:
            c.execute("SELECT 1 FROM flight_dataset_history WHERE fingerprint = ?", ...)
```

SQLite allows concurrent reads in WAL mode. Acquiring the write lock for a SELECT blocks all other threads unnecessarily.

**Fix:** Remove `DB_LOCK` for read-only operations. Only use lock for writes.

---

### LC-4 (Medium): `DatasetSelector.normalize_flight_row()` uses dict keys that may not exist

**File:** `roster_single_user.py` — `normalize_flight_row()`  
**Severity:** Medium

```python
personnel = str(row_data.get("Names", "")).strip().upper()
flight = str(row_data.get("Call", "")).strip().upper()
open_t = str(row_data.get("Open", "")).strip().upper()
close_t = str(row_data.get("Close", "")).strip().upper()
```

This expects `FlightRow`-style keys (`Names`, `Call`, `Open`, `Close`), but the input `row_data` is a `Dict` from an unknown source. If the dict uses lowercase keys or different field names, the normalization produces empty tuples and false-negative fingerprint collisions.

---

### LC-5 (Medium): `RosterList` pagination uses string interpolation in `hx_get`

**File:** `components.py` — `RosterList()` pagination  
**Severity:** Medium

```python
hx_get=f"/list?filter_month=All&page={page - 1}"
```

The `page` value is an integer from user input. While it's validated via `max(1, int(page))`, the f-string interpolation into an HTMX attribute is technically a vector for injection if the validation ever changes.

**Fix:** Use `html.escape(str(page))` or ensure `page` is always a validated int before interpolation.

---

### LC-6 (Low): `normalize_date_str()` has a dead `else: pass` branch

**File:** `database.py` — `normalize_date_str()`  
**Severity:** Low

```python
if len(y) == 2:
    y = "20" + y
elif len(y) == 4:
    pass  # No-op — year is already correct
else:
    pass  # Unexpected year, but silently continues
```

An unexpected year length (e.g., 1 digit or 5 digits) silently falls through and returns a malformed date.

**Fix:** Log a warning or return the original string for unexpected lengths.

---

### LC-7 (Low): `to_iso_date()` raises `ValueError` which may propagate to UI

**File:** `database.py` — `to_iso_date()`  
**Severity:** Low

```python
raise ValueError(f"Invalid date: {date_str}")
```

If this propagates through `save_entries_bulk()` → the upload route, the user sees a raw Python exception instead of a friendly error message.

---

## 4. PERFORMANCE

### PF-1 (High): `RosterCard` renders `get_flight_type_class()` per flight — calls `_get_aircraft_config()` every time

**File:** `components.py` — `get_flight_type_class()` inside `RosterCard()`  
**Severity:** High

For each flight in every card, the config is fetched:
```python
if get_config:
    config = get_config()
```

For 60 roster entries with an average of 3 flights each, that's 180 config lookups per list render. The config doesn't change during runtime.

**Fix:** Cache the config at module level during `_init_components()`.

---

### PF-2 (Medium): `json.loads(r["full_data"])` called twice per row in `RosterList`

**File:** `components.py` — `RosterList()`  
**Severity:** Medium

```python
# First time — to get flights for sorting
data = json.loads(r["full_data"])
flights = data.get("flights", [])
sorted_flights = sort_flights_by_open_time(flights, shift_info=shift_info)
should_expand = is_flight_card_active(r["work_date"], sorted_flights)

# Second time — inside RosterCard()
data = json.loads(r["full_data"])
```

For 60 entries, that's 120 JSON parses. The parsed result could be passed to `RosterCard` directly.

**Fix:** Parse once, pass the parsed `data` dict to `RosterCard`.

---

### PF-3 (Medium): `_RE_ZONE_PATTERN.search()` called in multiple functions without caching

**File:** `components.py` — `format_shift_display()`, `RosterCard()`  
**Severity:** Medium

The pattern is lazily loaded but searched on every card render. For 60 cards, that's 120 regex searches. These could be pre-compiled at import time.

---

### PF-4 (Medium): `compile_alias_regex()` re-sorts aliases every call

**File:** `parser/utils.py` — `compile_alias_regex()`  
**Severity:** Medium

```python
clean_aliases.sort(key=len, reverse=True)
pattern = ...
return re.compile(pattern, re.IGNORECASE)
```

This is called during every upload and auto-ingest cycle. The alias list rarely changes between calls, so the regex could be cached.

**Fix:** Add an `@lru_cache(maxsize=1)` or cache on the frozen tuple of sorted aliases.

---

### PF-5 (Low): `clean_val()` calls `.endswith(".0")` string check on every cell

**File:** `parser/utils.py` — `clean_val()`  
**Severity:** Low

```python
s = str(val).strip()
if s.endswith(".0"):
    return s[:-2]
```

This runs on every cell in every row in every sheet. Most cells are already strings without `.0`. The `str()` conversion is redundant when the value is already a string (most Excel cells are).

---

### PF-6 (Low): `RE_MULTIPLE_SPACES.sub(" ", row).strip()` called on every flight in `build_copy_text()`

**File:** `components.py` — `build_copy_text()`  
**Severity:** Low

Minor — the regex substitution runs on every flight copy text build. For a single copy action this is negligible.

---

## 5. ARCHITECTURAL OBSERVATIONS

### A-1: Circular import between `roster_single_user.py` and `routes.py`

`routes.py` imports from `roster_single_user.py`:
```python
from roster_single_user import rt, serve, debug_log, layout, get_config, save_config, get_aliases, get_aircraft_config
```

`roster_single_user.py` imports from `routes.py`:
```python
from routes import *
```

This works because `app, rt = fast_app(hdrs=hdrs)` is created **before** `from routes import *`. But adding any new import at the top of `roster_single_user.py` that depends on routes will crash.

**Risk:** Medium. Works by accident, not by design.

---

### A-2: Thread safety is well-implemented

All shared state uses `RLock` or `Event` correctly. No race conditions detected. The `DB_LOCK` is properly used for all writes. The `APP` `AppState` dataclass provides clean encapsulation.

**Status:** ✅ Good

---

### A-3: Parser module follows pure function discipline well

`parser/engine.py` functions have no side effects — no DB, no I/O, no globals. This is excellent for testability.

**Status:** ✅ Good

---

### A-4: `AGENTS.md` contracts are mostly honored

| Contract | Status |
|----------|--------|
| SQLite WAL mode | ✅ `PRAGMA journal_mode=WAL` in `get_db()` |
| All writes behind `DB_LOCK` | ✅ |
| Strict overwrite (INSERT OR REPLACE) | ✅ |
| No schema changes | ✅ |
| No new tables | ✅ |

---

### A-5: `roster_styles.css` exists but is not wired up

The CSS file (`roster_styles.css`, ~300 lines) sits unused while ~300 lines of CSS are embedded as a Python string in `roster_single_user.py`. This prevents browser caching.

**Fix:** Serve as static file.

---

## PRIORITY ORDER FOR FIXES

| Priority | ID | Fix | Effort | Risk |
|----------|-----|-----|--------|------|
| P0 | SEC-1 | HTML-escape filenames in status messages | 5 min | None |
| P0 | LC-1 | Safe rollback in `save_entries_bulk` | 5 min | None |
| P1 | SEC-2 | Strengthen `safe_path()` for nested symlinks | 15 min | Low |
| P1 | CQ-1 | Migrate to single state system (`AppState`) | 30 min | Medium |
| P1 | LC-2 | Validate `ParseContext` in `__post_init__` | 5 min | None |
| P2 | CQ-2 | Delete `parser/thresholds.py` redundant layer | 10 min | Low |
| P2 | CQ-5 | Remove duplicate constants in `data_types.py` | 5 min | None |
| P2 | LC-3 | Remove `DB_LOCK` from read-only `check_fingerprint_seen` | 5 min | Low |
| P2 | PF-1 | Cache aircraft config in `RosterCard` | 10 min | Low |
| P2 | PF-2 | Single JSON parse per row in `RosterList` | 10 min | Low |
| P3 | CQ-3 | Remove `sys.path.insert()` hacks | 15 min | Medium |
| P3 | A-1 | Break circular import with `app_setup.py` | 20 min | Medium |
| P3 | A-5 | Wire up `roster_styles.css` as static file | 10 min | Low |

---

*Report generated: 2026-04-08*
