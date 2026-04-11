import os
import json
import html
import logging
import threading
from fasthtml.common import *
from fasthtml.starlette import Request
from starlette.responses import Response, FileResponse
from datetime import datetime, timedelta
import asyncio
from roster_single_user import (
    rt,
    serve,
    debug_log,
    layout,
    get_config,
    save_config,
    get_aliases,
    get_aircraft_config,
    compile_alias_regex,
    parse_file,
    ParseContext,
    consolidate_file_results,
    save_entries_bulk,
    log_debug,
)
from config import (
    DB_FILE,
    EXPORT_DIR,
    AUTO_INGEST_DIR,
    INGEST_INTERVAL,
    MAX_UPLOAD_MB,
    SAFE_THRESHOLD,
)
from state import (
    try_get_app_status,
    get_app_status,
    update_status,
    APP,
    bump_db_rev,
    SHUTDOWN_EVENT,
)
from database import get_available_months, clear_db, delete_entries
from export import generate_ical_content, generate_csv_content
from components import (
    format_date_vn,
    format_shift_display,
    shift_color,
    shift_text_class,
    build_copy_text,
    RosterCard,
    sort_flights_by_open_time,
    is_flight_card_active,
    RosterList,
    _init_components,
    invalidate_aircraft_config_cache,
    ApiPreviewCard,
)


# Flight API preview cache (in-memory, survives within app session)
_flight_api_cache: dict = {}
_flight_api_cache_lock = threading.Lock()


def _refresh_api_cache(days=3):
    """Fetch API data for today + N future days and store in cache."""
    global _flight_api_cache
    from scraper import FlightScraper

    scraper = FlightScraper()
    dates_data = {}

    for i in range(days):
        date = datetime.now() + timedelta(days=i)
        date_iso = date.strftime("%Y-%m-%d")
        date_db = date.strftime("%d.%m.%Y")

        try:
            flights = scraper.fetch_departures(date_iso)
            dates_data[date_db] = {
                "fetched_at": datetime.now().isoformat(),
                "flights": flights,
                "error": False,
                "error_message": None,
            }
            debug_log(f"Flight API cache: {len(flights)} flights for {date_db}")
        except Exception as e:
            dates_data[date_db] = {
                "fetched_at": datetime.now().isoformat(),
                "flights": [],
                "error": True,
                "error_message": str(e),
            }
            debug_log(f"Flight API cache error for {date_db}: {e}")

    with _flight_api_cache_lock:
        _flight_api_cache = {
            "dates": dates_data,
            "last_refresh": datetime.now().isoformat(),
        }


@rt("/status")
def get_status(rev: int = 0):
    s, current_rev = try_get_app_status()
    st = s.get("state", "Idle")
    details = s.get("details", "")

    # Clean up display text
    if st == "Idle":
        display = (
            "Sẵn sàng"
            if not details or details == "Ready" or details == "Monitoring folder..."
            else details
        )
    elif st == "Running":
        display = details if details else "Đang xử lý..."
    else:
        display = f"{st}: {details}" if details else st

    cls = "st-run" if st == "Running" else "st-idle"
    res = Span(
        Input(type="hidden", id="client-rev", name="rev", value=current_rev),
        Span("●", style="font-size:0.5rem;"),
        Span(display, id="status-text"),
        id="status-indicator",
        cls=cls,
    )
    if current_rev != rev:
        res.headers = {"HX-Trigger": "db-changed"}
    return res


_DB_REV = 0
_DB_REV_LOCK = threading.Lock()


def bump_db_rev():
    global _DB_REV
    with _DB_REV_LOCK:
        _DB_REV += 1


# === UI COMPONENTS MOVED TO components.py ===
# format_date_vn, format_shift_display, shift_color, shift_text_class,
# build_copy_text, RosterCard, sort_flights_by_open_time,
# is_flight_card_active, RosterList - see components.py


@rt("/list")
def get_list(filter_month: str = None, page: int = None):
    return RosterList(filter_month, page)


@rt("/delete", methods=["post"])
def post_delete(selected_dates: list[str] = None):
    if selected_dates:
        delete_entries(selected_dates)
        bump_db_rev()
    return RosterList()


