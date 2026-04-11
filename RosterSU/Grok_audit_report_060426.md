# RosterSU/ Audit Report
**Date**: 2026-04-06  
**Scope**: Full codebase audit against AGENTS.md rules and project conventions

---

## 1. Overall Architecture & Intent Violation (Critical)

- **AGENTS.md Prime Directive**: The project explicitly declares:
  ```python
  AGENT_INTENT = {
      "app_type": "local_single_user",
      ...
      "refactor_allowed": False,
      "module_split_allowed": False,
      ...
  }
  ```
  The original design intent was a **single large file** (`roster_single_user.py` ~7000 lines) with routes-as-functions and components-as-Python-objects.

- **Current State**: RosterSU/ represents a **partial modular refactor** that directly violates `module_split_allowed: False`.
  - Main entry point: `RosterSU/roster_single_user.py` (still contains app setup, ingestion logic, and imports everything).
  - There is also a root-level `roster_single_user.py` (the canonical 7000+ line version).
  - This creates **duplication and confusion** about which file is active.

**Key Finding**: The modular split was done despite explicit prohibition. This is the most significant architectural issue.

---

## 2. File Inventory & Responsibilities

### Core Modules

| File | Purpose |
|------|---------|
| `__init__.py` | Empty package initializer. |
| `config.py` | Constants, paths, regex patterns, ingest/export directories. |
| `data_types.py` | Dataclasses (`FlightRow`, `ParsedSheet`, etc.). |
| `state.py` | Thread-safe state management (`RLock`, `APP_STATUS`, `ROSTER_VERSION`, status functions). |
| `database.py` | SQLite operations with lazy imports and thread safety. |
| `components.py` | UI components (`RosterCard`, `RosterList`, formatting helpers). Uses proper `fasthtml.common` objects. |
| `routes.py` | HTMX routes (`/`, `/status`, `/list`, `/delete`, etc.). **Has circular import** with `roster_single_user`. |
| `export.py` | iCal/CSV generation (lazy imports). |
| `roster_single_user.py` | Main FastHTML app + background ingestion orchestration. |

### Parser Subpackage

| File | Purpose |
|------|---------|
| `parser/__init__.py` | Re-exports utilities, detection functions, and thresholds. |
| `parser/engine.py` | Core sheet processing logic (pure functions). |
| `parser/utils.py` | Cell normalization, text processing, validation. |
| `parser/detection.py` | Sheet type detection (SHIFT vs FLIGHT_PERSONNEL) using statistical invariants. |
| `parser/thresholds.py` | Detection tuning constants (re-exported from config for backward compatibility). |

---

## 3. Code Quality & Rule Compliance

### ✅ Positive Patterns Observed

- **No string HTML returns**: No `return "<div>..."` found.
- **Proper component attributes**: Uses `cls=` instead of `class=` throughout.
- **Framework usage**: Correct use of `fasthtml.common` components.
- **Thread safety**: `RLock` used in state/database modules for concurrency.
- **Parser domain logic**: Follows AGENTS.md rules (statistical detection, regex patterns, date priority order).
- **Lazy imports**: Used to mitigate circular dependencies where detected.

### ⚠️ Issues Found

| Issue | Severity | Location |
|-------|----------|----------|
| Circular imports | High | `routes.py` imports from `roster_single_user` |
| File duplication | High | Two `roster_single_user.py` files (root + RosterSU/) |
| Mixed architecture | Medium | Some files still import heavily from monolithic file |
| Intent violation | Critical | Module split against `module_split_allowed: False` |
| Parser redundancy | Low | `thresholds.py` re-exports from config |

---

## 4. Technical Observations

### Framework & Libraries
- FastHTML + HTMX + PicoCSS usage is mostly correct.
- Database uses WAL mode as documented.
- Parser uses `python-calamine` + `rapidfuzz` as specified.
- Status polling via HTMX with revision counters is implemented.

### Security
- No obvious XSS issues in reviewed components (uses proper component construction).
- Thread-safe state access via locks.

### Parser Domain Rules
- Sheet detection follows AGENTS.md specification:
  1. SHIFT sheets: time range clustering ≥4, OFF tokens ≥3
  2. FLIGHT_PERSONNEL: route patterns (`AAA-BBB`) near human names
  3. Detection order: SHIFT precedes FLIGHT_PERSONNEL
- Date extraction priority: header → ISO scan → cell scan → filename fallback
- Regex patterns are precompiled (RE_TIME_RANGE, RE_ROUTE, etc.)

---

## 5. Recommendations

### Option Y (Surgical Fix - Recommended)
Delete or deprecate `RosterSU/` entirely. Keep everything in the root `roster_single_user.py` as originally intended. This respects `module_split_allowed: False`.

### Option Z (Good Enough Hack)
Clean up circular imports, remove duplicate files, make RosterSU/ the canonical package, and update AGENTS.md to allow modularization.

---

## 6. Current State Classification

**Transitional/Chaotic** — Mixed patterns exist because of the incomplete split. The code inside is reasonably well-structured and follows most FastHTML best practices, but the existence of the split itself is the primary architectural smell.

The parser logic and state management appear solid.

---

*Report generated: 2026-04-06*
