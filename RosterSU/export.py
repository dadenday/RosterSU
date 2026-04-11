"""
Export functionality for RosterMaster.

Extracted from roster_single_user.py for maintainability.
Provides iCal and CSV export functions.
"""

import io
import csv
import json
from datetime import datetime, timedelta

# Import from config
from config import RE_TIME
import os
from config import (
    STATIC_HTML_OUTPUT_DIR, STATIC_HTML_FILENAME, STATIC_HTML_META_FILENAME
)

# Import from main module (requires lazy loading to avoid circular imports)
# These will be set when the module is initialized
_load_history = None
sanitize_formula = None
_export_debug_log = None


def _init_exports(load_history_fn, sanitize_fn, debug_log_fn=None) -> None:
    """Initialize export module with dependencies from main module."""
    global _load_history, sanitize_formula, _export_debug_log
    _load_history = load_history_fn
    sanitize_formula = sanitize_fn
    _export_debug_log = debug_log_fn


def export_snapshot(scope="current_month", count=5):
    """
    Query DB and return roster data for static HTML generation.
    
    Args:
        scope: "all", "current_month", "latest", or "latest_n"
        count: Number of entries for "latest_n" mode
    
    Returns:
        list of dict rows from work_schedule table
    """
    if _load_history is None:
        raise RuntimeError("Export module not initialized. Call init_exports() first.")
    
    if scope == "all":
        # Load all history (use large limit)
        return _load_history(limit=9999)
    elif scope == "current_month":
        now = datetime.now()
        month_str = now.strftime("%Y-%m")
        return _load_history(limit=9999, filter_month=month_str)
    elif scope == "latest":
        return _load_history(limit=1)
    elif scope == "latest_n":
        return _load_history(limit=max(1, count))
    else:
        # Fallback to current month
        now = datetime.now()
        month_str = now.strftime("%Y-%m")
        return _load_history(limit=9999, filter_month=month_str)


def _render_frozen_card(row):
    """
    Render a single roster entry as frozen HTML card.
    Reuses the same rendering logic as components.py RosterCard.

    Args:
        row: dict with keys "work_date", "full_data", "last_updated"

    Returns:
        str: HTML fragment for this card
    """
    import html as html_mod
    import re

    date_str = row["work_date"]
    data = json.loads(row["full_data"])
    shift_raw = data.get("shift", "")
    flights = data.get("flights", [])

    # Format date (Vietnamese style: T2 10.02.26)
    try:
        dt = datetime.strptime(date_str, "%d.%m.%Y")
        days = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
        date_display = f"{days[dt.weekday()]} {dt.strftime('%d.%m.%y')}"
    except Exception:
        date_display = date_str

    # Format shift with zone extraction
    zone = ""
    time_part = shift_raw or "--"
    zone_match = re.search(r'(.*)\((.*)\)', time_part)
    if zone_match:
        time_part = zone_match.group(1).strip()
        zone = zone_match.group(2).strip().capitalize()

    shift_display = date_display
    if time_part in ("OFF", "HỌC"):
        shift_display = f"{date_display} | {time_part}"
    else:
        shift_display = f"{date_display} | {time_part}"
        if zone:
            shift_display += f" | {zone}"

    # Determine card color class
    if shift_raw == "OFF":
        color_class = "rc-off"
    elif shift_raw and "HỌC" in shift_raw:
        color_class = "rc-edu"
    elif shift_raw:
        color_class = "rc-on"
    else:
        color_class = "rc-nil"

    # Build card HTML
    card_html = f'''
    <details class="rd" {"open" if flights else ""}>
        <summary>
            <div class="rc {color_class}">
                <div class="rc-content">
                    <div class="rc-date-col">
                        <p class="rc-date">{html_mod.escape(shift_display, quote=True)}</p>
                    </div>
                </div>
    '''

    if flights:
        card_html += f'                <span class="rc-badge">{len(flights)} chuyến</span>\n'

    card_html += '''            </div>
        </summary>'''

    # Flight table
    if flights:
        # Sort flights by Open time (same logic as components.py)
        def _sort_flight_key(f):
            open_t = f.get("Open", "")
            time_match = re.search(r'(\d{1,2}[:hH]\d{2})', open_t)
            if time_match:
                t = time_match.group(1).replace("h", ":").replace(".", ":")
                parts = t.split(":")
                return int(parts[0]) * 60 + int(parts[1]) if len(parts) >= 2 else 9999
            return 9999

        sorted_flights = sorted(flights, key=_sort_flight_key)

        # Determine aircraft type CSS class
        def _get_flight_type_class(flight_type):
            if not flight_type:
                return ""
            ft_upper = flight_type.upper()
            # Check Airbus (first 3 chars for A3xx)
            if ft_upper.startswith(("A30", "A31", "A32", "A33", "A34", "A35", "A38")):
                return "flight-airbus"
            # Check Boeing (first 3 chars for B7xx)
            if ft_upper.startswith(("B74", "B76", "B77", "B78", "B73")):
                return "flight-boeing"
            return "flight-other"

        card_html += '''
        <div class="fd">
            <table>
                <thead>
                    <tr>
                        <th>🕐</th>
                        <th>🔒</th>
                        <th>✈️</th>
                        <th>🛫</th>
                        <th>🚪</th>
                        <th>🔧</th>
                        <th>👥</th>
                        <th>🏷️</th>
                    </tr>
                </thead>
                <tbody>
        '''

        for f in sorted_flights:
            ftype = f.get("Type", "")
            type_class = _get_flight_type_class(ftype)
            row_class = f' class="{type_class}"' if type_class else ""

            card_html += f'''
                    <tr{row_class}>
                        <td>{html_mod.escape(f.get("Open", ""), quote=True)}</td>
                        <td>{html_mod.escape(f.get("Close", ""), quote=True)}</td>
                        <td>{html_mod.escape(f.get("Call", ""), quote=True)}</td>
                        <td>{html_mod.escape(f.get("Route", ""), quote=True)}</td>
                        <td>{html_mod.escape(f.get("Bay", ""), quote=True)}</td>
                        <td>{html_mod.escape(ftype, quote=True)}</td>
                        <td>{html_mod.escape(f.get("Names", ""), quote=True)}</td>
                        <td>{html_mod.escape(f.get("ckRow", ""), quote=True)}</td>
                    </tr>
            '''

        card_html += '''
                </tbody>
            </table>
        </div>'''

    card_html += '\n    </details>'
    return card_html