@rt("/")
def get():
    months = get_available_months()
    # Default to current/latest month (first in list since sorted DESC)
    default_month = months[0] if months else None

    # Build options with "All" first, then mark default month as selected
    all_opt = Option("Tất cả tháng", value="All")
    month_opts = [all_opt] + [
        Option(m, value=m, selected=(m == default_month)) for m in months
    ]

    # Initial RosterList with default month filter
    initial_list = RosterList(filter_month=default_month)

    content = Div(
        Div(
            Select(
                *month_opts,
                name="filter_month",
                hx_get="/list",
                hx_target="#roster-list",
            ),
            cls="mb-2",
        ),
        Div(
            Button(
                "📂 Quét Zalo",
                hx_post="/scan",
                hx_target="#status-indicator",
                cls="btn-act",
            ),
            Form(
                Label(
                    "📤 Tải lên",
                    cls="button outline btn-act",
                    style="margin:0;display:flex;align-items:center;justify-content:center;cursor:pointer;",
                )(
                    Input(
                        type="file",
                        name="file",
                        accept=".xlsx,.xls,.csv",
                        style="display:none;",
                        onchange="this.form.requestSubmit()",
                    )
                ),
                hx_post="/upload",
                hx_target="#status-indicator",
                enctype="multipart/form-data",
            ),
            Button(
                "🗑️ Xóa",
                id="delete-btn",
                cls="btn-act btn-del",
                onclick="toggleDeleteMode()",
            ),
            cls="btn-row",
        ),
        Form(
            id="delete-form",
            hx_post="/delete",
            hx_target="#roster-list",
            hx_swap="outerHTML",
            style="display:none;",
        ),
        # API Preview Card
        Div(ApiPreviewCard(cache=_flight_api_cache), id="api-preview-wrapper"),
        Div(H4("📋 Lịch làm việc"), style="margin-top:0.5rem;"),
        Div(initial_list, id="roster-list"),
        Script("""
        function toggleDeleteMode() {
            const list = document.getElementById('roster-list');
            const btn = document.getElementById('delete-btn');
            const isChecked = list.classList.toggle('delete-mode');
            
            if (isChecked) {
                btn.textContent = '✓ Xóa đã chọn';
                btn.onclick = function() {
                    const checked = list.querySelectorAll('input[type="checkbox"]:checked');
                    if (checked.length === 0) {
                        alert('Vui lòng chọn ít nhất một mục để xóa.');
                        return;
                    }
                    if (confirm('Xóa ' + checked.length + ' mục đã chọn?')) {
                        // Use HTMX form to ensure X-App-Token is included
                        const form = document.getElementById('delete-form');
                        form.innerHTML = '';
                        checked.forEach(cb => {
                            const inp = document.createElement('input');
                            inp.type = 'hidden';
                            inp.name = 'selected_dates';
                            inp.value = cb.value;
                            form.appendChild(inp);
                        });
                        htmx.trigger(form, 'submit');
                    }
                };
            } else {
                btn.textContent = '🗑️ Xóa';
                btn.onclick = toggleDeleteMode;
            }
        }
        """),
    )
    return layout(content)


