"""Score and rank employee × destination pairs using Claude."""

import os
import json
import logging
import anthropic
from dotenv import load_dotenv
from .models import Employee, Destination, Match

load_dotenv()

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"

_SYSTEM = """\
You are a talent placement advisor for NEA, a venture capital firm.
You evaluate how well a departing portfolio company employee fits an open job requisition.
Focus on three signals:
1. Function/domain fit — does their background match the role's function (engineering, sales, ops, etc.)?
2. Title/seniority fit — is their seniority level appropriate for the role?
3. Company stage fit — does their experience align with the hiring company's stage (seed, Series A/B, growth)?

Respond ONLY with a JSON object: {"score": <0.0–1.0>, "reasoning": "<one concise sentence>"}
"""


def _score_one(employee: Employee, destination: Destination, client: anthropic.Anthropic) -> tuple[float, str]:
    prompt = f"""\
Employee:
- Name: {employee.name}
- Title: {employee.title or "Unknown"}
- Company: {employee.company}
- Founder: {employee.is_founder}, Executive: {employee.is_executive}

Open role at {destination.company}:
- Role: {destination.role}
- Description: {destination.description or "N/A"}

Score this match."""

    message = client.messages.create(
        model=_MODEL,
        max_tokens=200,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    text = message.content[0].text.strip()
    try:
        parsed = json.loads(text)
        score = float(parsed["score"])
        reasoning = parsed["reasoning"]
    except Exception:
        score = 0.0
        reasoning = text[:200]

    return score, reasoning


def rank_matches(
    employee: Employee,
    destinations: list[Destination],
    top_n: int = 5,
) -> list[Match]:
    """Return the top N matches for an employee, each with a score and one-line reasoning."""
    if not destinations:
        return []

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    scored: list[Match] = []
    for dest in destinations:
        try:
            score, reasoning = _score_one(employee, dest, client)
        except Exception as e:
            logger.warning("Scoring failed for %s → %s: %s", employee.name, dest.role, e)
            score, reasoning = 0.0, "Scoring unavailable"

        scored.append(Match(
            employee=employee,
            destination=dest,
            score=score,
            reasoning=reasoning,
        ))

    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:top_n]
