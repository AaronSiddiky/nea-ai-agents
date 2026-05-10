# Talent Placement Agent

Internal NEA tool for placing key employees from portfolio companies heading toward exit or wind-down.

## Setup

```bash
cd agents/talent-placement
cp .env.example .env
# Add your HARMONIC_API_KEY to .env

pip install -e ".[dev]"
```

## Run

```bash
streamlit run src/app.py
```

## Workflow

1. Enter a portfolio company name — Harmonic pulls current employees
2. Matching engine scores each employee against open job reqs and warm-network destinations
3. Partner reviews and approves matches in the Streamlit UI
4. Approved matches are exported as JSON to `data/approved_matches/`

## Structure

```
src/
├── harmonic.py   # All Harmonic API calls (single seam)
├── models.py     # Employee, Destination, Match dataclasses
├── roster.py     # Load job reqs from data/job_reqs.csv
├── matching.py   # Scoring + reasoning via LLM
├── export.py     # Write approved matches to JSON (future: outreach handoff)
├── store.py      # SQLite audit log
└── app.py        # Streamlit UI
data/
├── job_reqs.csv          # Synced from NEA portfolio Google Sheet
└── approved_matches/     # Export destination
```
