"""SQLite state and audit log."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from .models import Match, Employee, Destination

_DB_PATH = Path(__file__).parent.parent / "data" / "audit.db"


def init_db(db_path: Path = _DB_PATH) -> None:
    """Create tables if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT (datetime('now')),
                employee_id TEXT NOT NULL,
                employee_name TEXT NOT NULL,
                employee_title TEXT,
                employee_company TEXT NOT NULL,
                destination_id TEXT NOT NULL,
                destination_company TEXT NOT NULL,
                destination_role TEXT NOT NULL,
                score REAL NOT NULL,
                reasoning TEXT,
                partner_notes TEXT,
                approved INTEGER NOT NULL DEFAULT 0,
                employee_json TEXT NOT NULL,
                destination_json TEXT NOT NULL
            )
        """)
        conn.commit()


def log_match(match: Match, db_path: Path = _DB_PATH) -> None:
    """Append a match (approved or rejected) to the audit log."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO matches (
                employee_id, employee_name, employee_title, employee_company,
                destination_id, destination_company, destination_role,
                score, reasoning, partner_notes, approved,
                employee_json, destination_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            match.employee.id,
            match.employee.name,
            match.employee.title,
            match.employee.company,
            match.destination.id,
            match.destination.company,
            match.destination.role,
            match.score,
            match.reasoning,
            match.partner_notes,
            int(match.approved),
            match.employee.model_dump_json(),
            match.destination.model_dump_json(),
        ))
        conn.commit()


def get_approved_matches(db_path: Path = _DB_PATH) -> list[Match]:
    """Return all partner-approved matches."""
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM matches WHERE approved = 1 ORDER BY created_at DESC"
        ).fetchall()

    result = []
    for row in rows:
        employee = Employee(**json.loads(row["employee_json"]))
        destination = Destination(**json.loads(row["destination_json"]))
        result.append(Match(
            employee=employee,
            destination=destination,
            score=row["score"],
            reasoning=row["reasoning"] or "",
            partner_notes=row["partner_notes"],
            approved=True,
        ))
    return result
