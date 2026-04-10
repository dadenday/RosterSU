# Tech Debt Audit: `roster_single_user.py`

**Audit Date:** 2026-02-28  
**File:** `roster_single_user.py`  
**Lines of Code:** 4,323 (reduced from 4,349)  
**Status:** ✅ REFACTORED (Partial)

---

## Executive Summary

The codebase has been partially refactored following this audit. Parser layer extracted to separate modules, dead code removed, and constants consolidated. `AGENT_INTENT` constraints updated to allow incremental improvements.

---

## ✅ Completed: Static HTML Viewer (2026-04-08)

| Feature | Status | Files Changed |
|---------|--------|---------------|
| Static HTML Viewer | ✅ Done | `export.py`, `routes.py`, `config.py`, `roster_single_user.py`, `state.py` |

- Added `export_snapshot()` and `generate_html()` to export module
- Auto-generates `schedule.html` + `schedule_meta.json` after ingestion
- Manual trigger via Settings UI + `POST /export/html`
- Configurable scope: All / Current Month / Latest / Latest N
- Opens instantly via Termux Widget shortcut
- Added CONFIG_LOCK for thread-safe config access
- Replaced debug print() with log_debug() in post_settings()

---

## ✅ Completed Refactoring

| Task | Status | Lines Saved |
|------|--------|-------------|
| P1: LRU cache for norm_cell() | ✅ Done | ~5 |
| P2: Consolidated threshold constants | ✅ Done | N/A (clarity) |
| P3: Removed dead extract_date_smart() | ✅ Done | ~52 |
| P4: CSS extraction | ⏭️ Skipped | N/A (framework limitation) |
| P5: Updated AGENT_INTENT | ✅ Done | N/A |
| P6: Extracted parser layer | ✅ Done | -589 (moved to modules) |

### New Module Structure

```
RosterSU/
├── roster_single_user.py    # Main app (4,323 lines)
├── rosterSU_config.json     # Config
├── tech_debt.md             # This file
└── parser/
    ├── __init__.py          # Module exports (64 lines)
    ├── thresholds.py        # Tunable constants (38 lines)
    ├── utils.py             # Cell/text utilities (158 lines)
    └── detection.py         # Sheet type detection (329 lines)
```

---

## 🔴 Critical Issues

### 1. Monolithic Architecture
| Metric | Value | Threshold |
|--------|-------|-----------|
| Lines of Code | 4,349 | < 1,000 ideal |
| Cyclomatic Complexity | High | < 10 per function |

**Location:** Entire file  
**Impact:** Cognitive overload, difficult testing, merge conflicts  
**Constraint Conflict:** `AGENT_INTENT.refactor_allowed=False` prevents necessary maintenance

### 2. Dead Code / Band-aid Fixes
```python
# Lines 877-878
_LOGGING_LOCAL = threading.local()
# Used in log_debug() to prevent infinite recursion
```
**Impact:** Masks root cause of logging instability  
**Fix:** Investigate why `log_debug` causes recursion and resolve at source

### 3. Schema Drift
| Table | Purpose | Added |
|-------|---------|-------|
| `work_schedule` | Core roster data | Original |
| `flight_dataset_history` | Cross-file dedup | Feature D |
| `ingestion_manifest` | Authority tracking | Feature E |

**Location:** Lines 960-998 (`init_db()`)  
**Constraint Conflict:** `AGENT_INTENT.db_schema_mutable=False`  
**Impact:** Schema changes without migration strategy

---

## 🟠 Architectural Debt

### 1. God Object Pattern
**Location:** `process_sheet_v3()` (Lines 2648-2828)  
**Responsibilities:**
- Zone detection
- Ghost busting logic
- Shift parsing
- Flight parsing
- Result aggregation

**Recommended Split:**
```
parser/
├── shift_detector.py    # shift-specific logic
├── flight_detector.py   # flight-specific logic
└── zone_analyzer.py     # zone/ghost detection
```

### 2. Layer Bypass
**Location:** `extract_date_smart()` (Lines 2318-2353)  
**Issue:** Duplicates `DateResolver` logic, violating contract:
```
"ONLY DateResolver decides the global truth date"
```
**Fix:** Remove function, use `DateResolver` exclusively

### 3. Cache Fragmentation
**Location:** Lines 1844-1848
```python
_cell_norm_cache = {}
_cell_norm_cache_lock = threading.Lock()

def norm_cell(cell):
    with _cell_norm_cache_lock:
        if cell not in _cell_norm_cache:
            _cell_norm_cache[cell] = str(cell).upper().strip()
        return _cell_norm_cache[cell]
```
**Issues:**
- Global unbounded dict (memory leak potential)
- Cleared per-sheet in `process_sheet_v3` (inconsistent)
- Manual lock management

