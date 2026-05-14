"""Load NEA portfolio job reqs from data/job_reqs.csv."""
from __future__ import annotations

import csv
import uuid
from pathlib import Path
from .models import Destination

_DEFAULT_PATH = Path(__file__).parent.parent / "data" / "job_reqs.csv"

_REQUIRED_COLUMNS = {"company", "title"}


def load_job_reqs(path: Path = _DEFAULT_PATH) -> list[Destination]:
    """Return all open job reqs as Destination objects."""
    if not path.exists():
        return []

    destinations = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not _REQUIRED_COLUMNS.issubset(row.keys()):
                continue
            destinations.append(Destination(
                id=str(uuid.uuid4()),
                type="job_req",
                company=row["company"].strip(),
                role=row["title"].strip(),
                location=row.get("location", "").strip() or None,
                url=row.get("url", "").strip() or None,
            ))
    return destinations
