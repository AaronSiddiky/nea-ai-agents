"""
Backfill `canonical_entity_id` on the 11 Stanford TEXT-slug tables.

For every row where `canonical_entity_id IS NULL`, we ask the Node service
(`POST /api/v1/canonical/find-or-create`) to resolve / create a canonical
entity from `company_id` (the domain string) plus any companion hints
(`company_name`, `harmonic_id`). On success we UPDATE the row in place.

Idempotent: rows that already have a `canonical_entity_id` are skipped on
filter, so re-running this script is safe (and recommended after a fresh
ingest of Stanford data).

Unmatched domains are appended to
`scripts/backfill_canonical_ids.unmatched.log` so a human can resolve them
manually (rare; usually means the domain is junk or Harmonic has no hit).

Usage:
    python scripts/backfill_canonical_ids.py
    python scripts/backfill_canonical_ids.py --tables briefing_companies stories
    python scripts/backfill_canonical_ids.py --dry-run
    python scripts/backfill_canonical_ids.py --batch 200
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

# Allow running this file directly from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.canonical_bridge import resolve_canonical_entity_id  # noqa: E402
from core.clients import get_supabase  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_canonical_ids")

UNMATCHED_LOG = Path(__file__).resolve().parent / "backfill_canonical_ids.unmatched.log"

# Each entry: (table_name, name_column_or_None)
# Resolver hint = (domain=company_id, name=row[name_column] if any)
TABLES_AND_NAME_COLS = [
    ("briefing_companies", "company_name"),
    ("briefing_news", None),
    ("briefing_signals", None),
    ("briefing_competitors", "competitor_name"),
    ("founders", "company_name"),
    ("watched_companies", "company_name"),
    ("stories", "company_name"),
    ("outreach_history", "company_name"),
    ("outreach_feedback", None),
    ("briefing_history", "company_name"),
    ("nea_portfolio", "company_name"),
]


def _backfill_table(
    table: str,
    name_col: Optional[str],
    batch: int,
    dry_run: bool,
    unmatched_writer,
) -> tuple[int, int, int]:
    """Returns (scanned, updated, unmatched)."""
    supabase = get_supabase()
    select_cols = ["id", "company_id"]
    # nea_portfolio uses `slug` as PK and `domain` for the website; treat domain as company_id.
    is_portfolio = table == "nea_portfolio"
    if is_portfolio:
        select_cols = ["id", "domain"]
    if name_col:
        select_cols.append(name_col)

    scanned = updated = unmatched = 0
    page_size = max(1, min(batch, 1000))
    offset = 0
    while True:
        try:
            resp = (
                supabase.table(table)
                .select(",".join(select_cols))
                .is_("canonical_entity_id", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )
        except Exception as exc:
            logger.warning(f"[{table}] select failed at offset {offset}: {exc}")
            return scanned, updated, unmatched

        rows = resp.data or []
        if not rows:
            break

        for row in rows:
            scanned += 1
            domain = row.get("domain") if is_portfolio else row.get("company_id")
            name = row.get(name_col) if name_col else None
            if not domain and not name:
                unmatched += 1
                unmatched_writer.write(f"{table}\t{row.get('id')}\t<no-domain-no-name>\n")
                continue

            cid = resolve_canonical_entity_id(domain=domain, name=name)
            if not cid:
                unmatched += 1
                unmatched_writer.write(f"{table}\t{row.get('id')}\t{domain or ''}\t{name or ''}\n")
                continue

            if dry_run:
                updated += 1
                continue

            try:
                supabase.table(table).update({"canonical_entity_id": cid}).eq("id", row["id"]).execute()
                updated += 1
            except Exception as exc:
                logger.warning(f"[{table}] update id={row.get('id')} failed: {exc}")
                unmatched += 1
                unmatched_writer.write(f"{table}\t{row.get('id')}\tUPDATE_FAILED\t{exc}\n")

        if len(rows) < page_size:
            break
        offset += page_size

    return scanned, updated, unmatched


def main(argv: Iterable[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill canonical_entity_id across Stanford tables.")
    parser.add_argument("--tables", nargs="*", help="Only run on these tables (default: all 11)")
    parser.add_argument("--batch", type=int, default=500, help="Rows per Supabase page (default 500)")
    parser.add_argument("--dry-run", action="store_true", help="Resolve but don't UPDATE")
    args = parser.parse_args(argv)

    target = TABLES_AND_NAME_COLS
    if args.tables:
        wanted = set(args.tables)
        target = [t for t in TABLES_AND_NAME_COLS if t[0] in wanted]

    UNMATCHED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with UNMATCHED_LOG.open("a") as unmatched_writer:
        unmatched_writer.write(f"\n# --- run @ {__import__('datetime').datetime.utcnow().isoformat()}Z ---\n")
        totals = (0, 0, 0)
        for table, name_col in target:
            logger.info(f"[{table}] starting backfill")
            scanned, updated, unmatched = _backfill_table(
                table=table,
                name_col=name_col,
                batch=args.batch,
                dry_run=args.dry_run,
                unmatched_writer=unmatched_writer,
            )
            logger.info(f"[{table}] scanned={scanned} updated={updated} unmatched={unmatched}")
            totals = (totals[0] + scanned, totals[1] + updated, totals[2] + unmatched)
        logger.info(f"TOTAL scanned={totals[0]} updated={totals[1]} unmatched={totals[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
