"""SQLite state and audit log."""

from pathlib import Path
from .models import Match

_DB_PATH = Path(__file__).parent.parent / "data" / "audit.db"


def init_db(db_path: Path = _DB_PATH) -> None:
    """Create tables if they don't exist."""
    ...


def log_match(match: Match, db_path: Path = _DB_PATH) -> None:
    """Append a match (approved or rejected) to the audit log."""
    ...


def get_approved_matches(db_path: Path = _DB_PATH) -> list[Match]:
    """Return all partner-approved matches."""
    ...
