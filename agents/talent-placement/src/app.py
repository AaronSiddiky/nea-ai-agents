"""CLI entry point for the talent placement agent."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from .harmonic import get_company_employees, get_person_by_linkedin
from .roster import load_job_reqs
from .matching import rank_matches
from .export import export_match
from .store import init_db, log_match
from .scraper import scrape as refresh_job_reqs

_DEFAULT_PORTCO_CSV = Path.home() / "Desktop" / "Active Portco (LU March 2026) (1).csv"


def _prompt(msg: str) -> str:
    try:
        return input(msg)
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        sys.exit(0)


def _match_and_approve(employees: list, destinations: list, top_n: int) -> None:
    """Core loop: score each employee against destinations, prompt for approval."""
    for emp in employees:
        badge = " [FOUNDER]" if emp.is_founder else (" [EXEC]" if emp.is_executive else "")
        print(f"\n{emp.name}{badge} — {emp.title or 'Unknown title'} @ {emp.company}")
        if emp.linkedin_url:
            print(f"  LinkedIn: {emp.linkedin_url}")

        print("  Scoring matches with Claude...")
        matches = rank_matches(emp, destinations, top_n=top_n)

        if not matches:
            print("  No matches found.")
            continue

        for i, match in enumerate(matches, 1):
            score_pct = int(match.score * 100)
            print(f"\n  [{i}] {match.destination.role} @ {match.destination.company}  —  {score_pct}%")
            print(f"      {match.reasoning}")

        answer = _prompt("\n  Approve any matches? Enter numbers (e.g. 1,3) or press Enter to skip: ").strip()
        if not answer:
            continue

        for part in answer.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(matches):
                    match = matches[idx]
                    notes = _prompt(f"  Notes for {match.destination.role} @ {match.destination.company} (optional): ").strip()
                    match.approved = True
                    match.partner_notes = notes or None
                    log_match(match)
                    path = export_match(match)
                    print(f"  Exported → {path}")


def _load_destinations() -> list:
    destinations = load_job_reqs()
    if not destinations:
        print("No job reqs found. Check data/job_reqs.csv.")
        sys.exit(1)
    print(f"Loaded {len(destinations)} open roles.\n")
    print("=" * 60)
    return destinations


def run(company_name: str, harmonic_id: str, top_n: int = 5) -> None:
    init_db()

    print("Refreshing NEA portfolio job listings...")
    refresh_job_reqs()

    print(f"\nFetching employees for {company_name} from Harmonic...")
    employees = get_company_employees(harmonic_id)
    if not employees:
        print("No employees found. Check the company ID or your HARMONIC_API_KEY.")
        sys.exit(1)
    print(f"Found {len(employees)} employees.\n")

    destinations = _load_destinations()
    _match_and_approve(employees, destinations, top_n)
    print("\nDone.")


def run_linkedin(linkedin_urls: list[str], top_n: int = 5) -> None:
    init_db()

    print("Refreshing NEA portfolio job listings...")
    refresh_job_reqs()

    print(f"\nLooking up {len(linkedin_urls)} profile(s) in Harmonic...")
    employees = []
    for url in linkedin_urls:
        emp = get_person_by_linkedin(url)
        if emp:
            employees.append(emp)
            print(f"  Found: {emp.name} — {emp.title or 'Unknown title'} @ {emp.company}")
        else:
            print(f"  Not found in Harmonic: {url}")

    if not employees:
        print("No profiles resolved. Check the URLs and try again.")
        sys.exit(1)

    destinations = _load_destinations()
    _match_and_approve(employees, destinations, top_n)
    print("\nDone.")


def main() -> None:
    parser = argparse.ArgumentParser(description="NEA Talent Placement CLI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--portco", action="store_true", help="Pick a company interactively from the NEA portco list")
    group.add_argument("--company", help="Company domain or Harmonic ID (e.g. stripe.com or 4292875)")
    group.add_argument("--linkedin", nargs="+", metavar="URL", help="One or more LinkedIn profile URLs to match directly")
    parser.add_argument("--portco-csv", help="Path to portco CSV (default: ~/Desktop/Active Portco...csv)")
    parser.add_argument("--top", type=int, default=5, help="Top N matches per employee (default: 5)")
    args = parser.parse_args()

    if args.portco:
        from .portco import load_portcos, pick_company
        csv_path = args.portco_csv or _DEFAULT_PORTCO_CSV
        if not Path(csv_path).exists():
            print(f"Portco CSV not found at: {csv_path}")
            print("Pass the path with --portco-csv /path/to/file.csv")
            sys.exit(1)
        companies = load_portcos(csv_path)
        selected = pick_company(companies)
        run(selected.name, selected.harmonic_id, top_n=args.top)
    elif args.linkedin:
        run_linkedin(args.linkedin, top_n=args.top)
    else:
        run(args.company, args.company, top_n=args.top)


if __name__ == "__main__":
    main()
