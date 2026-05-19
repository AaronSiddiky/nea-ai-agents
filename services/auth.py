"""
Authentication utilities for JWT verification.

Supports two JWT modes (set via env feature flags):
    USE_SUPABASE_AUTH=true  -> verify HS256 Supabase user tokens via SUPABASE_JWT_SECRET (preferred)
    USE_CLERK_AUTH=true     -> verify RS256 Clerk tokens via CLERK_JWKS_URL (legacy)

If both are off, the legacy X-NEA-Key shared secret guard (in services/api.py
middleware) is used. If both are on, Supabase is tried first.

Usage:
    from services.auth import (
        USE_SUPABASE_AUTH, USE_CLERK_AUTH,
        verify_supabase_token, verify_clerk_token, get_user_id,
    )
"""

import os
import logging
from functools import lru_cache
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Feature flags
USE_CLERK_AUTH = os.getenv("USE_CLERK_AUTH", "false").lower() == "true"
USE_SUPABASE_AUTH = os.getenv("USE_SUPABASE_AUTH", "false").lower() == "true"

# Clerk JWKS URL for fetching public keys
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL")

# Supabase HS256 JWT signing secret (project-level, from Supabase dashboard ->
# Settings -> API -> JWT Settings). Used to verify user-issued tokens.
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


@lru_cache(maxsize=1)
def get_clerk_jwks() -> Optional[dict]:
    """
    Fetch Clerk JWKS (JSON Web Key Set) and cache it.

    Returns:
        JWKS dict or None if not configured/available.
    """
    if not CLERK_JWKS_URL:
        logger.warning("CLERK_JWKS_URL not set, Clerk auth will fail")
        return None

    try:
        response = httpx.get(CLERK_JWKS_URL, timeout=5.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch Clerk JWKS: {e}")
        return None


def verify_clerk_token(token: str) -> Optional[dict]:
    """
    Verify a Clerk JWT and return its claims.

    Args:
        token: The JWT token string (without "Bearer " prefix)

    Returns:
        Dict of JWT claims if valid, None if invalid/expired.
    """
    try:
        import jwt
        from jwt.algorithms import RSAAlgorithm
    except ImportError:
        logger.error("PyJWT not installed. Run: pip install pyjwt[crypto]")
        return None

    jwks = get_clerk_jwks()
    if not jwks:
        return None

    try:
        # Get the key ID from the token header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")

        if not kid:
            logger.warning("JWT missing 'kid' header")
            return None

        # Find the matching key in JWKS
        key_data = None
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                key_data = key
                break

        if not key_data:
            logger.warning(f"No matching key found for kid: {kid}")
            return None

        # Convert JWK to public key
        public_key = RSAAlgorithm.from_jwk(key_data)

        # Verify and decode the token
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={
                "verify_aud": False,  # Clerk tokens may not have aud claim
                "verify_iss": True,
            },
            # Clerk issuer format: https://<your-domain>.clerk.accounts.dev
            # We skip strict issuer check for flexibility
            issuer=None,
        )

        return claims

    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error verifying JWT: {e}")
        return None


def get_user_id(request) -> Optional[str]:
    """
    Extract user_id from request, supporting Supabase, Clerk, or neither.

    Resolution order:
        1. If USE_SUPABASE_AUTH is on, try HS256 verification (returns auth.users.id UUID).
        2. If USE_CLERK_AUTH is on, try RS256 verification (returns Clerk user id).
        3. Otherwise return None.

    Args:
        request: FastAPI Request object

    Returns:
        User ID (sub claim) if authenticated, None otherwise.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]

    if USE_SUPABASE_AUTH:
        claims = verify_supabase_token(token)
        if claims:
            return claims.get("sub")

    if USE_CLERK_AUTH:
        claims = verify_clerk_token(token)
        if claims:
            return claims.get("sub")

    return None


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