**Fix:** Use `@functools.lru_cache(maxsize=10000)`

### 4. Mixed Concerns (CSS in Python)
**Location:** Lines 3012-3416 (~400 lines of embedded CSS)  
**Impact:**
- Cannot hot-reload styles
- IDE support limited
- Violates separation of concerns

**Fix:** Extract to `roster_styles.css` and serve as static file

---

## 🟡 Code Smell Catalog

| Smell | Location | Example | Severity |
|-------|----------|---------|----------|
| Magic Numbers | Line 1984 | `threshold: int = 85` | Low |
| Parameter Bloat | Line 2362 | `process_row_content_v2(clean_items, name_idx, alias_regex, inside_cols, shift_col, is_maca)` - 6 params | Medium |
| Comment Debt | Throughout | `# v6 PATCH` comments should be in git history | Low |
| Global Mutable State | Lines 890-895 | `_TOKEN_PATTERNS`, `_TOKEN_PATTERNS_TS` with manual refresh | Medium |
| Early Exit Duplicates | Multiple | Same threshold checks in different detectors | Low |

---

## 🟢 Quick Wins (Safe to Implement)

### 1. Extract CSS → `roster_styles.css`
**Effort:** 1 hour  
**Risk:** Low  
**Savings:** ~400 lines

### 2. Add LRU Cache to `norm_cell()`
```python
from functools import lru_cache

@lru_cache(maxsize=10000)
def norm_cell(cell):
    return str(cell).upper().strip()
```
**Effort:** 5 minutes  
**Risk:** Very low

### 3. Remove `extract_date_smart()`
Replace all calls with `DateResolver` instance methods.  
**Effort:** 30 minutes  
**Risk:** Medium (requires testing)

### 4. Consolidate Threshold Constants
```python
# At top of file
SHIFT_TIME_MIN_ENTRIES = 4
SHIFT_OFF_MIN_COUNT = 3
FUZZY_MATCH_THRESHOLD = 85
```
**Effort:** 15 minutes  
**Risk:** Very low

---

## 📊 Constraint Analysis

The `AGENT_INTENT` constraints are actively preventing maintenance:

```python
AGENT_INTENT = {
    "app_type": "local_single_user",
    "refactor_allowed": False,      # ← Blocks modularization
    "module_split_allowed": False,  # ← Blocks extraction
    "db_schema_mutable": False,     # ← Already violated by Features D/E
}
```

**Recommendation:** Update constraints:
```python
AGENT_INTENT = {
    "app_type": "local_single_user",
    "refactor_allowed": "incremental",      # Allow surgical fixes
    "module_split_allowed": "parser_only",  # Extract parser layer only
    "db_schema_mutable": False,             # Keep frozen
}
```

---

## 🏗️ Proposed Architecture (If Constraints Lifted)

```
roster-app/
├── roster_single_user.py    # Main app (~1500 lines: routes, UI, config)
├── parser/
│   ├── __init__.py
│   ├── date_resolver.py     # DateResolver class
│   ├── shift_detector.py    # Shift sheet detection
│   ├── flight_detector.py   # Flight sheet detection
│   └── zone_analyzer.py     # Zone/ghost logic
├── ingestion/
│   ├── __init__.py          # Already exists
│   ├── processor.py         # Already exists
│   └── manifest.py          # IngestionManifest + DatasetSelector
├── static/
│   └── roster_styles.css    # Extracted CSS
└── RosterSU/
    └── tech_debt.md         # This file
```

---

## Action Items

| Priority | Task | Effort | Blocked By |
|----------|------|--------|------------|
| P1 | Add LRU cache to `norm_cell()` | 5 min | None |
| P2 | Consolidate threshold constants | 15 min | None |
| P3 | Remove `extract_date_smart()` | 30 min | Testing |
| P4 | Extract CSS to external file | 1 hr | None |
| P5 | Update AGENT_INTENT constraints | 30 min | User approval |
| P6 | Extract parser layer | 4 hr | P5 |

---

## Conclusion

The codebase is **functional** but **brittle**. The architectural constraints were designed for stability but now prevent necessary maintenance. A pragmatic approach would be to:

1. Implement quick wins (P1-P4) that don't violate constraints
2. Re-evaluate constraints for P5-P6 with user input
3. Consider incremental refactoring rather than big-bang rewrite

**Last Updated:** 2026-02-28
