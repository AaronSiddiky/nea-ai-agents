"""Score and rank employee × destination pairs."""

from .models import Employee, Destination, Match


def rank_matches(
    employee: Employee,
    destinations: list[Destination],
    top_n: int = 5,
) -> list[Match]:
    """Return the top N matches for an employee, each with a score and one-line reasoning."""
    ...
