# Talent Placement Agent — Progress & Next Steps

_Last updated: May 10, 2026_

---

## What was built

A terminal-based Python CLI that helps NEA partners place employees from portfolio companies heading toward exit or wind-down.

**Full pipeline is implemented and working end-to-end:**

1. Partner runs `python3 -m src.app --portco` → picks from the 420-company NEA portco list (loaded from the Harmonic export CSV on Desktop)
2. Tool fetches current employees from Harmonic using the Company ID directly (no domain lookup needed)
3. Claude scores each employee against open job reqs in `data/job_reqs.csv` — rated on function fit, seniority, and company stage
4. Partner reviews top 5 matches per employee, types numbers to approve
5. Approved matches are logged to SQLite (`data/audit.db`) and exported as JSON to `data/approved_matches/`

**Verified working:** Harmonic employee fetch (tested on Databricks, 30 employees returned)

**One blocker:** Anthropic account needs credits added at [console.anthropic.com](https://console.anthropic.com) → Plans & Billing. The API key is correct. Once credits are added, the full run works.

---

## To run

```bash
cd agents/talent-placement
cp .env.example .env          # add HARMONIC_API_KEY and ANTHROPIC_API_KEY
pip3 install anthropic requests python-dotenv pydantic sqlite-utils eval_type_backport
python3 -m src.app --portco
```

---

## Next steps

1. **Add credits to Anthropic account** — unblocks the Claude scoring step
2. **Replace sample `data/job_reqs.csv`** with real NEA portfolio open roles (columns: `company, role, description, contact_name, contact_email`)
3. **Test end-to-end** on a real portco — pick a small company from the list with 10–30 employees
4. **Google Sheets sync for job reqs** — instead of a static CSV, pull live open roles from the NEA portfolio jobs sheet
5. **Outreach handoff** — `src/export.py` is already stubbed as the seam; when ready, connect approved matches to the existing outreach agent (`agents/outreach/`)
6. **Batch scoring** — currently scores one employee×role pair per Claude call; batching all roles for one employee into a single prompt would be ~10x faster and cheaper
