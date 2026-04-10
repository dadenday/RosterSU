# RosterSU Architectural Map

**Date:** 2026-04-08
**Scope:** `RosterSU/` Refactored Codebase (v2)

---

## Architectural Relationship Map

```mermaid
graph TD
    %% Entry Point
    Main[roster_single_user.py] -- Entry point & orchestration --> FastHTML[FastHTML App]
    Main -- Manages --> Threads[Background Threads: Auto-Ingest, Browser]

    %% Web Layer (MVC)
    FastHTML -- Registers --> Routes[routes.py]
    Routes -- Renders --> Comp[components.py]
    Comp -- Generates --> HTML[FastHTML Fragments / HTMX]

    %% Parsing Pipeline
    Main -- Calls --> Engine[parser/engine.py]
    Engine -- Uses --> Det[parser/detection.py]
    Engine -- Uses --> Util[parser/utils.py]
    Engine -- Returns --> PureResult[PureParseResult]

    %% Supporting Modules
    Routes & Engine & Main -- Import --> Types[data_types.py]
    Routes & Engine & Main & Comp -- Import --> Cfg[config.py]
    Routes & Main -- Share --> State[state.py]

    %% Persistence
    Routes & Engine -- Read/Write --> DB[database.py]
    DB -- Manages --> SQLite[(SQLite: work_schedule<br/>flight_dataset_history<br/>ingestion_manifest)]

    %% Export
    Routes -- Triggers --> Export[export.py]
    Export -- Generates --> iCal[iCal Content]
    Export -- Generates --> CSV[CSV Content]

    %% Data Flow: Ingestion
    Threads -- Scans --> Zalo[AUTO_INGEST_DIR]
    Main -- Upload --> File[UploadFile]
    File & Zalo -- Input --> Main[parse_file()]
    Main -- DateResolver --> DateRes[DateResolver]
    Main -- DatasetSelector --> DSel[DatasetSelector]
    Main -- ConfidenceScorer --> CScorer[ConfidenceScorer]
    Main -- Manifest --> Mf[IngestionManifest]

    %% Contracts
    DateRes -- Creates --> Ctx[ParseContext]
    Ctx -- Passed to --> Engine
    Mf -- Validated by --> Gate[Safe Write Gate]
    Gate -- Guards --> DB

    %% Styling
    Comp -- References --> CSS[roster_styles.css]
```

---

## Module Roles & Responsibilities

| Module | Role | Key Responsibilities |
| :--- | :--- | :--- |
| `roster_single_user.py` | **Orchestrator** | Entry point, background thread management, ingestion pipeline (DateResolver, DatasetSelector, ConfidenceScorer, Safe Write Gate), and monolithic parse_file() function. |
| `routes.py` | **Controller** | FastHTML route handlers (`/`, `/status`, `/list`, `/upload`, `/scan`, `/settings`, `/delete`, `/clear-data`, `/export/ical`, `/export/csv`, `/shutdown`). Connects UI to background logic. |
| `components.py` | **View Layer** | Functional UI components: `RosterCard`, `RosterList`, date formatting (`format_date_vn`), shift display, flight sorting, aircraft type CSS classes. Lazy-loaded dependencies via `_init_components()`. |
| `parser/engine.py` | **Parsing Engine** | Pure extraction logic. `parse_shift_sheet_pure()`, `parse_flight_sheet_pure()` with side-effect-free design. Returns `PureParseResult`. Handles zone detection, name matching, flight row extraction. |
| `parser/detection.py` | **Sheet Detection** | Statistical sheet type identification: `identify_sheet_type()`, `detect_shift_sheet_by_invariants()`, `detect_flight_personnel_sheet_by_invariants()`, windowed flight scan, legacy fallback. |
| `parser/utils.py` | **Cell Utilities** | `norm_cell`, `get_cell_flags` (bitmask: ROUTE/TIME/OFF/NAME), `clean_val`, `clean_time`, `normalize_text`, `is_valid_name_generic`, `is_valid_route`, `compile_alias_regex`, `check_name_match`. |
| `database.py` | **Persistence** | SQLite abstraction: schema init, `save_entry_overwrite()`, `save_entries_bulk()`, `load_history()`, `delete_entries()`, fingerprint gate (`check_fingerprint_seen`, `record_fingerprint`), ingestion manifest management. |
| `state.py` | **Global State** | Thread-safe `AppState` dataclass with `STATE_LOCK`, `DB_LOCK`, `SHUTDOWN_EVENT`. Manages status, roster version, ingest running flag. Legacy aliases retained for backward compatibility. |
| `config.py` | **Configuration** | Constants, regex patterns (precompiled), detection thresholds, sheet markers, aircraft defaults, path config (Termux/Android). |
| `data_types.py` | **Domain Model** | Dataclasses: `FlightRow`, `ShiftRecord`, `ParsedSheet`, `ParseContext`, `DateCandidate`, `IngestionManifest`, `InvariantViolation`. |
| `export.py` | **Export Handler** | iCal (`.ics`) and CSV generation from DB records. Formula injection sanitization. Lazy-init via `_init_exports()`. |

---

## Data Flow: Ingestion → Storage → UI

### 1. Ingestion Phase (Data Input)
- **Source:** Files enter via **UI Upload** (`POST /upload`) or **Auto-Scan** (background thread scanning `AUTO_INGEST_DIR`).
- **Resolution:** `DateResolver` collects candidates from filename, sheet headers, and cells → weighted voting → single **global truth date**.
- **Extraction:** `parser/engine.py` runs pure parsing functions → `PureParseResult` per sheet.
- **Selection:** `DatasetSelector` fingerprints flight sheets (SHA256, order-independent) → selects authoritative dataset per file.
- **Scoring:** `ConfidenceScorer` computes confidence ∈ [0, 1]. Below `SAFE_THRESHOLD` (0.4) → file **quarantined**.
- **Manifest:** `IngestionManifest` tracks all metadata, warnings, anomalies for audit trail.

