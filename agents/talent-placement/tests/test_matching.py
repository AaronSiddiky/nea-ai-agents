"""Tests for matching.rank_matches (subprocess mocked)."""
import json
from unittest.mock import MagicMock, patch

from src.models import Employee, Destination
from src.matching import rank_matches


def _emp() -> Employee:
    return Employee(id="e1", name="Alice", title="Engineer", company="OldCo")


def _dests(n: int = 3) -> list[Destination]:
    return [
        Destination(id=f"d{i}", type="job_req", company=f"Co{i}", role=f"Role {i}")
        for i in range(n)
    ]


def _mock_run(scores: list[dict]) -> MagicMock:
    result = MagicMock()
    result.stdout = json.dumps({"result": json.dumps(scores)})
    return result


def test_returns_top_n():
    scores = [{"score": 0.9, "reasoning": "great"}, {"score": 0.5, "reasoning": "ok"}, {"score": 0.1, "reasoning": "weak"}]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(3), top_n=2)
    assert len(matches) == 2


def test_sorted_by_score_descending():
    scores = [{"score": 0.3, "reasoning": "low"}, {"score": 0.9, "reasoning": "high"}, {"score": 0.6, "reasoning": "mid"}]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(3), top_n=3)
    assert matches[0].score == 0.9
    assert matches[1].score == 0.6
    assert matches[2].score == 0.3


def test_empty_destinations_returns_empty():
    with patch("src.matching.subprocess.run") as mock_run:
        matches = rank_matches(_emp(), [], top_n=5)
    mock_run.assert_not_called()
    assert matches == []


def test_subprocess_failure_returns_fallback_scores():
    with patch("src.matching.subprocess.run", side_effect=Exception("timeout")):
        matches = rank_matches(_emp(), _dests(2), top_n=5)
    assert len(matches) == 2
    assert all(m.score == 0.0 for m in matches)
    assert all(m.reasoning == "Scoring unavailable" for m in matches)


def test_markdown_fenced_json_is_parsed():
    scores = [{"score": 0.8, "reasoning": "solid"}]
    fenced = "```json\n" + json.dumps(scores) + "\n```"
    result = MagicMock()
    result.stdout = json.dumps({"result": fenced})
    with patch("src.matching.subprocess.run", return_value=result):
        matches = rank_matches(_emp(), _dests(1), top_n=5)
    assert matches[0].score == 0.8


def test_top_n_does_not_exceed_available():
    scores = [{"score": 0.5, "reasoning": "ok"}]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(1), top_n=10)
    assert len(matches) == 1


def test_reasoning_is_preserved():
    scores = [{"score": 0.7, "reasoning": "Good domain fit."}]
    with patch("src.matching.subprocess.run", return_value=_mock_run(scores)):
        matches = rank_matches(_emp(), _dests(1), top_n=5)
    assert matches[0].reasoning == "Good domain fit."


def test_batching_makes_multiple_calls():
    """With 30 destinations, _BATCH_SIZE=25 should produce 2 subprocess calls."""
    from src.matching import _BATCH_SIZE
    n = _BATCH_SIZE + 5  # 30 destinations
    responses = [
        _mock_run([{"score": 0.5, "reasoning": "ok"}] * _BATCH_SIZE),
        _mock_run([{"score": 0.5, "reasoning": "ok"}] * 5),
    ]
    with patch("src.matching.subprocess.run", side_effect=responses) as mock_run:
        matches = rank_matches(_emp(), _dests(n), top_n=n)
    assert mock_run.call_count == 2
    assert len(matches) == n
