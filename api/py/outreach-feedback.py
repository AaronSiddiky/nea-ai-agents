"""
Vercel Python Function: outreach feedback persistence.

Mounted externally at /api/outreach/feedback via vercel.json rewrites.
"""
from __future__ import annotations

import hmac
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(override=False)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.models import OutreachFeedbackRequest, OutreachFeedbackResponse
from services.logging_setup import setup_logging, setup_langsmith, get_logger
from services.auth import USE_CLERK_AUTH, verify_clerk_token

# Configure structured logging and LangSmith tracing
setup_logging(use_json=True)
setup_langsmith(project="nea-outreach-feedback")
logger = get_logger(__name__)

app = FastAPI(title="NEA Outreach Feedback Function", version="3.0.0")

_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-NEA-Key", "Authorization"],
)

NEA_API_KEY = os.getenv("NEA_API_KEY")


@app.middleware("http")
async def require_auth(request: Request, call_next):
    """
    Phase 3.1: Dual-mode authentication.
    """
    if request.method == "POST":
        if USE_CLERK_AUTH:
            # Clerk JWT authentication
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return JSONResponse(status_code=401, content={"detail": "Missing Authorization header"})

            token = auth_header[7:]
            claims = verify_clerk_token(token)
            if not claims:
                return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})

            request.state.user_id = claims.get("sub")
        elif NEA_API_KEY:
            # Legacy X-NEA-Key authentication
            provided = request.headers.get("x-nea-key", "")
            if provided and not hmac.compare_digest(provided, NEA_API_KEY):
                return JSONResponse(status_code=401, content={"detail": "Invalid X-NEA-Key"})

    return await call_next(request)


def _save(request: OutreachFeedbackRequest) -> OutreachFeedbackResponse:
    from services.feedback import save_feedback, FeedbackRecord, PROMOTABLE_STATUSES

    if request.approval_status == "edited" and not request.edited_message:
        raise HTTPException(
            status_code=422, detail="edited_message is required when approval_status is 'edited'"
        )

    record = FeedbackRecord(
        outreach_id=request.outreach_id,
        investor_key=request.investor_key,
        company_id=request.company_id,
        context_type=request.context_type,
        original_message=request.original_message,
        edited_message=request.edited_message,
        approval_status=request.approval_status,
        investor_notes=request.investor_notes,
    )

    try:
        record_id = save_feedback(record)
    except Exception as exc:
        logger.error("Failed to save outreach feedback: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save feedback: {exc}")

    return OutreachFeedbackResponse(
        id=record_id,
        approval_status=request.approval_status,
        promoted=request.approval_status in PROMOTABLE_STATUSES,
    )


@app.post("/api/outreach/feedback", response_model=OutreachFeedbackResponse)
async def create_feedback_rewritten(request: OutreachFeedbackRequest):
    return _save(request)


@app.post("/", response_model=OutreachFeedbackResponse)
async def create_feedback_root(request: OutreachFeedbackRequest):
    return _save(request)
