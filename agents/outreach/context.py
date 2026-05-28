"""
Investor Context & Email Samples for Outreach Agent
=====================================================

Loads investor profiles from profiles.yaml and annotated email samples from
docs/email_samples.md. Provides the public API consumed by the generator:

    from agents.outreach.context import get_investor_context, load_samples

    profile = get_investor_context("ashley")
    samples = load_samples("ashley", context_type="thesis_driven_deep_dive")

All parsing uses PyYAML. Samples are split on ``---`` delimiters and their
YAML metadata blocks are extracted via regex.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml

logger = logging.getLogger(__name__)

# =========================================================================
# PATH CONSTANTS
# =========================================================================

_PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_SAMPLES_FILE = _PROJECT_ROOT / "docs" / "email_samples.md"
DEFAULT_PROFILES_FILE = _PROJECT_ROOT / "agents" / "outreach" / "profiles.yaml"

# Max samples to include in a prompt (high ceiling — use all available)
MAX_STYLE_SAMPLES = 50

# Promoted-only gating: when an investor has fewer than this many real
# (DB-promoted) examples for the chosen context type, fall back to filling
# remaining slots with hand-written seed samples from docs/email_samples.md.
# Set OUTREACH_USE_SYNTHETIC_FALLBACK=false to disable the fallback entirely.
MIN_PROMOTED_SAMPLES = 5


def _use_synthetic_fallback() -> bool:
    raw = os.environ.get("OUTREACH_USE_SYNTHETIC_FALLBACK", "true").strip().lower()
    return raw not in {"false", "0", "no", "off"}


# EmailSample.source values
SAMPLE_SOURCE_STATIC = "static_seed"           # hand-written examples in docs/email_samples.md
SAMPLE_SOURCE_PROMOTED_APPROVED = "promoted_approved"  # investor approved as-is
SAMPLE_SOURCE_PROMOTED_EDITED = "promoted_edited"      # investor edited before sending
SampleSource = Literal["static_seed", "promoted_approved", "promoted_edited"]

# Regex to extract fenced YAML blocks: ```yaml ... ```
_YAML_BLOCK_RE = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)


# =========================================================================
# DATA CLASSES
# =========================================================================

@dataclass
class InvestorProfile:
    """
    Mirrors a single entry in profiles.yaml.

    Provides format_for_prompt() to serialize the profile into a text block
    suitable for LLM prompt injection.
    """

    # Identity
    full_name: str
    role: str
    focus_areas: list[str] = field(default_factory=list)

    # Voice & style
    tone: str = ""
    intro_patterns: dict[str, str] = field(default_factory=dict)
    structural_pattern: str = ""
    sign_off_options: list[str] = field(default_factory=list)
    differentiators: str = ""

    # Portfolio & social proof
    portfolio_companies_to_reference: list[str] = field(default_factory=list)

    # Background & career history
    education: list[str] = field(default_factory=list)
    prior_career: list[str] = field(default_factory=list)
    prior_investments: list[str] = field(default_factory=list)

    # Optional fields
    location: Optional[str] = None
    firm_context_block: Optional[str] = None
    colleague_introductions: Optional[dict[str, str]] = None

    # Derived (not in YAML, set after loading)
    firm_name: str = "NEA"

    def format_for_prompt(self) -> str:
        """Serialize this profile into a text block for the LLM prompt."""
        lines: list[str] = []

        lines.append(f"Name: {self.full_name}")
        lines.append(f"Role: {self.role}")
        lines.append(f"Firm: {self.firm_name}")

        if self.focus_areas:
            lines.append(f"Focus Areas: {', '.join(self.focus_areas)}")

        if self.tone:
            lines.append(f"Tone: {self.tone.strip()}")

        if self.intro_patterns:
            lines.append("Intro Patterns:")
            for label, pattern in self.intro_patterns.items():
                lines.append(f"  {label}: {pattern.strip()}")

        if self.structural_pattern:
            lines.append(f"Structural Pattern: {self.structural_pattern.strip()}")

        if self.sign_off_options:
            lines.append(
                f"Sign-Off Options: {' | '.join(s.replace(chr(10), ' / ') for s in self.sign_off_options)}"
            )

        if self.differentiators:
            lines.append(f"Differentiators: {self.differentiators.strip()}")

        if self.portfolio_companies_to_reference:
            lines.append(
                f"Portfolio Companies: {', '.join(self.portfolio_companies_to_reference)}"
            )

        if self.education:
            lines.append(f"Education: {'; '.join(self.education)}")

        if self.prior_career:
            lines.append("Prior Career:")
            for entry in self.prior_career:
                lines.append(f"  - {entry}")

        if self.prior_investments:
            lines.append(
                f"Prior Investments (pre-NEA): {', '.join(self.prior_investments)}"
            )

        if self.location:
            lines.append(f"Location: {self.location}")

        if self.firm_context_block:
            lines.append(f"Firm Context: {self.firm_context_block.strip()}")

        if self.colleague_introductions:
            lines.append("Colleague Introductions:")
            for label, intro in self.colleague_introductions.items():
                lines.append(f"  {label}: {intro.strip()}")

        return "\n".join(lines)


@dataclass
class EmailSample:
    """
    A single annotated email sample parsed from the samples markdown file.

    Fields mirror the YAML metadata block plus the email body text.
    """

    investor: str
    recipient: str
    company: str
    context_type: str
    personalization_signals: list[str] = field(default_factory=list)
    length: str = "medium"
    body: str = ""
    exclude_from_outreach: bool = False
    human_edited: bool = False   # True for examples the investor edited before sending
    # Provenance: where the example came from. Drives the promoted-only
    # filter in select_samples — static_seed examples are only used as a
    # fallback when the investor's promoted pool is below MIN_PROMOTED_SAMPLES.
    source: SampleSource = SAMPLE_SOURCE_STATIC


# =========================================================================
# LOADING FUNCTIONS
# =========================================================================

def load_profiles(
    file_path: str | Path | None = None,
) -> dict[str, InvestorProfile]:
    """
    Load investor profiles from a YAML file.

    Args:
        file_path: Path to profiles.yaml. Defaults to
            agents/outreach/profiles.yaml.

    Returns:
        Dict mapping lowercase investor key to InvestorProfile.
    """
    path = Path(file_path) if file_path else DEFAULT_PROFILES_FILE

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error(f"Profiles file not found: {path}")
        return {}
    except yaml.YAMLError as e:
        logger.error(f"Failed to parse profiles YAML: {e}")
        return {}

    profiles: dict[str, InvestorProfile] = {}
    for key, data in raw.items():
        try:
            profiles[key] = InvestorProfile(
                full_name=data["full_name"],
                role=data["role"],
                focus_areas=data.get("focus_areas", []),
                tone=data.get("tone", ""),
                intro_patterns=data.get("intro_patterns", {}),
                structural_pattern=data.get("structural_pattern", ""),
                sign_off_options=data.get("sign_off_options", []),
                differentiators=data.get("differentiators", ""),
                portfolio_companies_to_reference=data.get(
                    "portfolio_companies_to_reference", []
                ),
                education=data.get("education", []),
                prior_career=data.get("prior_career", []),
                prior_investments=data.get("prior_investments", []),
                location=data.get("location"),
                firm_context_block=data.get("firm_context_block"),
                colleague_introductions=data.get("colleague_introductions"),
            )
        except KeyError as e:
            logger.warning(f"Skipping profile '{key}': missing required field {e}")

    return profiles


def load_all_samples(
    file_path: str | Path | None = None,
) -> list[EmailSample]:
    """
    Parse all annotated email samples from the markdown file.

    Splits the file on ``---`` delimiters, extracts the ```yaml``` metadata
    block from each chunk via regex, and treats the remaining text as the
    email body.

    Args:
        file_path: Path to the samples markdown file. Defaults to
            docs/email_samples.md.

    Returns:
        List of EmailSample objects. Empty list if file not found.
    """
    path = Path(file_path) if file_path else DEFAULT_SAMPLES_FILE

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(f"Samples file not found: {path}")
        return []
    except OSError as e:
        logger.warning(f"Could not read samples file {path}: {e}")
        return []

    chunks = text.split("---")
    samples: list[EmailSample] = []

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue

        # Extract YAML metadata block
        yaml_match = _YAML_BLOCK_RE.search(chunk)
        if not yaml_match:
            # No metadata — skip (likely the file header)
            continue

        try:
            metadata = yaml.safe_load(yaml_match.group(1))
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse sample YAML block: {e}")
            continue

        if not isinstance(metadata, dict):
            continue

        # Everything after the YAML block is the email body
        body = chunk[yaml_match.end():].strip()
        if not body:
            continue

        samples.append(EmailSample(
            investor=metadata.get("investor", "unknown"),
            recipient=metadata.get("recipient", "unknown"),
            company=metadata.get("company", "unknown"),
            context_type=metadata.get("context_type", "unknown"),
            personalization_signals=metadata.get("personalization_signals", []),
            length=metadata.get("length", "medium"),
            body=body,
            exclude_from_outreach=metadata.get("exclude_from_outreach", False),
            source=SAMPLE_SOURCE_STATIC,
        ))

    return samples


# =========================================================================
# SAMPLE SELECTION
# =========================================================================

def _sample_sort_key(s: EmailSample) -> tuple[int, int]:
    """Sort: promoted_edited < promoted_approved < static_seed, then shortest first."""
    rank = {
        SAMPLE_SOURCE_PROMOTED_EDITED: 0,
        SAMPLE_SOURCE_PROMOTED_APPROVED: 1,
        SAMPLE_SOURCE_STATIC: 2,
    }.get(s.source, 3)
    return (rank, len(s.body))


def select_samples(
    all_samples: list[EmailSample],
    investor_key: str,
    context_type: Optional[str] = None,
    max_count: int = MAX_STYLE_SAMPLES,
    min_promoted: int = MIN_PROMOTED_SAMPLES,
) -> list[EmailSample]:
    """
    Select the best style examples for a given investor and context type.

    Promoted-only policy:
    - Default behavior: only DB-promoted samples (source = promoted_edited /
      promoted_approved) are returned. Static_seed samples drag voice toward
      the synthetic baseline and are excluded.
    - Fallback: when the investor has fewer than ``min_promoted`` promoted
      examples available (across all context types), static_seed samples fill
      the remainder. The env var OUTREACH_USE_SYNTHETIC_FALLBACK=false
      disables this fallback entirely.

    Filtering pipeline:
    1. Keep only samples from the target investor, exclude exclude_from_outreach.
    2. Split into promoted vs. static_seed pools.
    3. If promoted count < min_promoted and fallback is enabled, merge in the
       static_seed pool; otherwise return promoted-only.
    4. Prefer samples whose context_type matches the current scenario; fill
       remainder with other context_types from the same investor.
    5. Sort: promoted_edited > promoted_approved > static_seed, then by body
       length (shorter first) for token efficiency.

    Args:
        all_samples: Full list of parsed EmailSample objects.
        investor_key: Lowercase investor identifier (e.g., "ashley").
        context_type: Optional context_type string to prefer.
        max_count: Maximum number of samples to return.
        min_promoted: Minimum promoted-sample count before static seeds are mixed in.

    Returns:
        List of up to max_count EmailSample objects.
    """
    # Step 1: filter to this investor, exclude internal
    eligible = [
        s for s in all_samples
        if s.investor == investor_key and not s.exclude_from_outreach
    ]

    if not eligible:
        return []

    # Step 2 + 3: gate the static-seed pool
    promoted = [s for s in eligible if s.source != SAMPLE_SOURCE_STATIC]
    static = [s for s in eligible if s.source == SAMPLE_SOURCE_STATIC]

    use_fallback = _use_synthetic_fallback() and len(promoted) < min_promoted
    pool = promoted + static if use_fallback else promoted

    # Health-check logging — make it easy to see which investors still rely on seeds
    logger.info(
        f"select_samples[investor={investor_key} context_type={context_type or 'any'}]: "
        f"promoted={len(promoted)} static={len(static)} "
        f"synthetic_used={use_fallback}"
    )

    if not pool:
        # No promoted examples and fallback disabled — return empty rather than
        # silently injecting seeds.
        return []

    if context_type:
        # Step 4: matching context_type first
        matching = [s for s in pool if s.context_type == context_type]
        non_matching = [s for s in pool if s.context_type != context_type]

        matching.sort(key=_sample_sort_key)
        non_matching.sort(key=_sample_sort_key)

        selected = matching[:max_count]
        remaining_slots = max_count - len(selected)
        if remaining_slots > 0:
            selected.extend(non_matching[:remaining_slots])
    else:
        pool.sort(key=_sample_sort_key)
        selected = pool[:max_count]

    return selected


# =========================================================================
# PUBLIC API
# =========================================================================

# Module-level caches
_profiles_cache: Optional[dict[str, InvestorProfile]] = None
_samples_cache: Optional[list[EmailSample]] = None


def get_investor_context(
    investor_key: str,
    profiles_file: str | Path | None = None,
) -> InvestorProfile:
    """
    Load and return an InvestorProfile by key.

    Caches profiles after first load. Falls back to a minimal default profile
    if the key is not found.

    Args:
        investor_key: Lowercase investor identifier (e.g., "ashley").
        profiles_file: Optional override path to profiles.yaml.

    Returns:
        InvestorProfile for the requested investor.
    """
    global _profiles_cache

    if _profiles_cache is None or profiles_file is not None:
        _profiles_cache = load_profiles(profiles_file)

    if investor_key in _profiles_cache:
        return _profiles_cache[investor_key]

    logger.warning(
        f"Investor '{investor_key}' not found in profiles. "
        f"Available: {list(_profiles_cache.keys())}. Using fallback."
    )
    return InvestorProfile(
        full_name=investor_key.title(),
        role="Investor",
    )


def load_samples(
    investor_key: str,
    context_type: Optional[str] = None,
    samples_file: str | Path | None = None,
    max_count: int = MAX_STYLE_SAMPLES,
) -> list[EmailSample]:
    """
    Load static-seed email samples only (from docs/email_samples.md).

    Most callers should use :func:`load_combined_samples` instead, which
    merges DB-promoted samples and applies the promoted-only policy.

    Args:
        investor_key: Lowercase investor identifier (e.g., "ashley").
        context_type: Optional context_type string to prefer in selection.
        samples_file: Optional override path to samples markdown file.
        max_count: Maximum number of samples to return.

    Returns:
        List of selected EmailSample objects (static seeds only).
    """
    global _samples_cache

    if _samples_cache is None or samples_file is not None:
        _samples_cache = load_all_samples(samples_file)

    return select_samples(
        all_samples=_samples_cache,
        investor_key=investor_key,
        context_type=context_type,
        max_count=max_count,
    )


def load_combined_samples(
    investor_key: str,
    context_type: Optional[str] = None,
    samples_file: str | Path | None = None,
    max_count: int = MAX_STYLE_SAMPLES,
) -> list[EmailSample]:
    """
    Load static seeds + DB-promoted samples and apply the promoted-only policy.

    This is the single entry point for the outreach generator. It replaces
    the duplicated merge logic previously inlined at each generator call site.

    Promoted samples come from the ``outreach_feedback`` Supabase table via
    :func:`services.feedback.load_promoted_samples`. If that call fails, the
    function falls back to static-seed-only selection so generation is never
    blocked by a Supabase outage.

    Args:
        investor_key: Lowercase investor identifier (e.g., "ashley").
        context_type: Optional context_type string to prefer in selection.
        samples_file: Optional override path to the static samples markdown file.
        max_count: Maximum number of samples to return.

    Returns:
        List of selected EmailSample objects, ordered promoted-first.
    """
    global _samples_cache

    if _samples_cache is None or samples_file is not None:
        _samples_cache = load_all_samples(samples_file)

    static = list(_samples_cache)

    try:
        from services.feedback import load_promoted_samples
        promoted = load_promoted_samples(investor_key)
    except Exception as exc:
        logger.warning(
            f"load_promoted_samples failed for {investor_key}, using static only: {exc}"
        )
        promoted = []

    return select_samples(
        all_samples=promoted + static,
        investor_key=investor_key,
        context_type=context_type,
        max_count=max_count,
    )
