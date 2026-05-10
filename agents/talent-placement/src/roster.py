"""Load NEA portfolio job reqs from data/job_reqs.csv."""

from pathlib import Path
from .models import Destination

_DEFAULT_PATH = Path(__file__).parent.parent / "data" / "job_reqs.csv"


def load_job_reqs(path: Path = _DEFAULT_PATH) -> list[Destination]:
    """Return all open job reqs as Destination objects."""
    ...
