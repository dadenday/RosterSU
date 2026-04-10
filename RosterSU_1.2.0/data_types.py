"""
RosterMaster Types Module

Dataclasses and type definitions for the roster application.
Extracted from roster_single_user.py for maintainability.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import date, datetime
import threading


@dataclass
class FlightRow:
    """
    A single flight assignment row.
    Replaces Dict[str, Any] for flight data throughout the codebase.
    """
    type: str = ""
    call: str = ""
    route: str = ""
    open: str = ""
    close: str = ""
    bay: str = ""
    names: str = ""
    zone: str = ""
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'FlightRow':
        """Create FlightRow from dict (DB/JSON boundary)."""
        return cls(
            type=d.get('Type', ''),
            call=d.get('Call', ''),
            route=d.get('Route', ''),
            open=d.get('Open', ''),
            close=d.get('Close', ''),
            bay=d.get('Bay', ''),
            names=d.get('Names', ''),
            zone=d.get('Zone', '')
        )
    
    def to_dict(self) -> Dict:
        """Convert to dict (DB/JSON boundary)."""
        return {
            'Type': self.type,
            'Call': self.call,
            'Route': self.route,
            'Open': self.open,
            'Close': self.close,
            'Bay': self.bay,
            'Names': self.names,
            'Zone': self.zone
        }


@dataclass
class ShiftRecord:
    """
    A shift assignment for a date.
    Combines shift info with associated flights.
    """
    date: str
    shift: str = ""
    flights: List[FlightRow] = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'ShiftRecord':
        """Create ShiftRecord from dict (DB/JSON boundary)."""
        flights = [FlightRow.from_dict(f) for f in d.get('flights', [])]
        return cls(
            date=d.get('date', ''),
            shift=d.get('shift', ''),
            flights=flights
        )
    
    def to_dict(self) -> Dict:
        """Convert to dict (DB/JSON boundary)."""
        return {
            'date': self.date,
            'shift': self.shift,
            'flights': [f.to_dict() for f in self.flights]
        }


@dataclass
class ParsedSheet:
    """
    Result of parsing a single sheet.
    Used internally by parser functions.
    """
    date: str
    shift: Optional[str] = None
    flights: List[FlightRow] = field(default_factory=list)
    sheet_name: str = ""
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'ParsedSheet':
        """Create ParsedSheet from dict."""
        flights = [FlightRow.from_dict(f) for f in d.get('flights', [])]
        return cls(
            date=d.get('date', ''),
            shift=d.get('shift'),
            flights=flights,
            sheet_name=d.get('sheet_name', '')
        )
    
    def to_dict(self) -> Dict:
        """Convert to dict for DB storage."""
        return {
            'date': self.date,
            'shift': self.shift,
            'flights': [f.to_dict() for f in self.flights],
            'sheet_name': self.sheet_name
        }
    
    def to_db_dict(self) -> Dict:
        """Convert to dict for DB storage (without sheet_name)."""
        return {
            'date': self.date,
            'shift': self.shift,
            'flights': [f.to_dict() for f in self.flights]
        }


@dataclass(frozen=True)
class ParseContext:
    """
    Immutable runtime context passed through the parsing pipeline.
    Layer 1 (DateResolver) creates this; all downstream layers receive it.
    """
    global_date: str  # Normalized DD.MM.YYYY format
    global_date_iso: str  # YYYY-MM-DD format for DB
    source_filename: str
    file_id: str  # Unique identifier for this ingestion
    date_confidence: float = 1.0
    date_anomaly: bool = False
    date_candidates: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        """Validate that global_date is set and not Unknown."""
        if not self.global_date or self.global_date == "Unknown":
            raise InvariantViolation(
                f"ParseContext created with invalid global_date: '{self.global_date}' "
                f"for file '{self.source_filename}'"
            )


@dataclass
class DateCandidate:
    """A candidate date with its source and weight."""
    date: str  # Normalized DD.MM.YYYY
    source: str
    weight: int
    raw_value: str = ""


@dataclass
class IngestionManifest:
    """
    Simplified metadata for ingestion tracking.

    Key principle: Sheets DO NOT define dates.
    Sheet date mismatches are logged as warnings, not blockers.
    """
    file_hash: str
    filename: str
    global_date: str
    global_date_iso: str
    date_candidates: List[Dict[str, Any]]
    parsed_sheets: List[str]
    warnings: List[str]  # Non-blocking issues (e.g., stale sheet headers)
    parsed_counts: Dict[str, int]  # {shift: N, flights: M}
    anomalies: List[str]
    confidence_score: float
    timestamp: str
    blocked: bool = False
    block_reason: str = ""
    # Flight Dataset Selection fields
    flight_fingerprints: List[str] = field(default_factory=list)
    authoritative_fingerprint: str = ""
    # Phase 3 (240326): Single source of truth - authoritative only
    authoritative_source: str = ""
    rejected_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """Convert to dict for DB storage."""
        return {
            'file_hash': self.file_hash,
            'filename': self.filename,
            'global_date': self.global_date,
            'global_date_iso': self.global_date_iso,
            'date_candidates': self.date_candidates,
            'parsed_sheets': self.parsed_sheets,
            'warnings': self.warnings,
            'parsed_counts': self.parsed_counts,
            'anomalies': self.anomalies,
            'confidence_score': self.confidence_score,
            'timestamp': self.timestamp,
            'blocked': self.blocked,
            'block_reason': self.block_reason,
            'flight_fingerprints': self.flight_fingerprints,
            'authoritative_fingerprint': self.authoritative_fingerprint,
            'authoritative_source': self.authoritative_source,
            'rejected_sources': self.rejected_sources,
        }


# Exception classes
class DateMismatchWarning(Exception):
    """Raised when date resolution detects significant conflict."""
    pass


class InvariantViolation(Exception):
    """Raised when an architectural invariant is violated."""
    pass


__all__ = [
    'FlightRow',
    'ShiftRecord',
    'ParsedSheet',
    'ParseContext',
    'DateCandidate',
    'IngestionManifest',
    'DateMismatchWarning',
    'InvariantViolation',
]