def generate_html(scope="current_month", count=5):
    """
    Generate frozen HTML viewer file and metadata JSON.

    Args:
        scope: "all", "current_month", "latest", or "latest_n"
        count: Number of entries for "latest_n" mode

    Returns:
        dict with keys "success", "file_path", "entry_count", "error"
    """
    try:
        # Get snapshot data
        rows = export_snapshot(scope=scope, count=count)

        if not rows:
            # Write minimal "no data" HTML
            html_content = _build_empty_html()
            meta = {
                "generated_at": datetime.now().isoformat(),
                "scope": scope,
                "entry_count": 0,
                "status": "empty"
            }
        else:
            # Build cards
            cards_html = "\n".join(_render_frozen_card(r) for r in rows)

            # Date range for title
            first_date = rows[-1]["work_date"] if rows else ""
            last_date = rows[0]["work_date"] if rows else ""
            date_range = f"{first_date} → {last_date}" if first_date != last_date else first_date

            scope_labels = {
                "all": "Tất cả",
                "current_month": "Tháng này",
                "latest": "Mới nhất",
                "latest_n": f"{count} mới nhất"
            }
            scope_label = scope_labels.get(scope, scope)

            html_content = _build_full_html(cards_html, date_range, scope_label, len(rows))
            meta = {
                "generated_at": datetime.now().isoformat(),
                "scope": scope,
                "scope_label": scope_label,
                "entry_count": len(rows),
                "date_range": date_range,
                "status": "ok"
            }

        # Write files
        output_dir = STATIC_HTML_OUTPUT_DIR
        html_path = os.path.join(output_dir, STATIC_HTML_FILENAME)
        meta_path = os.path.join(output_dir, STATIC_HTML_META_FILENAME)

        os.makedirs(output_dir, exist_ok=True)

        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        os.chmod(html_path, 0o644)

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        os.chmod(meta_path, 0o644)

        return {
            "success": True,
            "file_path": html_path,
            "entry_count": meta["entry_count"],
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "file_path": None,
            "entry_count": 0,
            "error": str(e)
        }


