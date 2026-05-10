"""Load NEA portfolio job reqs from data/job_reqs.csv."""

import csv
import uuid
from pathlib import Path
from .models import Destination

_DEFAULT_PATH = Path(__file__).parent.parent / "data" / "job_reqs.csv"

_REQUIRED_COLUMNS = {"company", "role"}


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
                role=row["role"].strip(),
                description=row.get("description", "").strip() or None,
                contact_name=row.get("contact_name", "").strip() or None,
                contact_email=row.get("contact_email", "").strip() or None,
            ))
    return destinations
