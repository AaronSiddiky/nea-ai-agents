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

_PREFILTER_LIMIT = 100
_BATCH_SIZE = 25


def _prefilter(employee: Employee, destinations: list[Destination]) -> list[Destination]:
    """Keyword-rank destinations and return top _PREFILTER_LIMIT before LLM scoring."""
    if len(destinations) <= _PREFILTER_LIMIT:
        return destinations
    title_words = set((employee.title or "").lower().split())
    if not title_words:
        return destinations[:_PREFILTER_LIMIT]

    def score(dest: Destination) -> int:
        role_words = set(dest.role.lower().split())
        return len(title_words & role_words)

    return sorted(destinations, key=score, reverse=True)[:_PREFILTER_LIMIT]


def _score_batch(employee: Employee, batch: list[Destination]) -> list[dict]:
    """Score one batch of up to _BATCH_SIZE destinations against an employee."""
    roles_text = "\n".join(
        f"{i + 1}. {d.role} @ {d.company}" + (f" ({d.location})" if d.location else "")
        for i, d in enumerate(batch)
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
            timeout=180,
            env=env,
        )
        data = json.loads(result.stdout)
        raw = data["result"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        scores = json.loads(raw)
        if not isinstance(scores, list):
            raise ValueError("Expected a JSON array")
        return scores
    except Exception as e:
        logger.error("Batch scoring failed for %s: %s", employee.name, e)
        return [{"score": 0.0, "reasoning": "Scoring unavailable"}] * len(batch)


def rank_matches(
    employee: Employee,
    destinations: list[Destination],
    top_n: int = 5,
) -> list[Match]:
    if not destinations:
        return []

    destinations = _prefilter(employee, destinations)

    all_scores: list[dict] = []
    for i in range(0, len(destinations), _BATCH_SIZE):
        batch = destinations[i : i + _BATCH_SIZE]
        scores = _score_batch(employee, batch)
        # Pad short responses so zip stays aligned
        if len(scores) < len(batch):
            scores += [{"score": 0.0, "reasoning": "Scoring unavailable"}] * (len(batch) - len(scores))
        all_scores.extend(scores[: len(batch)])

    matches = []
    for dest, s in zip(destinations, all_scores):
        matches.append(Match(
            employee=employee,
            destination=dest,
            score=float(s.get("score", 0.0)),
            reasoning=s.get("reasoning", ""),
        ))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:top_n]
