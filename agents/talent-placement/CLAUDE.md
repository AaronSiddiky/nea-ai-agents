# Talent Placement Agent

Internal NEA tool. Partner picks a portfolio company that's heading
for exit or wind-down. Tool uses Harmonic to find key employees,
matches them to NEA portfolio job reqs and Harmonic-surfaced
warm-network destinations, partner approves matches, approved
matches are exported as structured JSON.

Two-week MVP. Single partner, single test company. No real frontend —
Streamlit only.

## Key dependencies
- Harmonic API (people data, similar-people search) — API key in .env
- Google Sheet of NEA portfolio open job reqs — synced to data/job_reqs.csv
- Future: email outreach agent (separate service, integration deferred)

## Architecture seams to protect
- src/export.py is a temporary stand-in for the outreach agent handoff.
  When the outreach agent is ready, only export.py changes.
- src/harmonic.py wraps all Harmonic calls — no Harmonic SDK calls
  anywhere else in the codebase.

## Out of scope
- Diagnostic/triage logic (partner brings the decision)
- M&A workflow
- Drafting or sending emails
- React/Next.js/real frontend — Streamlit only
- Auth (single-user local app for the pilot)

## Style
- Boring Python. Type hints. SQLite, not a real DB.
- No premature abstraction — one company, one partner, one workflow.
