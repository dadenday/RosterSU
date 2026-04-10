"""
Application state management for RosterMaster.

Extracted from roster_single_user.py for maintainability.
Provides thread-safe state encapsulation.
"""

import threading
from dataclasses import dataclass, field
from typing import Dict, Tuple


STATE_LOCK = threading.RLock()
DB_LOCK = threading.RLock()
CONFIG_LOCK = threading.RLock()
SHUTDOWN_EVENT = threading.Event()
UI_CONNECTED = threading.Event()

# Legacy globals retained for Event semantics (wait, is_set)
# but access should go through AppState wrappers where possible.
_INGEST_EVENT = threading.Event()


@dataclass
class AppState:
    """
    Encapsulates all application state with thread-safe access.
    Phase 4: Reduces global variable chaos by wrapping state in a class.
    Phase 2.5: Unified runtime state (ingest_running, ui_connected migrated from globals).
    """

    _lock: threading.RLock = field(default_factory=threading.RLock)
    _status: Dict[str, str] = field(
        default_factory=lambda: {"state": "Idle", "details": "Ready"}
    )
    _roster_version: int = 0
    _ingest_running: bool = False
    _ui_connected: bool = False

    @property
    def ingest_running(self) -> bool:
        """Thread-safe getter for ingest_running flag."""
        with self._lock:
            return self._ingest_running

    @ingest_running.setter
    def ingest_running(self, value: bool) -> None:
        """Thread-safe setter for ingest_running flag. Also syncs the legacy Event."""
        with self._lock:
            self._ingest_running = value
        if value:
            _INGEST_EVENT.set()
        else:
            _INGEST_EVENT.clear()

    def set_ingest(self) -> None:
        """Mark ingest as running (Event-compatible API)."""
        self.ingest_running = True

    def clear_ingest(self) -> None:
        """Mark ingest as stopped (Event-compatible API)."""
        self.ingest_running = False

    def is_ingest_running(self) -> bool:
        """Check if ingest is running (Event-compatible API, returns bool)."""
        return self.ingest_running

    @property
    def ingest_event(self) -> threading.Event:
        """Expose the underlying Event for wait() semantics."""
        return _INGEST_EVENT

    @property
    def ui_connected(self) -> bool:
        """Thread-safe getter for ui_connected flag."""
        with self._lock:
            return self._ui_connected

    @ui_connected.setter
    def ui_connected(self, value: bool) -> None:
        """Thread-safe setter for ui_connected flag."""
        with self._lock:
            self._ui_connected = value

    def get_status(self) -> Tuple[Dict[str, str], int]:
        """Thread-safe getter for status and version."""
        with self._lock:
            return self._status.copy(), self._roster_version

    def try_get_status(self, timeout: float = 0.05) -> Tuple[Dict[str, str], int]:
        """Non-blocking status getter with timeout."""
        acquired = self._lock.acquire(timeout=timeout)
        if not acquired:
            return {"state": "Busy", "details": "Resuming..."}, self._roster_version
        try:
            return self._status.copy(), self._roster_version
        finally:
            self._lock.release()

    def update_status(self, state: str, details: str = "") -> None:
        """Thread-safe status update."""
        acquired = self._lock.acquire(timeout=0.1)
        if not acquired:
            return  # Never block UI
        try:
            self._status = {"state": state, "details": details}
            if state == "Idle" and "Processed" in details:
                self._roster_version += 1
        finally:
            self._lock.release()

    def increment_version(self) -> None:
        """Increment roster version (for external DB changes)."""
        with self._lock:
            self._roster_version += 1

    @property
    def roster_version(self) -> int:
        """Read-only access to roster version for UI binding."""
        with self._lock:
            return self._roster_version


# Global instance - single source of truth
APP = AppState()


def get_app_status() -> Tuple[Dict[str, str], int]:
    """Thread-safe getter for status and version. Delegates to APP."""
    return APP.get_status()


def try_get_app_status(timeout: float = 0.05) -> Tuple[Dict[str, str], int]:
    """UI-safe state getter. Delegates to APP."""
    return APP.try_get_status(timeout)


def update_status(state: str, details: str = "") -> None:
    """Thread-safe status update. Delegates to APP."""
    APP.update_status(state, details)


def bump_db_rev() -> None:
    """Increment roster version for external DB changes."""
    APP.increment_version()


# === Backward-compatible aliases for direct Event usage ===
# These delegate to the Event so existing code (INGEST_RUNNING.set(), etc.) still works.
INGEST_RUNNING = _INGEST_EVENT  # type: threading.Event

# Legacy globals (deprecated — use APP.get_status() instead)
APP_STATUS: Dict[str, str] = {"state": "Idle", "details": "Ready"}
ROSTER_VERSION = 0