@rt("/upload", methods=["post"])
async def post_upload(file: UploadFile):
    if not file.filename:
        return Span("No file selected", cls="st-run", id="status-indicator")

    content = await file.read()
    filename = file.filename
    safe_filename = html.escape(filename, quote=True)

    # File size pre-check to prevent OOM
    if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
        update_status("Error", f"File too large (>{MAX_UPLOAD_MB}MB)")
        return Span(
            f"File too large (>{MAX_UPLOAD_MB}MB)", cls="st-run", id="status-indicator"
        )

    aliases = get_aliases()
    alias_regex = compile_alias_regex(aliases)

    update_status("Processing", f"Uploading {safe_filename}")

    def _parse():
        try:
            # parse_file returns (results, error) or (results, error, manifest)
            raw_result = parse_file(io.BytesIO(content), filename, alias_regex)
            if len(raw_result) == 3:
                results, err, manifest = raw_result
            else:
                results, err = raw_result
                manifest = None

            # === LAYER 4: SAFE WRITE GATE ===
            if manifest and manifest.confidence_score < SAFE_THRESHOLD:
                manifest.blocked = True
                manifest.block_reason = f"confidence_score_below_threshold: {manifest.confidence_score:.2f} < {SAFE_THRESHOLD}"
                log_debug(
                    "UPLOAD_BLOCKED",
                    {
                        "file": filename,
                        "confidence": manifest.confidence_score,
                        "threshold": SAFE_THRESHOLD,
                        "reason": manifest.block_reason,
                        "anomalies": manifest.anomalies,
                    },
                )
                update_status(
                    "Error",
                    f"Upload blocked: low confidence ({manifest.confidence_score:.0%})",
                )
                return

            if results:
                final = consolidate_file_results(results)
                # Pass manifest context for DB validation
                if manifest:
                    save_entries_bulk(
                        final,
                        context=ParseContext(
                            global_date=manifest.global_date,
                            global_date_iso=manifest.global_date_iso,
                            source_filename=manifest.filename,
                            file_id=manifest.file_hash,
                            date_confidence=manifest.confidence_score,
                            date_anomaly=len(manifest.anomalies) > 0,
                            date_candidates=manifest.date_candidates,
                        ),
                    )
                else:
                    save_entries_bulk(final)
                bump_db_rev()
                update_status("Idle", f"Uploaded: {safe_filename}")
            elif err:
                safe_err = html.escape(str(err), quote=True)
                update_status("Error", f"Upload error: {safe_err}")
            else:
                update_status("Error", "No data found in file")
        except Exception as e:
            safe_err = html.escape(str(e), quote=True)
            update_status("Error", safe_err)
            log_debug("upload_error", str(e))

    threading.Thread(target=_parse, daemon=True).start()
    return Span("Uploading...", cls="st-run", id="status-indicator")


@rt("/scan", methods=["post"])
def post_scan():
    if not APP.is_ingest_running():
        APP.set_ingest()

        def _scan():
            try:
                _run_ingest_once()
            finally:
                bump_db_rev()

        threading.Thread(target=_scan, daemon=True).start()
        return Span("Running...", cls="st-run", id="status-indicator")
    return Span("Busy...", cls="st-run", id="status-indicator")