### 2. Storage Phase (Persistence)
- **Validation:** `ParseContext` enforces date authority — all entry dates must match `global_date`.
- **Write:** `database.py` executes **Strict Overwrite** policy (INSERT OR REPLACE) within `DB_LOCK` transaction.
- **Fingerprint Gate:** `flight_dataset_history` tracks ingested fingerprints (optimization only).
- **Manifest Gate:** `ingestion_manifest` enforces authority protection — newer files replace older for same date.
- **Signal:** `bump_db_rev()` increments roster version in `state.py`, notifying UI via HTMX polling.

### 3. UI Phase (Display)
- **Polling:** HTMX client polls `GET /status` with `rev` parameter. Server compares client rev → triggers `db-changed` event.
- **Fetching:** `RosterList` calls `load_history()` with optional month filter and pagination.
- **Rendering:** `components.py` renders `RosterCard` with shift color coding, expandable flight tables, aircraft type CSS classes, auto-expand for active flights.
- **Interaction:** Delete mode (checkboxes → `POST /delete`), pagination (`GET /list?filter_month=All&page=N`), settings form (`POST /settings`).

---

## Route Map

| Route | Method | Handler | Purpose |
|-------|--------|---------|---------|
| `/` | GET | `get()` | Main dashboard: upload form, scan button, roster list, delete controls |
| `/status` | GET | `get_status(rev)` | HTMX polling endpoint — returns status indicator + version check |
| `/list` | GET | `get_list(filter_month, page)` | Roster cards with month filter + pagination |
| `/upload` | POST | `post_upload(file)` | File upload → parse → bulk save (threaded) |
| `/scan` | POST | `post_scan()` | Trigger auto-ingest scan (threaded) |
| `/settings` | GET/POST | `get_settings()` / `post_settings()` | Settings page: aliases, aircraft types, data management |
| `/delete` | POST | `post_delete(selected_dates)` | Delete selected roster entries |
| `/clear-data` | POST | `post_clear_data()` | Wipe all roster data |
| `/export/ical` | GET | `get_export_ical()` | Download iCal file |
| `/export/csv` | GET | `get_export_csv()` | Download CSV file |
| `/shutdown` | POST | `post_shutdown()` | Graceful shutdown (Termux session close) |

---

## Database Schema

### `work_schedule` (Main roster table)
| Column | Type | Notes |
|--------|------|-------|
| `work_date` | TEXT (PK) | Normalized DD.MM.YYYY |
| `full_data` | TEXT (JSON) | `{"date", "shift", "flights": [...]}` |
| `date_iso` | TEXT | YYYY-MM-DD (for sorting/filtering) |
| `last_updated` | TIMESTAMP | Auto-set on insert |

### `flight_dataset_history` (Feature D: Fingerprint Gate)
| Column | Type | Notes |
|--------|------|-------|
| `fingerprint` | TEXT (PK) | SHA256 of normalized flight rows |
| `true_date` | TEXT | Global date when ingested |
| `ingestion_id` | TEXT | File hash |
| `created_at` | TIMESTAMP | Auto-set |

### `ingestion_manifest` (Feature E: Authority Protection)
| Column | Type | Notes |
|--------|------|-------|
| `true_date` | TEXT (PK) | Global date |
| `file_hash` | TEXT | File identifier |
| `dataset_fingerprint` | TEXT | Authoritative fingerprint |
| `file_timestamp` | TEXT | For recency comparison |
| `is_active` | INTEGER | 1 = active, 0 = superseded |
| `created_at` | TIMESTAMP | Auto-set |

---

## Key Classes & Contracts

### DateResolver
- **Contract:** Only DateResolver decides global truth date
- **Weights:** filename (5) > shift_header (3) > iso_cell (3) > flight_header (2) > shift_cell (2) > flight_cell (1)
- **Output:** `ParseContext(global_date, global_date_iso, source_filename, file_id, ...)`

### DatasetSelector
- **Contract:** ONE FILE = ONE FLIGHT DATASET
- **Method:** SHA256 fingerprint of sorted normalized rows → filter empties → filter duplicates → select max row_count

### ConfidenceScorer
- **Base:** 0.5 (neutral)
- **Signals:** date agreement (+0.2/+0.1), data extraction (+0.3/+0.1), anomalies (-0.05 each)
- **Threshold:** `SAFE_THRESHOLD = 0.4` → below = quarantine

### PureParseResult (parser/engine.py)
- **Contract:** No side effects — no DB, no I/O, no globals, no logging
- **Input:** rows, global_date, alias_regex, sheet_name, zone_blocks (optional)
- **Output:** PureParseResult → `.to_parsed_sheet()` for DB storage

---

## Thread Safety Model

| Lock | Protects | Used By |
|------|----------|---------|
| `STATE_LOCK` (RLock) | App status, roster version | `state.py` (AppState methods) |
| `DB_LOCK` (RLock) | All SQLite writes | `database.py` (save, delete, fingerprint, manifest) |
| `_DB_REV_LOCK` (Lock) | `_DB_REV` counter | `routes.py` (bump_db_rev local) |
| `SHUTDOWN_EVENT` (Event) | Graceful termination | Background threads |

- Background threads: `daemon=True`
- State access: Non-blocking with timeout (`try_get_app_status(timeout=0.05)`)
- HTMX polling: Never blocks — drops update if lock acquisition fails

---

*Note: This map represents the refactored state as of April 2026. Modules extracted from monolithic `roster_single_user.py` into separate files for maintainability.*