def _build_full_html(cards_html, date_range, scope_label, count):
    """Build the complete HTML document with inline CSS."""
    return f'''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Lịch — {date_range}</title>
    <style>
:root {{
    --space-1: 0.15rem; --space-2: 0.3rem; --space-3: 0.5rem; --space-4: 0.7rem;
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
    --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1);
    --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1);
    --radius-sm: 0.375rem; --radius-md: 0.5rem; --radius-lg: 0.75rem;
    --transition-fast: 150ms ease; --transition-base: 200ms ease;
}}
* {{ box-sizing: border-box; }}
body {{
    font-size: 1rem; line-height: 1.5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: linear-gradient(180deg, #f8fafc 0%, #f1f5f9 100%);
    min-height: 100vh; margin: 0; padding: 1rem;
    color: #1e293b;
}}
summary::after {{ content: none !important; display: none !important; }}
h1 {{ font-size: 1.38rem; margin: 0 0 0.25rem; font-weight: 700; }}
header {{ margin-bottom: 1rem; padding-bottom: 0.75rem; border-bottom: 1px solid rgba(148,163,184,0.3); }}
header p {{ font-size: 0.86rem; color: #64748b; margin: 0; }}
.rd {{ margin-bottom: 0.5rem; border-radius: var(--radius-lg); overflow: hidden; width: 100%; }}
.rc {{
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.5rem 0.75rem; border-radius: var(--radius-lg);
    color: #fff; position: relative; overflow: hidden;
    box-shadow: var(--shadow-md);
    width: 100%;
}}
.rc::before {{
    content: ""; position: absolute; inset: 0;
    background: linear-gradient(180deg, rgba(255,255,255,0.15) 0%, transparent 50%);
    pointer-events: none;
}}
.rc-on  {{ background: linear-gradient(135deg, #22c55e 0%, #16a34a 50%, #15803d 100%); }}
.rc-off {{ background: linear-gradient(135deg, #f87171 0%, #ef4444 50%, #dc2626 100%); }}
.rc-edu {{ background: linear-gradient(135deg, #60a5fa 0%, #3b82f6 50%, #2563eb 100%); }}
.rc-nil {{ background: linear-gradient(135deg, #94a3b8 0%, #64748b 50%, #475569 100%); }}
.rc-content {{ flex: 1; min-width: 0; z-index: 1; display: flex; align-items: center; gap: 0.75rem; }}
.rc-date-col {{ min-width: 4.5rem; }}
.rc-date {{ font-size: 0.9rem; color: #fff; text-transform: uppercase; letter-spacing: 0.05rem; margin: 0; font-weight: 600; text-shadow: 0 1px 2px rgba(0,0,0,0.2); }}
.rc-badge {{
    background: rgba(255,255,255,0.25); color: #fff;
    padding: 0.2rem 0.5rem; border-radius: 9999px;
    font-size: 0.6rem; font-weight: 600; white-space: nowrap;
    z-index: 1; backdrop-filter: blur(4px); flex-shrink: 0;
}}
details summary {{ list-style: none; cursor: pointer; display: flex; padding: 0; -webkit-appearance: none; appearance: none; }}
summary::-webkit-details-marker {{ display: none !important; }}
summary::marker {{ content: '' !important; }}
.fd {{
    padding: 0.4rem 0.6rem; font-size: 0.86rem;
    background: rgba(255,255,255,0.95);
    border: 1px solid rgba(148,163,184,0.25); border-top: none;
    border-radius: 0 0 var(--radius-lg) var(--radius-lg);
    box-shadow: var(--shadow-sm); width: 100%; overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}}
.fd table {{ font-size: 0.86rem; width: 100%; min-width: max-content; table-layout: auto; border-collapse: collapse; }}
.fd th {{ font-weight: 600; color: #1e293b; border-bottom: 1px solid rgba(148,163,184,0.2); padding: 0.3rem 0.5rem; white-space: nowrap; font-size: 0.8rem; }}
.fd td {{ padding: 0.25rem 0.5rem; color: #475569; white-space: nowrap; }}
.fd tr.flight-airbus {{ background: #7f1d1d !important; }}
.fd tr.flight-airbus td {{ color: #fecaca !important; }}
.fd tr.flight-boeing {{ background: #1e3a5f !important; }}
.fd tr.flight-boeing td {{ color: #bfdbfe !important; }}
.fd tr.flight-other {{ background: #14532d !important; }}
.fd tr.flight-other td {{ color: #bbf7d0 !important; }}
.empty {{ text-align: center; padding: 2rem 1.5rem; border: 2px dashed rgba(148,163,184,0.4); border-radius: var(--radius-lg); background: rgba(255,255,255,0.5); }}
.empty p:first-child {{ font-weight: 600; margin: 0; font-size: 0.95rem; }}
.theme-toggle {{
    position: fixed; top: 0.75rem; right: 0.75rem; z-index: 100;
    background: rgba(148,163,184,0.2); border: 1px solid rgba(148,163,184,0.3);
    border-radius: 9999px; width: 2.25rem; height: 2.25rem;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; font-size: 1.1rem; padding: 0;
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    transition: background var(--transition-fast), border-color var(--transition-fast);
}}
.theme-toggle:hover {{ background: rgba(148,163,184,0.35); }}
/* === Dark Theme === */
[data-theme='dark'] body {{
    background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
    color: #e2e8f0;
}}
[data-theme='dark'] header {{ border-bottom-color: rgba(71,85,105,0.4); }}
[data-theme='dark'] header p {{ color: #94a3b8; }}
[data-theme='dark'] h1 {{ color: #f1f5f9; }}
[data-theme='dark'] .fd {{
    background: #000 !important; border-color: rgba(71,85,105,0.4) !important;
}}
[data-theme='dark'] .fd th {{ color: #f1f5f9 !important; border-bottom-color: rgba(71,85,105,0.4); }}
[data-theme='dark'] .fd td {{ color: #e2e8f0 !important; }}
[data-theme='dark'] .fd tr.flight-airbus {{ background: #991b1b !important; }}
[data-theme='dark'] .fd tr.flight-airbus td {{ color: #fecaca !important; }}
[data-theme='dark'] .fd tr.flight-boeing {{ background: #1e3a8a !important; }}
[data-theme='dark'] .fd tr.flight-boeing td {{ color: #bfdbfe !important; }}
[data-theme='dark'] .fd tr.flight-other {{ background: #166534 !important; }}
[data-theme='dark'] .fd tr.flight-other td {{ color: #bbf7d0 !important; }}
[data-theme='dark'] .empty {{
    background: rgba(30,41,59,0.5); border-color: rgba(71,85,105,0.4);
}}
[data-theme='dark'] .empty p:last-child {{ color: #94a3b8; }}
@media (prefers-color-scheme: dark) {{
    body {{ background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%); color: #e2e8f0; }}
    header {{ border-bottom-color: rgba(71,85,105,0.4); }}
    header p {{ color: #94a3b8; }}
    h1 {{ color: #f1f5f9; }}
    .fd {{ background: #000 !important; border-color: rgba(71,85,105,0.4) !important; }}
    .fd th {{ color: #f1f5f9 !important; border-bottom-color: rgba(71,85,105,0.4); }}
    .fd td {{ color: #e2e8f0 !important; }}
    .fd tr.flight-airbus {{ background: #991b1b !important; }}
    .fd tr.flight-airbus td {{ color: #fecaca !important; }}
    .fd tr.flight-boeing {{ background: #1e3a8a !important; }}
    .fd tr.flight-boeing td {{ color: #bfdbfe !important; }}
    .fd tr.flight-other {{ background: #166534 !important; }}
    .fd tr.flight-other td {{ color: #bbf7d0 !important; }}
    .empty {{ background: rgba(30,41,59,0.5); border-color: rgba(71,85,105,0.4); }}
    .empty p:last-child {{ color: #94a3b8; }}
}}
    </style>
</head>
<body>
    <header>
        <h1>Lịch làm việc</h1>
        <p>Phạm vi: {scope_label} | {count} mục | Cập nhật: {datetime.now().strftime("%H:%M %d.%m.%Y")}</p>
    </header>
    <button class="theme-toggle" id="themeBtn" aria-label="Toggle theme">🌙</button>
    <main>
{cards_html}
    </main>
    <script>
(function(){{
    var html = document.documentElement;
    var btn = document.getElementById('themeBtn');
    var saved = localStorage.getItem('roster-theme');
    var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    if(saved){{ html.setAttribute('data-theme', saved); }}
    else if(prefersDark){{ html.setAttribute('data-theme','dark'); }}
    btn.textContent = html.getAttribute('data-theme')==='dark' ? '☀️' : '🌙';
    btn.addEventListener('click', function(){{
        var next = html.getAttribute('data-theme')==='dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
        btn.textContent = next==='dark' ? '☀️' : '🌙';
        localStorage.setItem('roster-theme', next);
    }});
}})();
(function(){{
    var details = document.querySelectorAll('.rd');
    details.forEach(function(d){{
        d.addEventListener('toggle', function(e){{
            if(e.newState === 'open'){{
                details.forEach(function(other){{
                    if(other !== d && other.open) other.open = false;
                }});
            }}
        }});
    }});
}})();
    </script>
</body>
</html>'''