@rt("/settings", methods=["get", "post"])
def settings_page(
    request: Request,
    aliases: str = "",
    aircraft_airbus: str = "",
    aircraft_boeing: str = "",
    aircraft_other: str = "",
    static_html_scope: str = "",
    static_html_count: str = "",
    db_path: str = "",
    auto_ingest_dir: str = "",
    export_dir: str = "",
    static_html_output_dir: str = "",
    processed_archive_dir: str = "",
    enable_flight_sync: str = "",
):
    """Handle GET (render form) and POST (save settings) for /settings."""
    if request.method == "POST":
        log_debug(
            "settings_post",
            {
                "enable_flight_sync": repr(enable_flight_sync),
                "aliases": aliases,
                "aircraft_airbus": aircraft_airbus,
                "aircraft_boeing": aircraft_boeing,
                "aircraft_other": aircraft_other,
                "static_html_scope": static_html_scope,
                "static_html_count": static_html_count,
                "db_path": db_path,
                "auto_ingest_dir": auto_ingest_dir,
                "export_dir": export_dir,
                "static_html_output_dir": static_html_output_dir,
                "processed_archive_dir": processed_archive_dir,
            },
        )

        config = get_config()
        config["aliases"] = [x.strip() for x in aliases.split(",") if x.strip()]
        config["aircraft"] = {
            "airbus": [
                x.strip().upper() for x in aircraft_airbus.split(",") if x.strip()
            ],
            "boeing": [
                x.strip().upper() for x in aircraft_boeing.split(",") if x.strip()
            ],
            "other": [
                x.strip().upper() for x in aircraft_other.split(",") if x.strip()
            ],
        }

        if static_html_scope:
            config["static_html_scope"] = static_html_scope
        try:
            config["static_html_count"] = (
                int(static_html_count) if static_html_count else 5
            )
        except ValueError:
            config["static_html_count"] = 5

        # Save path settings (only if user provided non-empty values)
        if db_path:
            config["db_path"] = db_path
        if auto_ingest_dir:
            config["auto_ingest_dir"] = auto_ingest_dir
        if export_dir:
            config["export_dir"] = export_dir
        if static_html_output_dir:
            config["static_html_output_dir"] = static_html_output_dir
        if processed_archive_dir:
            config["processed_archive_dir"] = processed_archive_dir

        # Save flight sync toggle (radio button pattern: "1" = on, "0" = off)
        # Radio buttons always send a single value, no list handling needed
        flight_sync_enabled = enable_flight_sync == "1"
        log_debug(
            "flight_sync_save",
            {
                "raw_value": repr(enable_flight_sync),
                "parsed": flight_sync_enabled,
            },
        )
        config["enable_flight_sync"] = flight_sync_enabled

        log_debug(
            "settings_saving",
            {
                "received_scope": static_html_scope,
                "received_count": static_html_count,
            },
        )
        save_config(config)

        # Note: Flight sync no longer auto-triggers on save
        # Users must manually press the "Sync Now" button
        log_debug("flight_sync_no_auto_trigger", {"action": "save_only"})

        saved = get_config()
        log_debug(
            "settings_verified",
            {
                "saved_scope": saved.get("static_html_scope"),
                "saved_count": saved.get("static_html_count"),
                "saved_enable_flight_sync": saved.get("enable_flight_sync"),
            },
        )

        invalidate_aircraft_config_cache()

    # Render settings page (for both GET and POST)
    config = get_config()
    log_debug(
        "settings_render",
        {
            "enable_flight_sync": config.get("enable_flight_sync"),
        },
    )
    aliases_val = ",".join(config.get("aliases", []))
    aircraft_config = config.get("aircraft", {})

    # Path defaults
    db_path_val = config.get("db_path", "roster_history.db")
    auto_ingest_val = config.get("auto_ingest_dir", "~/storage/downloads/Zalo")
    export_val = config.get("export_dir", "~/storage/downloads/Zalo")
    static_output_val = config.get(
        "static_html_output_dir", "~/storage/downloads/Zalo/viewer"
    )
    processed_val = config.get("processed_archive_dir", "processed_archive")

    # Flight sync state for radio buttons
    flight_sync_scope = config.get("enable_flight_sync", False)

    content = Div(
        Div(H4("⚙️ Cài đặt"), style="margin-bottom:0.75rem;"),
        # Unified settings form
        Form(
            # Path configuration section
            Div(
                H5("📁 Đường dẫn"),
                P(
                    "Tùy chỉnh đường dẫn cho database, thư mục ingest, xuất file. Dùng cho môi trường Termux.",
                    style="font-size:0.8rem; color:var(--muted); margin-bottom:0.5rem;",
                ),
                # Database path
                Div(
                    Label(
                        "🗄️ Database path",
                        style="font-weight:500; margin-bottom:0.2rem;",
                    ),
                    Input(
                        type="text",
                        name="db_path",
                        value=db_path_val,
                        style="font-family:monospace; font-size:0.75rem; width:100%;",
                    ),
                    P(
                        "Đường dẫn tới file SQLite. VD: ~/roster.db",
                        style="font-size:0.7rem; color:var(--muted);",
                    ),
                    cls="mb-2",
                ),
                # Auto ingest directory
                Div(
                    Label(
                        "📂 Thư mục auto-ingest (Zalo)",
                        style="font-weight:500; margin-bottom:0.2rem;",
                    ),
                    Input(
                        type="text",
                        name="auto_ingest_dir",
                        value=auto_ingest_val,
                        style="font-family:monospace; font-size:0.75rem; width:100%;",
                    ),
                    P(
                        "Thư mục tải xuống Zalo để quét file tự động.",
                        style="font-size:0.7rem; color:var(--muted);",
                    ),
                    cls="mb-2",
                ),
                # Export directory
                Div(
                    Label(
                        "📤 Thư mục xuất file",
                        style="font-weight:500; margin-bottom:0.2rem;",
                    ),
                    Input(
                        type="text",
                        name="export_dir",
                        value=export_val,
                        style="font-family:monospace; font-size:0.75rem; width:100%;",
                    ),
                    P(
                        "Nơi lưu file iCal/CSV xuất ra.",
                        style="font-size:0.7rem; color:var(--muted);",
                    ),
                    cls="mb-2",
                ),
                # Static HTML output directory
                Div(
                    Label(
                        "📖 Thư mục HTML tĩnh",
                        style="font-weight:500; margin-bottom:0.2rem;",
                    ),
                    Input(
                        type="text",
                        name="static_html_output_dir",
                        value=static_output_val,
                        style="font-family:monospace; font-size:0.75rem; width:100%;",
                    ),
                    P(
                        "Nơi lưu file schedule.html để xem nhanh.",
                        style="font-size:0.7rem; color:var(--muted);",
                    ),
                    cls="mb-2",
                ),
                # Processed archive directory
                Div(
                    Label(
                        "📦 Thư mục lưu file đã xử lý",
                        style="font-weight:500; margin-bottom:0.2rem;",
                    ),
                    Input(
                        type="text",
                        name="processed_archive_dir",
                        value=processed_val,
                        style="font-family:monospace; font-size:0.75rem; width:100%;",
                    ),
                    P(
                        "Thư mục con lưu file roster đã ingest (trong thư mục auto-ingest).",
                        style="font-size:0.7rem; color:var(--muted);",
                    ),
                    cls="mb-2",
                ),
                cls="card mb-3",
            ),
            # Aliases section
            Div(
                Label("🏷️ Biệt danh", style="font-weight:500; margin-bottom:0.3rem;"),
                Textarea(
                    aliases_val,
                    name="aliases",
                    rows=2,
                    style="font-family:monospace; font-size:0.8rem; width:100%; resize:vertical;",
                ),
                P(
                    "Phân cách bằng dấu phẩy. VD: Nguyễn Văn A, VAN A, a.nv",
                    style="font-size:0.7rem; color:var(--muted); margin-top:0.2rem;",
                ),
                cls="card mb-3",
            ),
            # Aircraft type editor section
            Div(
                H5("✈️ Loại máy bay"),
                P(
                    "Tùy chỉnh màu nền cho loại máy bay trong bảng chuyến bay.",
                    style="font-size:0.8rem; color:var(--muted); margin-bottom:0.5rem;",
                ),
                # Dark red - Airbus
                Div(
                    Label(
                        "🔴 Airbus (Đỏ đậm)",
                        style="font-weight:500; margin-bottom:0.2rem; color:#ef4444;",
                    ),
                    Textarea(
                        ",".join(aircraft_config.get("airbus", [])),
                        name="aircraft_airbus",
                        rows=1,
                        style="font-family:monospace; font-size:0.75rem; width:100%; resize:vertical;",
                    ),
                    cls="mb-2",
                ),
                # Dark blue - Boeing
                Div(
                    Label(
                        "🔵 Boeing (Xanh đậm)",
                        style="font-weight:500; margin-bottom:0.2rem; color:#3b82f6;",
                    ),
                    Textarea(
                        ",".join(aircraft_config.get("boeing", [])),
                        name="aircraft_boeing",
                        rows=1,
                        style="font-family:monospace; font-size:0.75rem; width:100%; resize:vertical;",
                    ),
                    cls="mb-2",
                ),
                # Dark green - Other
                Div(
                    Label(
                        "🟢 Khác (Xanh lá đậm)",
                        style="font-weight:500; margin-bottom:0.2rem; color:#22c55e;",
                    ),
                    Textarea(
                        ",".join(aircraft_config.get("other", [])),
                        name="aircraft_other",
                        rows=1,
                        style="font-family:monospace; font-size:0.75rem; width:100%; resize:vertical;",
                    ),
                    cls="mb-2",
                ),
                P(
                    "Các loại không có trong danh sách sẽ không có màu. Tự động nhận diện biến thể (A330-200 → A330).",
                    style="font-size:0.7rem; color:var(--muted); margin-top:0.2rem;",
                ),
                cls="card mb-3",
            ),
            # Static HTML Viewer settings
            Div(
                H5("📖 Xem lịch tĩnh"),
                P(
                    "Tạo file HTML tĩnh để xem nhanh qua Termux Widget. Không cần mở app.",
                    style="font-size:0.8rem; color:var(--muted); margin-bottom:0.5rem;",
                ),
                # Scope radio buttons
                Div(
                    Label("Phạm vi:", style="font-weight:500; margin-bottom:0.3rem;"),
                    # Radio options
                    Div(
                        Input(
                            type="radio",
                            id="scope_all",
                            name="static_html_scope",
                            value="all",
                            **(
                                {"checked": ""}
                                if config.get("static_html_scope") == "all"
                                else {}
                            ),
                        ),
                        Label(
                            "Tất cả", for_="scope_all", style="margin-right:0.75rem;"
                        ),
                        Input(
                            type="radio",
                            id="scope_month",
                            name="static_html_scope",
                            value="current_month",
                            **(
                                {"checked": ""}
                                if config.get("static_html_scope")
                                in ("current_month", None)
                                else {}
                            ),
                        ),
                        Label(
                            "Tháng này",
                            for_="scope_month",
                            style="margin-right:0.75rem;",
                        ),
                        Input(
                            type="radio",
                            id="scope_latest",
                            name="static_html_scope",
                            value="latest",
                            **(
                                {"checked": ""}
                                if config.get("static_html_scope") == "latest"
                                else {}
                            ),
                        ),
                        Label(
                            "Mới nhất",
                            for_="scope_latest",
                            style="margin-right:0.75rem;",
                        ),
                        Input(
                            type="radio",
                            id="scope_n",
                            name="static_html_scope",
                            value="latest_n",
                            **(
                                {"checked": ""}
                                if config.get("static_html_scope") == "latest_n"
                                else {}
                            ),
                        ),
                        Label("N mục mới nhất:", for_="scope_n"),
                        Input(
                            type="number",
                            id="scope_count",
                            name="static_html_count",
                            value=str(config.get("static_html_count", 5)),
                            min="1",
                            max="100",
                            style="width:4rem; margin-left:0.3rem;",
                        ),
                        style="display:flex; flex-wrap:wrap; align-items:center; gap:0.3rem; font-size:0.8rem;",
                    ),
                    style="margin-bottom:0.5rem;",
                ),
                cls="card mb-3",
            ),
            # Flight Delay Auto-Sync toggle (radio button pattern like static HTML)
            Div(
                H5("Quét web sân bay"),
                P(
                    "Tự động cập nhật giờ bay và quầy check-in từ web sân bay.",
                    style="font-size:0.8rem; color:var(--muted); margin-bottom:0.5rem;",
                ),
                # Radio buttons for On/Off
                Div(
                    Label("Trạng thái:", style="font-weight:500; margin-bottom:0.3rem;"),
                    Div(
                        Input(
                            type="radio",
                            id="flight-sync-on",
                            name="enable_flight_sync",
                            value="1",
                            **({"checked": ""} if flight_sync_scope else {}),
                        ),
                        Label("Bật", for_="flight-sync-on", style="margin-right:0.75rem;"),
                        Input(
                            type="radio",
                            id="flight-sync-off",
                            name="enable_flight_sync",
                            value="0",
                            **({"checked": ""} if not flight_sync_scope else {}),
                        ),
                        Label("Tắt", for_="flight-sync-off", style="margin-right:0.75rem;"),
                        style="display:flex; align-items:center; gap:0.5rem; font-size:0.8rem;",
                    ),
                    style="margin-bottom:0.5rem;",
                ),
                cls="mb-3",
            ),
            # Save button - use hx-headers to ensure token is sent
            Button(
                "💾 Lưu tất cả thay đổi",
                cls="btn-act",
                style="width:100%; margin-bottom:1rem;",
            ),
            hx_post="/settings",
            hx_target="body",
            hx_swap="outerHTML",
        ),
        # Static HTML Viewer generate section
        Div(
            H5("🔄 Tạo file xem lịch tĩnh"),
            P(
                "Nhấn nút để tạo file HTML từ cài đặt đã lưu.",
                style="font-size:0.8rem; color:var(--muted); margin-bottom:0.5rem;",
            ),
            Button(
                "🔄 Tạo file HTML",
                hx_post="/export/html",
                hx_target="#static-viewer-status",
                cls="btn-act",
                style="width:100%;",
            ),
            Div(id="static-viewer-status"),
            P(
                "File: schedule.html (mở nhanh qua Termux Widget)",
                style="font-size:0.7rem; color:var(--muted); margin-top:0.3rem;",
            ),
            cls="card mb-3",
        ),
        # Data section
        Div(
            H5("📊 Dữ liệu"),
            P(
                "Xóa toàn bộ lịch làm việc đã lưu.",
                style="font-size:0.8rem; color:var(--muted); margin-bottom:0.5rem;",
            ),
            Button(
                "🗑️ Xóa tất cả dữ liệu",
                hx_post="/clear-data",
                hx_confirm="Xóa tất cả lịch làm việc? Không thể hoàn tác.",
                cls="btn-act btn-del",
                style="width:100%;",
            ),
            cls="card mb-3",
        ),
        # Export section
        Div(
            H5("📤 Xuất dữ liệu"),
            P(
                "Tải xuống lịch làm việc dưới định dạng khác.",
                style="font-size:0.8rem; color:var(--muted); margin-bottom:0.5rem;",
            ),
            Div(
                A("📅 iCal", href="/export/ical", cls="button outline btn-act"),
                A("📊 CSV", href="/export/csv", cls="button outline btn-act"),
                cls="btn-row",
            ),
            cls="card",
        ),
    )
    return layout(content)


