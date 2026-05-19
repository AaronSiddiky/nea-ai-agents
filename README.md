# NEA AI Agents

> **Merged into the NEA Scout monorepo.** This fork is the live source for
> the Python agent service hosted on Railway as `nea-agents`; everything
> else (the standalone Next.js frontend, the Vercel deployment, the
> separate Supabase project) is decommissioned in favour of the
> [NEA Scout monorepo](https://github.com/AaronSiddiky/neatracker). See
> `supabase/migrations/040_stanford_base_schema.sql` through `050_*.sql`
> in that repo for the unified data model, and `merge-nea-ai-agents` plan
> for the integration history.
>
> Auth: Supabase HS256 JWTs only (legacy X-NEA-Key and Clerk RS256 removed
> in M5). Internal cron triggers use `X-NEA-Internal-Token`. Frontend
> requests are proxied through `app/api/agents/[...path]/route.ts` in
> the monorepo.

![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![Railway](https://img.shields.io/badge/deploy-railway-purple.svg)
![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)

AI agents for venture capital workflows, delivered as a FastAPI service on
Railway backed by the shared NEA Scout Supabase project. Three agents
(briefing, news, outreach) built on LangChain/LangGraph with Claude as the
primary LLM.

---

## Table of Contents

- [Problem](#problem)
- [Quick Start](#quick-start)
- [Architecture Overview](#architecture-overview)
- [The Three Agents](#the-three-agents)
  - [Meeting Briefing Agent](#1-meeting-briefing-agent)
  - [News Aggregator Agent](#2-news-aggregator-agent)
  - [Outreach Agent](#3-outreach-agent)
- [Frontend](#frontend)
- [Deployment](#deployment)
- [Configuration Guide](#configuration-guide)
  - [Environment Variables](#environment-variables)
  - [Changing Models](#changing-models)
  - [Changing API Providers](#changing-api-providers)
- [Batch Jobs](#batch-jobs)
- [Costs & Pricing](#costs--pricing)
- [Project Structure](#project-structure)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Team](#team)

---

## Problem

**VC investors spend 2-4 hours preparing for each meeting** — researching companies, synthesizing signals, and drafting talking points. This is repetitive, error-prone, and doesn't scale.

**NEA AI Agents automates meeting briefing preparation** by:
- Aggregating company data from Harmonic, Tavily, and Parallel Search
- Detecting key signals (funding, hiring, product launches)
- Generating structured briefings with citations and source attribution
- Creating personalized outreach messages

The result: **meeting prep in minutes, not hours**, with full traceability.

---

## Quick Start

### Backend (CLI / local dev)

```bash
# 1. Clone and setup
cd nea-ai-agents
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your API keys (see Configuration Guide below)

# 4. Run an agent from the CLI
python -m agents.meeting_briefing.briefing_generator --company_url stripe.com
```

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

The frontend proxies `/api/*` calls to the Python backend. For local dev, set
`BACKEND_URL=http://localhost:8000` in `frontend/.env.local` and run the FastAPI
server (`uvicorn services.api:app --reload --port 8000`) in another terminal.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            Browser (Next.js)                              │
│  app/(platform)/briefing  •  /digest  •  /outreach                        │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │ same-origin fetch  /api/*
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│        Next.js API proxy  (frontend/app/api/[...path]/route.ts)           │
│        - Injects X-NEA-Key server-side                                    │
│        - Forwards to BACKEND_URL                                          │
└──────────────────────────┬───────────────────────────────────────────────┘
                           │
        ┌──────────────────┴───────────────────┐
        │ POST /api/briefing, /api/outreach    │  GET /api/briefings, /digest/weekly, …
        ▼                                       ▼
┌───────────────────────────┐      ┌───────────────────────────┐
│  Vercel Python Functions  │      │  Long-running API         │
│  api/py/briefing.py       │      │  services/api.py (FastAPI)│
│  api/py/outreach.py       │      │  Local dev or managed     │
│  api/py/outreach-feedback │      │  deployment               │
│  (Fluid Compute, 300s)    │      └───────────────────────────┘
└────────────┬──────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                            Shared Services                                │
│  tools/company_tools.py   •   core/clients/*   •   core/database.py       │
└────────────┬─────────────────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Harmonic  •  Tavily  •  Parallel  •  HackerNews  •  Claude            │
│                                                                           │
│  Supabase (Postgres): company_core, founders, briefing_news,              │
│                       briefing_signals, briefing_competitors,             │
│                       outreach_history, watched_companies, job_runs       │
└──────────────────────────────────────────────────────────────────────────┘

Batch (scheduled on GitHub Actions — see .github/workflows/):
  news_refresh      every 6h  → scripts/run_news_refresh.py
  investor_digest   weekly    → scripts/run_investor_digest.py
```

### Data Flow

1. **Input**: Company URL (e.g., `stripe.com`) from the UI or CLI
2. **Data Ingestion**: `tools/company_tools.py` fetches from Harmonic, Parallel, Tavily
3. **Persistence**: Company bundle written to Supabase (no local SQLite)
4. **LLM Synthesis**: Claude generates the briefing / outreach / digest
5. **Response**: Returned to the browser; history also saved to Supabase

---

## The Three Agents

### 1. Meeting Briefing Agent

**Purpose**: Generate comprehensive meeting prep documents for investor meetings.

**Location**: `agents/meeting_briefing/briefing_generator.py`

**How it works**:
```
URL Input → ingest_company() (Harmonic + Tavily → Supabase) → generate_briefing() → Claude
```

`ingest_company()` populates the company bundle (profile, founders, signals, news, competitors)
in Supabase; `generate_briefing()` reads that bundle and synthesizes the final markdown
with Claude.

**Run it (CLI)**:
```bash
python -m agents.meeting_briefing.briefing_generator --company_url stripe.com
```

**Run it (HTTP)**:
```bash
curl -X POST http://localhost:3000/api/briefing \
  -H 'Content-Type: application/json' \
  -d '{"url":"stripe.com"}'
```

**Output sections**:
- TL;DR (2-3 sentences)
- Why This Meeting Matters
- Company Snapshot (table)
- Founders (with backgrounds)
- Key Signals
- In the News
- Competitive Landscape
- Meeting Prep (questions + next steps)

**Key files**:
| File | Purpose |
|------|---------|
| `briefing_generator.py` | Reads the company bundle from Supabase and calls Claude to produce the briefing |
| `../../api/py/briefing.py` | Vercel Function wrapper (POST `/api/briefing`) |

---

### 2. News Aggregator Agent

**Purpose**: Track portfolio companies and competitors for signals (funding, hires, launches).

**Location**: `agents/news_aggregator/agent.py`

**How it works**:
1. Maintains a watchlist of portfolio companies + competitors in Supabase
2. Periodically scans Harmonic (metrics) + Parallel Search + HackerNews (news)
3. Classifies signals, scores relevance, filters noise (semantic embeddings cache)
4. Generates investor digest (featured + summary articles, sentiment rollup)

**Run it**:
```bash
# Add a company to watchlist
python -m agents.news_aggregator.agent --add stripe.com --name Stripe --category portfolio

# Check for new signals
python -m agents.news_aggregator.agent --check

# Generate digest (last 7 days)
python -m agents.news_aggregator.agent --digest --days 7

# Show alerts only
python -m agents.news_aggregator.agent --alerts

# List all watched companies
python -m agents.news_aggregator.agent --list
```

**Signal types detected**:
| Type | Source | Description |
|------|--------|-------------|
| `funding` | Harmonic/News | Funding rounds |
| `acquisition` | News | M&A activity |
| `team_change` | News | Executive hires/departures |
| `product_launch` | News | Product announcements |
| `hiring_expansion` | Harmonic | Headcount changes |
| `web_traffic` | Harmonic | Traffic changes |

**Key files**:
| File | Purpose |
|------|---------|
| `agent.py` | CLI and orchestration |
| `detector.py` | Signal detection logic |
| `classification.py` | Signal-type classifier |
| `scorer.py` | Relevance/rank scoring |
| `embeddings.py` | Embedding dedupe cache (`embedding_cache.db`) |
| `database.py` | Watchlist storage (Supabase) |
| `investor_digest.py` | Digest generation |

---

### 3. Outreach Agent

**Purpose**: Generate personalized cold outreach emails/LinkedIn messages.

**Location**: `agents/outreach/agent.py`

**How it works**:
1. Ingests company data (reuses `company_tools.py`)
2. Auto-selects best founder contact
3. Detects "context type" (thesis-driven, problem-solving, etc.)
4. Loads investor voice profile from `profiles.yaml` + style examples
5. Generates personalized message via Claude
6. Optional feedback loop: approved/edited messages are logged via `/api/outreach/feedback`

**Run it**:
```bash
# Generate email (default investor: ashley)
python -m agents.outreach.agent --company stripe.com --format email

# As different investor
python -m agents.outreach.agent --company stripe.com --investor madison

# LinkedIn message
python -m agents.outreach.agent --company stripe.com --format linkedin

# Preview data without generating
python -m agents.outreach.agent --company stripe.com --preview

# List available investor profiles
python -m agents.outreach.agent --list-profiles
```

**Context types**:
- `thesis_driven_deep_dive` - Investment thesis alignment
- `problem_solving_discussion` - Pain point focused
- `founder_background_connection` - Shared background hook
- `stealth_founder_outreach` - Stealth mode (no public company info)

**Key files**:
| File | Purpose |
|------|---------|
| `agent.py` | CLI entry point |
| `generator.py` | Core generation pipeline |
| `context.py` | Investor profile loader |
| `profiles.yaml` | Investor voice/style data |
| `context_types.py` | Context type detection |
| `prompts.py` | Prompt building |
| `../../api/py/outreach.py` | Vercel Function wrapper (POST `/api/outreach`) |
| `../../api/py/outreach-feedback.py` | Feedback capture (POST `/api/outreach/feedback`) |

---

## Frontend

**Stack**: Next.js 16 App Router, React 19, TypeScript, Tailwind 4, shadcn/ui (Radix primitives).

**Structure**:
```
frontend/
├── app/
│   ├── (platform)/            # Authenticated/app layout group
│   │   ├── layout.tsx         # Sidebar shell
│   │   ├── briefing/page.tsx  # Meeting briefing UI
│   │   ├── digest/page.tsx    # Weekly news digest
│   │   └── outreach/page.tsx  # Outreach composer
│   ├── api/[...path]/route.ts # Server-side proxy → BACKEND_URL
│   ├── layout.tsx             # Root HTML shell
│   ├── page.tsx               # Landing → /briefing
│   └── globals.css            # Tailwind tokens (nea-blue, nea-surface, …)
├── components/
│   ├── layout/Sidebar.tsx     # App navigation
│   └── ui/*                   # shadcn/ui primitives
├── lib/
│   ├── api.ts                 # Typed client for /api/*
│   └── utils.ts               # cn() helper
├── public/                    # Logo + static assets
└── next.config.ts
```

**API proxy**: `/api/*` requests are intercepted by `app/api/[...path]/route.ts`, which
injects the `X-NEA-Key` header server-side and forwards to `BACKEND_URL`. POSTs to
`/api/briefing` and `/api/outreach` are also rewritten at the Vercel edge (see
`vercel.json`) directly to the Python Functions in `api/py/` — bypassing the proxy for
lower latency.

---

## Deployment

The project deploys as a Vercel monorepo:

- **Web UI**: Next.js build from `frontend/` (configured via `vercel.json:buildCommand`)
- **Compute**: Python Functions in `api/py/` (Fluid Compute, 300s default timeout)
- **Database**: Supabase (external — provision separately)
- **Batch jobs**: GitHub Actions scheduled workflows (see [Batch Jobs](#batch-jobs))

Minimum env vars in the Vercel project:
```
ANTHROPIC_API_KEY, HARMONIC_API_KEY, TAVILY_API_KEY, PARALLEL_API_KEY,
SUPABASE_URL, SUPABASE_SERVICE_KEY,
NEA_API_KEY, ALLOWED_ORIGINS,
BACKEND_URL                     # set to the Vercel production URL (or managed backend host)
```

**Deploy**:
```bash
vercel link            # first time only
vercel                 # preview
vercel --prod          # production
```

**Edge rewrites** (from `vercel.json`):
- `POST /api/briefing`          → `api/py/briefing.py`
- `POST /api/outreach`          → `api/py/outreach.py`
- `POST /api/outreach/feedback` → `api/py/outreach-feedback.py`

All other `/api/*` reads are served by the long-lived FastAPI app (`services/api.py`)
behind `BACKEND_URL` via the Next.js proxy.

**Auth gate**: Write endpoints require the `X-NEA-Key` header (HMAC-compared against
`NEA_API_KEY`). The Next.js proxy injects this server-side so the secret never reaches
the browser. Replaced by real auth (Clerk/Auth0) in Phase 3.

---

## Configuration Guide

### Environment Variables

Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
```

**Required API Keys**:

| Variable | Service | Required For | Get it from |
|----------|---------|--------------|-------------|
| `ANTHROPIC_API_KEY` | Claude LLM | All agents | [console.anthropic.com](https://console.anthropic.com/) |
| `HARMONIC_API_KEY` | Company data | Meeting briefing, News aggregator | [console.harmonic.ai](https://console.harmonic.ai/) |
| `SUPABASE_URL` | Database | All persistence | [supabase.com](https://supabase.com/) |
| `SUPABASE_SERVICE_KEY` | Database | All persistence | Supabase dashboard |

**Optional API Keys**:

| Variable | Service | Purpose | Get it from |
|----------|---------|---------|-------------|
| `TAVILY_API_KEY` | Website intelligence | Website signals | [tavily.com](https://tavily.com/) (FREE: 1K credits/month) |
| `PARALLEL_API_KEY` | News search | News articles | [parallel.ai](https://parallel.ai/) |
| ~~`SWARM_API_KEY`~~ | ~~Founder profiles~~ | ~~Background enrichment~~ | **DISABLED** (integration removed) |
| `OPENAI_API_KEY` | Embeddings | News-dedupe embeddings | [platform.openai.com](https://platform.openai.com/) |
| `LANGSMITH_API_KEY` | Tracing | Debugging/observability | [smith.langchain.com](https://smith.langchain.com/) |
| `LANGSMITH_TRACING` | Tracing toggle | `true` to enable | — |
| `LANGSMITH_PROJECT` | Project name | Defaults to `nea-briefing` / `nea-outreach` | — |

**Deployment-only**:

| Variable | Purpose |
|----------|---------|
| `ALLOWED_ORIGINS` | Comma-separated CORS allowlist (e.g. `https://nea.example.com`). Defaults to `http://localhost:3000`. |
| `NEA_API_KEY` | Shared-secret header (`X-NEA-Key`) gating write endpoints. Generate 32+ random chars. |
| `BACKEND_URL` | Used by the Next.js proxy to forward `/api/*` reads to the long-lived FastAPI app. |
| `NEXT_PUBLIC_API_URL` | Browser-side override for the API base (only for local multi-host dev). |

**Graceful Degradation**: Missing optional keys disable features but don't crash the system.

### Changing Models

Models are configured in each agent file. Here's where to change them:

**Meeting Briefing Agent** (`agents/meeting_briefing/briefing_generator.py`):
```python
DEFAULT_LLM_MODEL = "claude-sonnet-4-6"  # Change this
```

**Outreach Agent** (`agents/outreach/generator.py`):
```python
DEFAULT_LLM_MODEL = "claude-sonnet-4-5-20250929"  # Change this
```

**To switch models**, change the string to any supported model:

| Model | Provider | Best For | Cost |
|-------|----------|----------|------|
| `claude-sonnet-4-6` | Anthropic | Meeting briefings (structured output) | ~$3/1M input, $15/1M output |
| `claude-sonnet-4-5-20250929` | Anthropic | Outreach (creative writing) | ~$3/1M input, $15/1M output |
| `claude-3-5-haiku-20241022` | Anthropic | Fast, cheap tasks | ~$0.25/1M input, $1.25/1M output |
| `gpt-4o` | OpenAI | Alternative (legacy) | ~$2.50/1M input, $10/1M output |
| `gpt-4o-mini` | OpenAI | Cheap alternative | ~$0.15/1M input, $0.60/1M output |

### Changing API Providers

**To add or replace a data source**, edit the relevant client in `core/clients/` and wire it into
`tools/company_tools.py` (which orchestrates ingestion into the shared `CompanyBundle`).

| Client | File | Replace to change... |
|--------|------|---------------------|
| Harmonic | `core/clients/harmonic.py` | Company data source |
| Tavily | `core/clients/tavily.py` | Website intelligence |
| Parallel Search | `core/clients/parallel_search.py` | News search |
| ~~Swarm~~ | ~~`core/clients/swarm.py`~~ | **DISABLED** (integration removed) |
| HackerNews | `core/clients/hackernews.py` | Secondary news/discussion signal |
| Supabase | `core/clients/supabase_client.py` | Persistence backend |

---

## Batch Jobs

Long-running jobs (news refresh, investor digest) run on **GitHub Actions scheduled workflows**,
not on Vercel Cron. The Databricks Asset Bundle in `databricks.yml` is kept as documentation for
re-activation on a paid Databricks tier.

| Workflow | File | Schedule | Script |
|----------|------|----------|--------|
| News refresh | `.github/workflows/news_refresh.yml` | every 6h | `scripts/run_news_refresh.py` |
| Investor digest | `.github/workflows/investor_digest.yml` | weekly (Mon) | `scripts/run_investor_digest.py` |

**First-run verification**: Trigger manually via `workflow_dispatch` once, confirm new rows in
`job_runs` + `briefing_signals` + `briefing_news` Supabase tables, then let the cron enable.

**Notebooks**: `notebooks/batch/news_refresh.py` and `notebooks/batch/investor_digest.py` contain
the Databricks-ready versions of the same logic.

---

## Costs & Pricing

### Per-Company Costs (Estimated)

| Service | Cost | Notes |
|---------|------|-------|
| **Claude (Briefing)** | ~$0.02-0.05 | Varies by output length |
| **Claude (Outreach)** | ~$0.01-0.02 | Shorter outputs |
| **Harmonic** | Included | Subscription-based |
| **Tavily** | ~$0.02 | ~2 credits per crawl |
| **Parallel Search** | ~$0.01 | Per search query |
| ~~**Swarm**~~ | ~~Varies~~ | **DISABLED** (integration removed) |

### Monthly Projections

| Scale | Companies/Month | Estimated Cost |
|-------|-----------------|----------------|
| Light | 50 | ~$5-10 |
| Medium | 200 | ~$15-30 |
| Heavy | 500 | ~$35-60 |

### Cost Tracking

The system tracks costs automatically:
```python
from core.tracking import get_cost_summary

costs = get_cost_summary(days=30)
print(f"Total: ${costs['total_cost']:.2f}")
print(f"Per company: ${costs['cost_per_company']:.4f}")
```

---

## Project Structure

```
nea-ai-agents/
├── frontend/                     # Next.js 16 App Router UI
│   ├── app/
│   │   ├── (platform)/           # Sidebar-shell routes: briefing, digest, outreach
│   │   ├── api/[...path]/        # Server-side proxy → BACKEND_URL
│   │   ├── layout.tsx · page.tsx · globals.css
│   ├── components/{layout,ui}/   # Sidebar + shadcn/ui primitives
│   ├── lib/{api.ts,utils.ts}     # Typed API client
│   ├── public/                   # Logo, static assets
│   ├── next.config.ts · package.json · tsconfig.json
│
├── api/                          # Vercel Python Functions (Fluid Compute)
│   └── py/
│       ├── briefing.py           # POST /api/briefing        (300s)
│       ├── outreach.py           # POST /api/outreach        (300s)
│       └── outreach-feedback.py  # POST /api/outreach/feedback (60s)
│
├── agents/                       # The three AI agents
│   ├── meeting_briefing/
│   │   └── briefing_generator.py # DB-read → Claude briefing
│   ├── news_aggregator/
│   │   ├── agent.py · detector.py · classification.py
│   │   ├── scorer.py · embeddings.py · database.py · investor_digest.py
│   └── outreach/
│       ├── agent.py · generator.py · context.py
│       ├── context_types.py · prompts.py · profiles.yaml
│
├── core/                         # Shared infrastructure
│   ├── clients/                  # API client wrappers
│   │   ├── harmonic.py · tavily.py · parallel_search.py
│   │   ├── swarm.py · hackernews.py · supabase_client.py
│   ├── database.py               # Pydantic dataclasses + Supabase sync (no SQLite)
│   ├── schemas.py                # Pydantic validation
│   ├── tracking.py               # Cost/usage tracking
│   ├── observability.py          # Logging/tracing
│   ├── security.py               # Input validation
│   ├── resilience.py             # Retry/circuit-breaker helpers
│   ├── llm_validation.py · evaluation.py · eval_harness.py
│   ├── failure_analysis.py · quality_scoring.py · prompt_registry.py
│
├── services/                     # FastAPI backend (long-lived reads)
│   ├── api.py                    # Main app: list/get/delete briefings, digest, watchlist
│   ├── history.py                # Briefing history (Supabase)
│   ├── feedback.py               # Outreach feedback loop
│   ├── job_manager.py            # Background job tracking
│   ├── models.py                 # Pydantic request/response schemas
│   ├── logging_setup.py          # Structured JSON logs + LangSmith
│   ├── rate_limit.py             # Per-identifier rate limits
│
├── tools/
│   └── company_tools.py          # Multi-source ingestion into CompanyBundle
│
├── evaluation/                   # Eval harness + judge prompts
│   ├── run_eval.py · run_judge_batch.py · generate_outputs.py
│   ├── judge_prompts/ · results/ · test_outputs/
│
├── scripts/                      # Maintenance + batch entry points
│   ├── run_news_refresh.py       # Invoked by GitHub Actions
│   ├── run_investor_digest.py    # Invoked by GitHub Actions
│   ├── seed_nea_portfolio.py · view_tracking.py · cleanup_history.py
│
├── notebooks/
│   └── batch/                    # Databricks-ready versions of batch jobs
│       ├── news_refresh.py · investor_digest.py · requirements.txt
│
├── .github/workflows/            # Scheduled batch workflows
│   ├── news_refresh.yml          # every 6h
│   └── investor_digest.yml       # weekly
│
├── migrations/                   # Supabase SQL migrations (001–006)
├── tests/                        # Python test suite
├── databricks.yml                # Asset Bundle (documentation only)
├── vercel.json                   # Vercel build + function config
└── requirements.txt
```

---

## Development

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test files
pytest tests/test_harmonic_client.py -v
pytest tests/test_integration_pipeline.py -v

# With coverage
pytest tests/ --cov=. --cov-report=html
```

### API Server (local)

```bash
# Long-lived FastAPI server for /api/briefings, /api/digest/weekly, etc.
uvicorn services.api:app --reload --port 8000
```

Point the frontend at it by adding to `frontend/.env.local`:
```
BACKEND_URL=http://localhost:8000
NEA_API_KEY=some-dev-secret          # must match services/api.py's env
```

### Database Setup (Supabase)

1. Create a Supabase project at [supabase.com](https://supabase.com)
2. Run migrations in `migrations/001_…` through `006_…` via the SQL editor
3. Add `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` to `.env`

### History Cleanup

Records older than 30 days are pruned by a maintenance script:

```bash
# Preview (dry run)
python scripts/cleanup_history.py --dry-run

# Run cleanup
python scripts/cleanup_history.py
```

### Observability

Structured JSON logs + LangSmith tracing are wired into the Python Functions via
`services/logging_setup.py`. Enable with:

```bash
# In .env (or Vercel project settings)
LANGSMITH_API_KEY=your_key
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=nea-briefing
```

**Rate limits** (per `X-NEA-Key`): 10 briefings/min, 5 outreach/min. Exceeding returns
`429` with `Retry-After`.

**Log drains**: Vercel forwards production logs to the drain configured in
**Settings → Log Drains**. Supported providers include Axiom, BetterStack, Datadog,
Logflare, and Papertrail.

---

## Troubleshooting

### Common Issues

**"Company not found in Harmonic"**
- Check the URL format (use domain like `stripe.com`, not full URL)
- Verify `HARMONIC_API_KEY` is set
- Company may not exist in Harmonic's database

**"ANTHROPIC_API_KEY not set"**
- Add your key to `.env`
- Verify the file is named `.env` (not `.env.example`)

**401 `Missing or invalid X-NEA-Key`**
- `NEA_API_KEY` is set in the backend but the Next.js proxy isn't injecting it.
- Confirm `NEA_API_KEY` is configured in Vercel (or `frontend/.env.local`) and matches
  the backend value.

**`BACKEND_URL is not configured` from the proxy**
- Set `BACKEND_URL` in `frontend/.env.local` (local) or Vercel project settings (deployed).

**Empty news results**
- Check `PARALLEL_API_KEY` is set
- News may not exist for smaller companies

**Outreach generation fails**
- Run without `--skip-ingest` to fetch fresh data
- Check that founders exist in the database

### Graceful Degradation

| Missing Key | Behavior |
|-------------|----------|
| `HARMONIC_API_KEY` | **Blocks briefing** - required for company lookup |
| `ANTHROPIC_API_KEY` | **Blocks generation** - required for LLM |
| `TAVILY_API_KEY` | Website signals disabled; placeholder added |
| `PARALLEL_API_KEY` | News search disabled; empty results |
| ~~`SWARM_API_KEY`~~ | **N/A** (integration permanently disabled) |
| `OPENAI_API_KEY` | News-dedupe embeddings fall back to lexical comparison |

---

## Team

- Ana Garza
- Ellie Brew
- Juan Sandoval
- Luke Shuman

---

## License

MIT License - see [LICENSE](LICENSE) for details.
