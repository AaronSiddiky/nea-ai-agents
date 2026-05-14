"""Scrape job listings from careers.nea.com and save to data/job_reqs.csv."""

import csv
import pathlib
import time
from typing import Optional

import requests

PAGE_SIZE = 100
OUTPUT = pathlib.Path(__file__).parent.parent / "data" / "job_reqs.csv"
API_URL = "https://careers.nea.com/api-boards/search-jobs"
BOARD = {"id": "nea", "isParent": True}

HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


def fetch_page(session: requests.Session, sequence: Optional[str]) -> dict:
    meta: dict = {"size": PAGE_SIZE}
    if sequence:
        meta["sequence"] = sequence
    resp = session.post(
        API_URL,
        headers=HEADERS,
        json={"meta": meta, "board": BOARD, "query": {}, "grouped": False, "parentSlug": "nea"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def scrape() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; NEA-talent-placement/1.0)"})

    all_jobs: list[dict] = []
    sequence: Optional[str] = None

    while True:
        data = fetch_page(session, sequence)
        jobs = data.get("jobs", [])
        if not jobs:
            break
        all_jobs.extend(jobs)
        sequence = data.get("meta", {}).get("sequence")
        if not sequence or len(all_jobs) >= data.get("total", 0):
            break
        time.sleep(0.1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company", "title", "location", "url"])
        writer.writeheader()
        for job in all_jobs:
            writer.writerow({
                "company": job.get("companyName", ""),
                "title": job.get("title", ""),
                "location": "; ".join(job.get("locations", [])),
                "url": job.get("url", ""),
            })

    print(f"Found {len(all_jobs)} jobs. Saved to {OUTPUT}")


if __name__ == "__main__":
    scrape()