@rt("/clear-data", methods=["post"])
def post_clear_data():
    clear_db()
    bump_db_rev()
    return get_settings()


@rt("/export/ical")
def get_export_ical():
    content = generate_ical_content()
    if not content:
        return "Không có dữ liệu để xuất."
    return Response(
        content,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=roster.ics"},
    )


@rt("/export/csv")
def get_export_csv():
    content = generate_csv_content()
    if not content:
        return "Không có dữ liệu để xuất."
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=roster.csv"},
    )


@rt("/export/html", methods=["post"])
def post_export_html():
    """Manually trigger static HTML generation with current scope settings."""
    try:
        from export import generate_html as gen_static_html

        config = get_config()
        scope = config.get("static_html_scope", "current_month")
        count = config.get("static_html_count", 5)
        result = gen_static_html(scope=scope, count=count)

        if result["success"]:
            return Div(
                P(
                    f"✅ Đã tạo: {result['entry_count']} mục → schedule.html",
                    cls="text-green-700",
                ),
                id="static-viewer-status",
            )
        else:
            return Div(
                P(
                    f"❌ Lỗi: {html.escape(str(result['error']), quote=True)}",
                    cls="text-red-600",
                ),
                id="static-viewer-status",
            )
    except Exception as e:
        return Div(
            P(f"❌ Lỗi: {html.escape(str(e), quote=True)}", cls="text-red-600"),
            id="static-viewer-status",
        )


