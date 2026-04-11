# Bug Fix Report - Silent Failure Issues

**Date:** April 11, 2026  
**Issue:** Auto-scan, auto-ingest, and file upload failing silently on friend's device  
**Status:** ✅ FIXED

---

## Problems Identified

Your friend reported that on his Android/Termux device:
1. ❌ Auto-scan doesn't trigger
2. ❌ Auto-ingest doesn't work
3. ❌ Manual Excel file upload fails
4. ❌ No error messages shown

### Root Cause: **6 Silent Failure Points**

After detailed investigation, we found that errors were occurring but being silently swallowed due to:

---

## Issue 1: Error Swallowing in Scan Thread

**Location:** `routes.py`, `post_scan()` function

**Problem:**
```python
def _scan():
    try:
        _run_ingest_once()
    finally:
        bump_db_rev()  # No exception handling!
```

If `_run_ingest_once()` raised an exception, it was swallowed by the daemon thread with no error reporting.

**Fix:**
```python
def _scan():
    try:
        _run_ingest_once()
    except Exception as e:
        # Now catches and reports errors
        safe_err = html.escape(str(e), quote=True)
        update_status("Error", f"Scan failed: {safe_err}")
        log_debug("scan_thread_error", str(e))
    finally:
        bump_db_rev()
```

---

## Issue 2: Status Overwrite in Finally Block

**Location:** `roster_single_user.py`, `_run_ingest_once()` function

**Problem:**
```python
finally:
    APP.clear_ingest()
    update_status("Idle", "Sẵn sàng")  # ALWAYS overwrites error status!
```

Even if an error status was set, the `finally` block would immediately overwrite it with "Sẵn sàng", making errors invisible to users.

**Fix:**
```python
error_occurred = False
try:
    # ... code ...
except Exception as e:
    error_occurred = True
    update_status("Error", f"Scan failed: {safe_err}")
finally:
    APP.clear_ingest()
    # Only reset if no error occurred
    if not error_occurred:
        update_status("Idle", "Sẵn sàng")
```

---

## Issue 3: Inconsistent Return Values from parse_file()

**Location:** `roster_single_user.py`, `parse_file()` function

**Problem:**
```python
except Exception as e:
    return None, str(e)  # Returns 2 values!
```

But callers expected 3 values:
```python
p_results, p_err, manifest = parse_file(...)  # Expects 3 values
```

This caused `ValueError: not enough values to unpack`, wrapping the real error message.

**Fix:**
```python
except Exception as e:
    # Always return 3 values to match caller expectations
    log_debug("parse_file_exception", {
        "file": filename,
        "error": str(e),
    })
    return None, str(e), None
```

---

## Issue 4: Missing Directory Visibility

**Location:** `roster_single_user.py`, `_run_ingest_once()` function

**Problem:**
```python
if not os.path.exists(AUTO_INGEST_DIR):
    update_status("Idle", "Monitoring folder...")  # No error shown!
    return
```

If the Zalo download folder didn't exist (common on Termux without `termux-setup-storage`), users saw no error message.

**Fix:**
```python
if not os.path.exists(AUTO_INGEST_DIR):
    # Now shows actual path and helpful hint
    update_status("Error", f"Folder not found: {AUTO_INGEST_DIR}")
    log_debug("auto_ingest_dir_missing", {
        "path": AUTO_INGEST_DIR,
        "hint": "Run 'termux-setup-storage' and grant storage permission",
    })
    error_occurred = True
    return
```

---

## Issue 5: Silent File Rejection

**Location:** `roster_single_user.py`, `_run_ingest_once()` function

**Problem:**
```python
for f in target_files:
    try:
        safe_path(AUTO_INGEST_DIR, f)
        safe_files.append(f)
    except ValueError:
        continue  # Silently drops files!
```

Files that failed path validation were silently dropped with no logging or user feedback.

**Fix:**
```python
dropped_files = []
for f in target_files:
    try:
        safe_path(AUTO_INGEST_DIR, f)
        safe_files.append(f)
    except ValueError as e:
        dropped_files.append(os.path.basename(f))
        log_debug("safe_path_rejected", {
            "file": os.path.basename(f),
            "reason": str(e),
        })

if dropped_files:
    log_debug("safe_path_dropped_files", {
        "count": len(dropped_files),
        "files": dropped_files[:5],
    })
```

---

## Issue 6: Debug Logging Suppressed During Ingest

**Location:** `roster_single_user.py`, `log_debug()` function

**Problem:**
```python
critical_events = {
    "db_write_error",
    "bulk_db_error",
    "runtime_error",
    "auth_denied",
    "file_loop_error",
}
if APP.is_ingest_running() and not DEBUG_ENABLED and event not in critical_events:
    return  # Drops most debug events!
```

During background ingest, most debug events were silently dropped, making it impossible to diagnose issues.

**Fix:**
```python
critical_events = {
    "db_write_error",
    "bulk_db_error",
    "runtime_error",
    "auth_denied",
    "file_loop_error",
    # Ingest visibility events - always log these
    "parse_file_exception",
    "parse_failed",
    "scan_exception",
    "scan_thread_error",
    "auto_ingest_dir_missing",
    "safe_path_rejected",
    "safe_path_dropped_files",
    "file_too_large",
    "SHEET_SKIPPED",
    "INGESTION_MANIFEST",
    "INGESTION_QUARANTINED",
}
```

---

## Files Modified

1. **`routes.py`**
   - Added exception handling in `post_scan()` thread
   - Proper error reporting with `update_status("Error", ...)`

2. **`roster_single_user.py`**
   - Fixed `parse_file()` to always return 3 values
   - Added `error_occurred` tracking in `_run_ingest_once()`
   - Fixed status overwrite in finally block
   - Added visibility for missing AUTO_INGEST_DIR
   - Added logging for dropped files
   - Enhanced critical events list for debug logging

---

## Impact on Your Friend

### Before Fix:
- ❌ Clicked "Quét Zalo" → Nothing happened
- ❌ Uploaded file → No response
- ❌ No error messages
- ❌ No way to know what went wrong

### After Fix:
- ✅ Clicked "Quét Zalo" → Shows "Running..." or clear error message
- ✅ Uploaded file → Shows "Uploading..." or clear error message
- ✅ Missing folder → Shows exact path and helpful hint
- ✅ Parse errors → Shows detailed error message
- ✅ All errors logged to `roster_debug.json` for debugging

---

## Testing

✅ All imports work correctly  
✅ Application starts without errors  
✅ Server runs successfully on port 8501  
✅ Error handling tested and verified  
✅ Status indicator now preserves error states  

---

## Instructions for Your Friend

### If Still Having Issues:

1. **Check if storage is set up:**
   ```bash
   termux-setup-storage
   # Grant storage permission when prompted
   ```

2. **Verify Zalo folder exists:**
   ```bash
   ls -la ~/storage/downloads/Zalo
   ```

3. **Enable debug logging:**
   ```bash
   cd ~/RosterSU
   python3 roster_single_user.py --debug
   ```

4. **Check debug log:**
   ```bash
   cat roster_debug.json
   ```

The app will now show clear error messages instead of failing silently!
