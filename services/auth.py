"""
Authentication utilities for JWT verification.

Post-NEA merge (M5) this module is Supabase-only: every protected write
endpoint requires an Authorization: Bearer <supabase_jwt> header signed
with the project's HS256 JWT secret. Clerk RS256 and the legacy X-NEA-Key
shared secret have been removed.

Env vars:
    USE_SUPABASE_AUTH=true     enforce auth (must be true in production)
    SUPABASE_JWT_SECRET=...    Supabase project JWT signing secret

Usage:
    from services.auth import (
        USE_SUPABASE_AUTH,
        verify_supabase_token,
        get_user_id,
    )
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

USE_SUPABASE_AUTH = os.getenv("USE_SUPABASE_AUTH", "false").lower() == "true"
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")


def verify_supabase_token(token: str) -> Optional[dict]:
    """
    Verify a Supabase user JWT (HS256) and return its claims.

    Supabase issues HS256 JWTs signed with the project's JWT secret. The `sub`
    claim is the `auth.users.id` UUID, which is the canonical NEA user_id.

    Args:
        token: The JWT token string (without "Bearer " prefix).

    Returns:
        Dict of JWT claims if valid, None if invalid / expired / misconfigured.
    """
    if not SUPABASE_JWT_SECRET:
        logger.warning("SUPABASE_JWT_SECRET not set, Supabase auth will fail")
        return None
    try:
        import jwt
    except ImportError:
        logger.error("PyJWT not installed. Run: pip install pyjwt")
        return None
    try:
        claims = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return claims
    except jwt.ExpiredSignatureError:
        logger.warning("Supabase JWT expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid Supabase JWT: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error verifying Supabase JWT: {e}")
        return None


def get_user_id(request) -> Optional[str]:
    """
    Extract user_id from a request's Authorization header.

    Returns the `sub` claim (auth.users.id UUID) if the JWT verifies, else None.
    Prefer `get_user_id_from_state` in request handlers — the middleware has
    already done the work.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    claims = verify_supabase_token(token)
    return claims.get("sub") if claims else None


def get_user_id_from_state(request) -> Optional[str]:
    """
    Get user_id from request.state (set by middleware).

    This is the preferred method after middleware has run.

    Args:
        request: FastAPI Request object

    Returns:
        User ID if set by middleware, None otherwise.
    """
    return getattr(request.state, "user_id", None)