@rt("/flight/preview")
def get_flight_preview():
    """Return the API preview card."""
    with _flight_api_cache_lock:
        cache_copy = dict(_flight_api_cache)
    return ApiPreviewCard(cache=cache_copy)


@rt("/flight/preview/fetch", methods=["post"])
def post_flight_fetch():
    """Fetch fresh API data and refresh the preview card."""
    _refresh_api_cache(days=3)
    bump_db_rev()
    with _flight_api_cache_lock:
        cache_copy = dict(_flight_api_cache)
    return ApiPreviewCard(cache=cache_copy)


@rt("/shutdown", methods=["post"])
def post_shutdown():
    import os
    import signal

    pid = os.getpid()
    print(f"Exiting application (PID: {pid})...")
    SHUTDOWN_EVENT.set()

    # Forcefully exit and also close Termux session
    def do_exit():
        import time
        import subprocess

        time.sleep(0.3)  # Allow response to be sent
        # Kill the parent shell to close Termux session
        # This works because we're in a process group with the shell
        try:
            # Get parent process ID and kill it (closes Termux session)
            ppid = os.getppid()
            os.kill(ppid, signal.SIGTERM)
        except:
            pass
        # Finally, kill ourselves with SIGKILL (immediate, no cleanup)
        os.kill(pid, signal.SIGKILL)

    threading.Thread(target=do_exit, daemon=False).start()
    return "Shutting down..."
