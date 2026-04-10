#!/usr/bin/env python
"""
Roster Parser Test Harness
==========================
Processes all xlsx files from processed_archive/ into a TEST database,
then compares against the main roster_history.db to find:
  1. Files that fail to parse (errors)
  2. Date mismatches (wrong date extracted)
  3. Entry discrepancies (different shift/flights for same date)
  4. Missing entries (in archive but not in main DB, or vice versa)
"""

import os
import sys
import json
import glob
import sqlite3
import hashlib
import io
import time
import traceback

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from config import DB_FILE as MAIN_DB_FILE
from data_types import ParseContext

# Test DB path
TEST_DB_FILE = os.path.join(PROJECT_ROOT, "roster_test.db")

# Archive path
ARCHIVE_DIR = os.path.join(PROJECT_ROOT, "processed_archive")


def init_test_db():
    """Create a fresh test database with the same schema."""
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)

    conn = sqlite3.connect(TEST_DB_FILE)
    conn.execute('PRAGMA journal_mode=WAL;')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS work_schedule
                 (work_date TEXT PRIMARY KEY,
                  full_data TEXT,
                  date_iso TEXT,
                  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()
    print(f"  Created test DB: {TEST_DB_FILE}")


def parse_file_to_testdb(file_path, test_conn):
    """Parse a single file and write results to test DB."""
    filename = os.path.basename(file_path)
    results = []
    error = None
    manifest = None

    try:
        # Import the parsing function
        from roster_single_user import (
            parse_file, compile_alias_regex, consolidate_file_results,
            save_entries_bulk, ParseContext, get_aliases
        )

        aliases = get_aliases()
        alias_regex = compile_alias_regex(aliases)

        with open(file_path, "rb") as f:
            results, error, manifest = parse_file(f, filename, alias_regex)

        if results:
            final = consolidate_file_results(results)
            if manifest:
                ctx = ParseContext(
                    global_date=manifest.global_date,
                    global_date_iso=manifest.global_date_iso,
                    source_filename=manifest.filename,
                    file_id=manifest.file_hash,
                    date_confidence=manifest.confidence_score,
                    date_anomaly=len(manifest.anomalies) > 0,
                    date_candidates=manifest.date_candidates
                )
                save_entries_bulk(final, context=ctx)
            else:
                save_entries_bulk(final)
            return {"status": "ok", "entries": len(final), "date": manifest.global_date if manifest else "N/A"}
        elif error:
            return {"status": "error", "error": str(error)}
        else:
            return {"status": "empty", "error": "No data found"}

    except Exception as e:
        return {"status": "exception", "error": str(e), "traceback": traceback.format_exc()}


def load_db_entries(db_path):
    """Load all entries from a database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT work_date, full_data FROM work_schedule ORDER BY work_date")
    result = {}
    for row in c.fetchall():
        data = json.loads(row["full_data"])
        result[row["work_date"]] = data
    conn.close()
    return result


def compare_databases(main_db, test_db):
    """Compare two databases and report differences."""
    print("\n" + "=" * 60)
    print("DATABASE COMPARISON REPORT")
    print("=" * 60)

    main_entries = load_db_entries(main_db)
    test_entries = load_db_entries(test_db)

    main_dates = set(main_entries.keys())
    test_dates = set(test_entries.keys())

    only_in_main = main_dates - test_dates
    only_in_test = test_dates - main_dates
    common_dates = main_dates & test_dates

    print(f"\nMain DB ({os.path.basename(main_db)}): {len(main_dates)} entries")
    print(f"Test DB ({os.path.basename(test_db)}): {len(test_dates)} entries")
    print(f"\nOnly in Main DB: {len(only_in_main)} dates")
    if only_in_main:
        for d in sorted(only_in_main):
            print(f"  - {d}")

    print(f"\nOnly in Test DB: {len(only_in_test)} dates")
    if only_in_test:
        for d in sorted(only_in_test):
            print(f"  + {d}")

    # Compare common entries
    discrepancies = []
    for date in sorted(common_dates):
        main_data = main_entries[date]
        test_data = test_entries[date]

        # Compare shift
        main_shift = main_data.get("shift", "--")
        test_shift = test_data.get("shift", "--")
        if main_shift != test_shift:
            discrepancies.append({
                "date": date,
                "field": "shift",
                "main": main_shift,
                "test": test_shift
            })

        # Compare flights
        main_flights = main_data.get("flights", [])
        test_flights = test_data.get("flights", [])
        if len(main_flights) != len(test_flights):
            discrepancies.append({
                "date": date,
                "field": "flight_count",
                "main": len(main_flights),
                "test": len(test_flights)
            })
        else:
            for i, (mf, tf) in enumerate(zip(main_flights, test_flights)):
                for key in ["Type", "Call", "Route", "Open", "Close", "Bay", "Names"]:
                    if mf.get(key) != tf.get(key):
                        discrepancies.append({
                            "date": date,
                            "field": f"flights[{i}].{key}",
                            "main": mf.get(key, ""),
                            "test": tf.get(key, "")
                        })

    if discrepancies:
        print(f"\nDiscrepancies in {len(discrepancies)} fields across common dates:")
        for d in discrepancies:
            print(f"  {d['date']} | {d['field']}: main='{d['main']}' vs test='{d['test']}'")
    else:
        print(f"\nAll {len(common_dates)} common entries match perfectly ✅")

    return {
        "only_in_main": len(only_in_main),
        "only_in_test": len(only_in_test),
        "discrepancies": len(discrepancies),
        "common_match": len(common_dates) - len(discrepancies)
    }


def main():
    print("=" * 60)
    print("ROSTER PARSER TEST HARNESS")
    print("=" * 60)

    # Find archive files
    xlsx_files = glob.glob(os.path.join(ARCHIVE_DIR, "*.xlsx"))
    xls_files = glob.glob(os.path.join(ARCHIVE_DIR, "*.xls"))
    csv_files = glob.glob(os.path.join(ARCHIVE_DIR, "*.csv"))
    all_files = sorted(xlsx_files + xls_files + csv_files)

    if not all_files:
        print(f"\nNo archive files found in {ARCHIVE_DIR}")
        sys.exit(1)

    print(f"\nFound {len(all_files)} archive files in {ARCHIVE_DIR}")

    # Initialize test DB
    init_test_db()

    # Connect to test DB for this session
    test_conn = sqlite3.connect(TEST_DB_FILE)
    test_conn.row_factory = sqlite3.Row

    results = {"ok": 0, "error": 0, "empty": 0, "exception": 0}
    errors = []

    print(f"\nProcessing files...")
    start_time = time.time()

    for i, fpath in enumerate(all_files, 1):
        fname = os.path.basename(fpath)
        print(f"  [{i}/{len(all_files)}] {fname}...", end=" ", flush=True)

        result = parse_file_to_testdb(fpath, test_conn)
        status = result["status"]
        results[status] = results.get(status, 0) + 1

        if status == "ok":
            print(f"OK ({result['entries']} entries, date={result['date']})")
        elif status == "error":
            print(f"ERROR: {result['error'][:80]}")
            errors.append({"file": fname, "status": status, "error": result["error"]})
        elif status == "empty":
            print(f"EMPTY: {result['error']}")
            errors.append({"file": fname, "status": status, "error": result["error"]})
        elif status == "exception":
            print(f"EXCEPTION: {result['error'][:80]}")
            errors.append({"file": fname, "status": status, "error": result["error"], "traceback": result.get("traceback")})

    elapsed = time.time() - start_time
    test_conn.close()

    # Summary
    print(f"\n{'=' * 60}")
    print(f"PARSING SUMMARY ({elapsed:.1f}s)")
    print(f"{'=' * 60}")
    print(f"  Successful:  {results['ok']}")
    print(f"  Parse error: {results['error']}")
    print(f"  Empty:       {results['empty']}")
    print(f"  Exception:   {results['exception']}")

    if errors:
        print(f"\n--- Error Details ---")
        for e in errors:
            print(f"\n  File: {e['file']}")
            print(f"  Status: {e['status']}")
            print(f"  Error: {e['error'][:200]}")

    # Compare databases
    main_db = MAIN_DB_FILE
    if os.path.exists(main_db):
        compare_databases(main_db, TEST_DB_FILE)
    else:
        print(f"\nMain DB not found at {main_db}, skipping comparison")
        print(f"Test DB has {len(load_db_entries(TEST_DB_FILE))} entries")


if __name__ == "__main__":
    main()
