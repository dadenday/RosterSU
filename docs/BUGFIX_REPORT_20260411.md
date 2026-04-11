# Bug Fix Report - Cross-Device Compatibility Issues

**Date:** April 11, 2026  
**Issue:** Application errors on friend's device (Android + Termux)  
**Status:** ✅ FIXED

---

## Problems Identified

### Error 1: `ModuleNotFoundError: No module named 'requests'`

**Screenshot:** IMG_1775918484489_1775919437548.jpg

**Root Cause:**
- The `scraper.py` module imports `requests` at the module level without checking if it's installed
- Your friend's device didn't have the `requests` package installed
- When the flight preview feature is triggered (`/flight/preview/fetch`), the import fails

**Why it worked on your device:**
- You likely have `requests` already installed in your Python environment (globally or in a virtual environment)

---

### Error 2: `NameError: name '_run_ingest_once' is not defined`

**Screenshot:** IMG_1775918564788_1775919441444.jpg

**Root Cause:**
- The function `_run_ingest_once()` is defined in `roster_single_user.py` (line 2662)
- It's called in `routes.py` (line 363) inside the `/scan` endpoint
- **BUT** it was missing from the import statement in `routes.py`
- This causes a NameError when the Zalo scan button is pressed

---

## Fixes Applied

### Fix 1: Added Missing Import (routes.py)

**File:** `RosterSU/routes.py`

**Change:** Added `_run_ingest_once` to the imports from `roster_single_user`

```python
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
    _run_ingest_once,  # ← ADDED THIS LINE
)
```

---

### Fix 2: Graceful `requests` Import (scraper.py)

**File:** `RosterSU/scraper.py`

**Changes:**

1. **Added conditional import at the top:**
```python
# Gracefully handle missing requests library
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    requests = None
    REQUESTS_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("requests library not installed - flight sync feature disabled")
```

2. **Added availability check in `fetch_departures()` method:**
```python
def fetch_departures(self, date: str) -> list[ScrapedFlight]:
    if not REQUESTS_AVAILABLE:
        logger.warning("requests library not available - cannot fetch flights")
        return []
    
    # ... rest of the method
```

This ensures the app doesn't crash if `requests` is not installed - it just returns an empty list for flight data.

---

### Fix 3: Enhanced Auto-Dependency Installation (roster_single_user.py)

**File:** `RosterSU/roster_single_user.py`

**Change:** Added `requests` to the dependency check in `_ensure_dependencies()`

```python
try:
    import requests
except ImportError:
    missing.append("requests")
```

Now when your friend runs the app for the first time, it will automatically detect the missing `requests` package and install it from `requirements.txt`.

---

## Verification

All fixes have been tested and verified:

✅ `routes.py` imports work correctly  
✅ `scraper.py` imports work correctly  
✅ `_run_ingest_once` can be imported  
✅ Application starts without errors  
✅ Server runs successfully on port 8501

---

## Instructions for Your Friend

Your friend should:

1. **Pull the latest code** with the fixes
2. **Run the app** - it will automatically detect and install missing dependencies:
   ```bash
   cd ~/RosterSU
   python3 roster_single_user.py
   ```
3. **If manual installation is needed:**
   ```bash
   pip install -r requirements.txt
   ```

The app should now work without the previous errors.

---

## Files Modified

1. `RosterSU/routes.py` - Added missing import
2. `RosterSU/scraper.py` - Added graceful fallback for missing `requests`
3. `RosterSU/roster_single_user.py` - Enhanced dependency check

---

## Preventive Measures for Future

To avoid similar issues in the future:

1. **Always run dependency checks** before distributing code
2. **Use graceful imports** for optional features (like flight sync)
3. **Test on a clean environment** before sharing with others
4. **Document required dependencies** clearly in README
