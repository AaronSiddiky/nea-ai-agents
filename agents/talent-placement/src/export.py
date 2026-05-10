"""Temporary stand-in for the outreach agent handoff.

When the outreach agent is ready, replace export_match() with
send_to_outreach(match) -> handoff_id. The call site in app.py stays the same.
"""

import json
from pathlib import Path
from .models import Match

_EXPORT_DIR = Path(__file__).parent.parent / "data" / "approved_matches"


def export_match(match: Match) -> Path:
    """Write an approved match to data/approved_matches/ as JSON."""
    ...
