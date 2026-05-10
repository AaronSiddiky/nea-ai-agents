"""Temporary stand-in for the outreach agent handoff.

When the outreach agent is ready, replace export_match() with
send_to_outreach(match) -> handoff_id. The call site in app.py stays the same.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from .models import Match

_EXPORT_DIR = Path(__file__).parent.parent / "data" / "approved_matches"


def export_match(match: Match) -> Path:
    """Write an approved match to data/approved_matches/ as JSON."""
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    safe_name = match.employee.name.replace(" ", "_").lower()
    safe_role = match.destination.role.replace(" ", "_").lower()
    filename = f"{safe_name}__{safe_role}__{ts}.json"
    path = _EXPORT_DIR / filename
    path.write_text(json.dumps(match.model_dump(), indent=2))
    return path