def _build_empty_html():
    """Build minimal HTML for empty state."""
    return '''<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Lịch — Không có dữ liệu</title>
    <style>
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f8fafc; min-height: 100vh; margin: 0; padding: 1rem; color: #1e293b; }
.empty { text-align: center; padding: 2rem; border: 2px dashed rgba(148,163,184,0.4); border-radius: 0.75rem; background: rgba(255,255,255,0.5); }
.empty p:first-child { font-weight: 600; margin: 0; font-size: 0.95rem; }
@media (prefers-color-scheme: dark) {
    body { background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%); color: #e2e8f0; }
    .empty { background: rgba(30,41,59,0.5); border-color: rgba(71,85,105,0.4); }
    .empty p:last-child { color: #94a3b8; }
}
    </style>
</head>
<body>
    <div class="empty">
        <p>Chưa có dữ liệu lịch</p>
        <p style="font-size:0.8rem; color:#64748b; margin-top:0.5rem;">Hãy tải lên file xếp lịch để xem tại đây.</p>
    </div>
</body>
</html>'''


def generate_ical_content():
    """Generate .ics content string."""
    if _load_history is None:
        raise RuntimeError("Export module not initialized. Call init_exports() first.")

    rows = _load_history()
    if not rows:
        return None

    ical_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RosterMaster//v4.2//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    count = 0
    for r in rows:
        try:
            date_str = r["work_date"]
            data = json.loads(r["full_data"])
            flights = data.get("flights", [])

            dt_obj = datetime.strptime(date_str, "%d.%m.%Y")

            for f in flights:
                t_open = f.get("Open", "")
                t_close = f.get("Close", "")

                # Only export flights with valid times
                if not t_open or not t_close:
                    continue

                open_match = RE_TIME.search(t_open)
                close_match = RE_TIME.search(t_close)

                if not open_match or not close_match:
                    continue

                open_time_parts = (
                    open_match.group(1).replace("H", ":").replace(".", ":").split(":")
                )
                close_time_parts = (
                    close_match.group(1).replace("H", ":").replace(".", ":").split(":")
                )

                if len(open_time_parts) < 2 or len(close_time_parts) < 2:
                    continue

                h_o, m_o = int(open_time_parts[0]), int(open_time_parts[1])
                h_c, m_c = int(close_time_parts[0]), int(close_time_parts[1])

                dt_start = dt_obj.replace(hour=h_o, minute=m_o)
                dt_end = dt_obj.replace(hour=h_c, minute=m_c)

                # Handle overnight shifts
                if dt_end < dt_start:
                    dt_end = dt_end + timedelta(days=1)

                ts_start = dt_start.strftime("%Y%m%dT%H%M%S")
                ts_end = dt_end.strftime("%Y%m%dT%H%M%S")

                summary = f"{f.get('Call', '')} ({f.get('Route', '')})"
                desc = f"Bay: {f.get('Bay', '')}. Type: {f.get('Type', '')}"

                # Sanitize fields to prevent formula injection
                sanitized_summary = sanitize_formula(summary)
                sanitized_desc = sanitize_formula(desc)

                ical_lines.append("BEGIN:VEVENT")
                ical_lines.append(f"DTSTART:{ts_start}")
                ical_lines.append(f"DTEND:{ts_end}")
                ical_lines.append(f"SUMMARY:{sanitized_summary}")
                ical_lines.append(f"DESCRIPTION:{sanitized_desc}")
                ical_lines.append("END:VEVENT")
                count += 1
        except Exception as e:
            if _export_debug_log:
                _export_debug_log(f"iCal export error for row {r}: {e}")
            continue

    ical_lines.append("END:VCALENDAR")

    return "\r\n".join(ical_lines)


