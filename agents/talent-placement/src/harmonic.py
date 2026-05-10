"""All Harmonic API calls live here. No Harmonic calls anywhere else."""

import os
import requests
from dotenv import load_dotenv
from .models import Employee, Person

load_dotenv()

_BASE_URL = "https://api.harmonic.ai"


def _headers() -> dict[str, str]:
    key = os.environ["HARMONIC_API_KEY"]
    return {"apikey": key, "Content-Type": "application/json"}


def get_company_employees(company_identifier: str) -> list[Employee]:
    """Pull current employees for a portfolio company."""
    ...


def find_similar_people(
    employee: Employee,
    role_context: str | None = None,
) -> list[Employee]:
    """Use Harmonic's similar-people search for warm-network destinations."""
    ...
