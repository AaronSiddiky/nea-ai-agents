"""
Canonical identity bridge to NEA Scout.

Stanford's agent system primary keys companies by their domain string
(`company_id = 'stripe.com'`). NEA Scout uses an opaque UUID
`canonical_entities.id`. This module is the bridge -- given a domain (and
optional Harmonic id, name), it returns the matching `canonical_entity_id`
so every agent-written row carries the same canonical id NEA Scout uses.

Behavior:
- POST to `${NEA_BACKEND_URL}/api/v1/canonical/find-or-create` with
  `x-internal-token: ${NEA_INTERNAL_SECRET}`.
- In-process LRU cache (cachetools.TTLCache) keeps the resolver fast for
  repeated lookups; TTL 1h, max 10k entries. Misses cost ~150-400ms once.
- Returns `None` on any error (timeout, 5xx, missing env, etc.) so the
  caller writes the row anyway with `canonical_entity_id=NULL` -- the
  backfill script (`scripts/backfill_canonical_ids.py`) sweeps nulls later.

Env required:
  NEA_BACKEND_URL       e.g. https://app.neascout.com (NODE side)
  NEA_INTERNAL_SECRET   shared secret with Node `requireInternalToken`

Typical use site (inside `core/database.py` sync fns):
    from core.canonical_bridge import resolve_canonical_entity_id

    data = { ... }
    cid = resolve_canonical_entity_id(
        domain=company.company_id,
        name=company.company_name,
    )
    if cid:
        data["canonical_entity_id"] = cid
    supabase.table("briefing_companies").upsert(data, on_conflict="company_id").execute()
"""

from __future__ import annotations

import logging
import os
from typing import Optional

try:
    # cachetools is in requirements.txt; this is the standard Python LRU+TTL.
    from cachetools import TTLCache, cached  # type: ignore
    _HAS_CACHETOOLS = True
except Exception:  # pragma: no cover - keep import-safe if cachetools missing
    _HAS_CACHETOOLS = False

import requests  # already used elsewhere in the codebase

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Cache
# -----------------------------------------------------------------------------
# Cache key: (kind, domain, harmonic_id). Value: canonical_entity_id str (or "" for negative).
# We cache negative results too so an unresolvable domain doesn't re-hit Node
# every call -- the backfill script can run later with a forced-refresh path.
_CACHE_MAXSIZE = int(os.environ.get("CANONICAL_BRIDGE_CACHE_SIZE", "10000"))
_CACHE_TTL_SECONDS = int(os.environ.get("CANONICAL_BRIDGE_CACHE_TTL", "3600"))

if _HAS_CACHETOOLS:
    _CACHE: "TTLCache[tuple, str]" = TTLCache(maxsize=_CACHE_MAXSIZE, ttl=_CACHE_TTL_SECONDS)
else:
    _CACHE = {}  # type: ignore[assignment]


def _cache_get(key: tuple) -> Optional[str]:
    val = _CACHE.get(key)
    if val is None:
        return None
    # Empty string means we explicitly resolved to "no canonical".
    return val if val else None


def _cache_set(key: tuple, value: Optional[str]) -> None:
    _CACHE[key] = value or ""


def _http_resolve(payload: dict, timeout: float = 8.0) -> Optional[str]:
    backend_url = os.environ.get("NEA_BACKEND_URL")
    secret = os.environ.get("NEA_INTERNAL_SECRET")
    if not backend_url or not secret:
        logger.warning(
            "canonical_bridge: NEA_BACKEND_URL or NEA_INTERNAL_SECRET not set; "
            "returning None"
        )
        return None

    url = f"{backend_url.rstrip('/')}/api/v1/canonical/find-or-create"
    headers = {
        "content-type": "application/json",
        "x-internal-token": secret,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning(f"canonical_bridge: HTTP error talking to Node: {exc}")
        return None

    if resp.status_code != 200:
        logger.warning(
            f"canonical_bridge: Node returned {resp.status_code}: {resp.text[:200]}"
        )
        return None
    try:
        body = resp.json()
    except ValueError:
        logger.warning("canonical_bridge: Node returned non-JSON body")
        return None
    entity = body.get("entity") if isinstance(body, dict) else None
    eid = entity.get("id") if isinstance(entity, dict) else None
    if not eid:
        return None
    return str(eid)


def resolve_canonical_entity_id(
    domain: Optional[str] = None,
    *,
    harmonic_id: Optional[str] = None,
    name: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    kind: str = "company",
) -> Optional[str]:
    """
    Resolve a domain / harmonic_id / linkedin to a canonical_entities.id (UUID).

    Returns None if:
      - No identifiers were provided
      - The Node service is unreachable / not configured
      - The Node service couldn't enrich and couldn't create a stub

    Caller should write the row regardless; canonical_entity_id is nullable.
    """
    if kind not in ("company", "person"):
        kind = "company"

    domain = (domain or "").strip().lower() or None
    harmonic_id = (harmonic_id or "").strip() or None
    name = (name or "").strip() or None
    linkedin_url = (linkedin_url or "").strip() or None

    if not (domain or harmonic_id or name or linkedin_url):
        return None

    cache_key = (kind, domain or "", harmonic_id or "", linkedin_url or "")
    cached_val = _cache_get(cache_key)
    if cached_val is not None:
        return cached_val
    if cache_key in _CACHE and _CACHE.get(cache_key) == "":
        # Explicit negative cache hit
        return None

    payload: dict = {"type": kind}
    if name:
        payload["name"] = name
    if harmonic_id:
        payload["harmonic_id"] = harmonic_id
    if domain:
        # The Node endpoint accepts bare domains as website_url.
        payload["website_url"] = domain
    if linkedin_url:
        payload["linkedin_url"] = linkedin_url

    result = _http_resolve(payload)
    _cache_set(cache_key, result)
    return result


def clear_cache() -> None:
    """For tests / backfill scripts that want a fresh resolver state."""
    _CACHE.clear()
