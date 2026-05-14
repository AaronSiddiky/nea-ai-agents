"""Score and rank employee × destination pairs using the claude CLI."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from .models import Employee, Destination, Match

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a talent placement advisor for NEA, a venture capital firm.
You evaluate how well a departing portfolio company employee fits open job requisitions.
Focus on three signals:
1. Function/domain fit — does their background match the role's function?
2. Title/seniority fit — is their seniority level appropriate?
3. Company stage fit — does their experience align with the hiring company's stage?

Respond ONLY with a JSON array, one object per role, in the same order as given:
[{"score": <0.0-1.0>, "reasoning": "<one concise sentence>"}, ...]
"""


def rank_matches(
    employee: Employee,
    destinations: list[Destination],
    top_n: int = 5,
) -> list[Match]:
    if not destinations:
        return []

    roles_text = "\n".join(
        f"{i+1}. {d.role} @ {d.company}" + (f" ({d.location})" if d.location else "")
        for i, d in enumerate(destinations)
    )

    prompt = f"""\
Employee:
- Name: {employee.name}
- Title: {employee.title or "Unknown"}
- Company: {employee.company}
- Founder: {employee.is_founder}, Executive: {employee.is_executive}

Score this employee against each open role below. Return a JSON array with one object per role in the same order:
{roles_text}"""

    try:
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        result = subprocess.run(
            [
                "claude", "-p",
                "--output-format", "json",
                "--system-prompt", _SYSTEM,
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        data = json.loads(result.stdout)
        raw = data["result"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        scores = json.loads(raw)
        if not isinstance(scores, list):
            raise ValueError("Expected a JSON array")
    except Exception as e:
        logger.error("Scoring failed for %s: %s", employee.name, e)
        scores = [{"score": 0.0, "reasoning": "Scoring unavailable"}] * len(destinations)

    matches = []
    for dest, s in zip(destinations, scores):
        matches.append(Match(
            employee=employee,
            destination=dest,
            score=float(s.get("score", 0.0)),
            reasoning=s.get("reasoning", ""),
        ))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:top_n]