def generate_csv_content():
    """Generate .csv content string."""
    if _load_history is None:
        raise RuntimeError("Export module not initialized. Call init_exports() first.")

    rows = _load_history()
    if not rows:
        return None

    # Create an in-memory string buffer
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(
        [
            "Date",
            "Shift",
            "Flight Type",
            "Callsign",
            "Route",
            "Open Time",
            "Close Time",
            "Bay",
            "Names",
            "Zone",
        ]
    )

    # Write data rows
    for r in rows:
        try:
            date_str = r["work_date"]
            data = json.loads(r["full_data"])
            shift = data.get("shift", "")

            flights = data.get("flights", [])

            if not flights:
                # Write a row even if there are no flights
                writer.writerow(
                    [
                        sanitize_formula(field)
                        for field in [date_str, shift, "", "", "", "", "", "", "", ""]
                    ]
                )
            else:
                for f in flights:
                    writer.writerow(
                        [
                            sanitize_formula(field)
                            for field in [
                                date_str,
                                shift,
                                f.get("Type", ""),
                                f.get("Call", ""),
                                f.get("Route", ""),
                                f.get("Open", ""),
                                f.get("Close", ""),
                                f.get("Bay", ""),
                                f.get("Names", ""),
                                f.get("Zone", ""),
                            ]
                        ]
                    )
        except Exception as e:
            if _export_debug_log:
                _export_debug_log(f"CSV export error for row {r}: {e}")
            continue

    csv_content = output.getvalue()
    output.close()
    return csv_content
