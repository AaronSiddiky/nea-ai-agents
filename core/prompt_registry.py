"""
Prompt Registry and Model Configuration
========================================

Centralized management of prompts and model configurations for reproducibility
and regression detection.

Why this is crucial:
1. Prompts are the "source code" of LLM behavior - changes need tracking
2. Model versions affect output quality - regressions can go unnoticed
3. Without versioning, you can't reproduce past results or compare A/B tests
4. Debugging requires knowing exactly what prompt+model produced an output

Usage:
    from core.prompt_registry import (
        get_prompt,
        get_model_config,
        PromptRegistry,
        ModelConfig,
    )

    # Get a versioned prompt
    prompt = get_prompt("briefing_system")
    print(prompt.content)
    print(prompt.version)

    # Get model configuration
    config = get_model_config("briefing")
    llm = ChatOpenAI(model=config.model, temperature=config.temperature)

    # Log which prompt/model was used
    tracker.log_llm_call(
        prompt_id=prompt.id,
        prompt_version=prompt.version,
        model_config=config.to_dict(),
        ...
    )
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# =============================================================================
# MODEL CONFIGURATION
# =============================================================================

class ModelProvider(str, Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


@dataclass
class ModelConfig:
    """
    Configuration for an LLM model.

    Captures all parameters that affect model behavior for reproducibility.
    """
    # Model identification
    name: str  # Config name (e.g., "briefing", "summarization")
    model: str  # Model ID (e.g., "gpt-4o-mini")
    provider: ModelProvider = ModelProvider.OPENAI

    # Generation parameters
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0

    # Metadata
    version: str = "1.0.0"
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/storage."""
        return {
            "name": self.name,
            "model": self.model,
            "provider": self.provider.value,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "version": self.version,
        }

    @property
    def config_hash(self) -> str:
        """Generate a hash of the config for change detection."""
        config_str = f"{self.model}:{self.temperature}:{self.max_tokens}:{self.top_p}"
        return hashlib.sha256(config_str.encode()).hexdigest()[:12]


# =============================================================================
# PROMPT DEFINITION
# =============================================================================

@dataclass
class Prompt:
    """
    A versioned prompt template.

    Prompts are immutable - changes create new versions.
    """
    # Identification
    id: str  # Unique identifier (e.g., "briefing_system_v1")
    name: str  # Human-readable name
    version: str  # Semantic version (e.g., "1.0.0")

    # Content
    content: str  # The actual prompt text
    description: str = ""  # What this prompt does

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    author: str = ""
    tags: list[str] = field(default_factory=list)

    # For prompt templates with variables
    variables: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Compute content hash after initialization."""
        self._content_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute SHA-256 hash of prompt content."""
        return hashlib.sha256(self.content.encode()).hexdigest()

    @property
    def content_hash(self) -> str:
        """Get the content hash (first 12 chars of SHA-256)."""
        return self._content_hash[:12]

    @property
    def full_id(self) -> str:
        """Get full identifier including version and hash."""
        return f"{self.id}@{self.version}#{self.content_hash}"

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/storage."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "content_hash": self.content_hash,
            "full_id": self.full_id,
            "description": self.description,
            "created_at": self.created_at,
            "variables": self.variables,
        }

    def format(self, **kwargs) -> str:
        """
        Format the prompt with variables.

        Args:
            **kwargs: Variable values to substitute

        Returns:
            Formatted prompt string

        Raises:
            KeyError: If required variable is missing
        """
        if not self.variables:
            return self.content

        missing = [v for v in self.variables if v not in kwargs]
        if missing:
            raise KeyError(f"Missing required variables: {missing}")

        return self.content.format(**kwargs)


# =============================================================================
# PROMPT REGISTRY
# =============================================================================

class PromptRegistry:
    """
    Central registry for all prompts and model configurations.

    Provides versioning, lookup, and change detection.
    """

    def __init__(self):
        self._prompts: dict[str, Prompt] = {}
        self._model_configs: dict[str, ModelConfig] = {}
        self._register_defaults()

    def _register_defaults(self):
        """Register all default prompts and model configs."""
        # Register model configurations
        self._register_default_model_configs()
        # Register prompts
        self._register_default_prompts()

    def _register_default_model_configs(self):
        """Register default model configurations."""

        # Main briefing generation
        self.register_model_config(ModelConfig(
            name="briefing",
            model="claude-sonnet-4-6",
            provider=ModelProvider.ANTHROPIC,
            temperature=0.0,
            max_tokens=4096,
            description="Primary model for meeting briefing generation",
            version="2.1.0",
        ))

        # Founder background summarization
        self.register_model_config(ModelConfig(
            name="summarization",
            model="claude-haiku-4-5-20251001",
            provider=ModelProvider.ANTHROPIC,
            temperature=0.0,
            description="Model for summarizing founder backgrounds",
            version="2.0.0",
        ))

        # High-quality generation (for critical outputs)
        self.register_model_config(ModelConfig(
            name="high_quality",
            model="claude-sonnet-4-6",
            provider=ModelProvider.ANTHROPIC,
            temperature=0.0,
            description="Higher quality model for critical generation tasks",
            version="2.0.0",
        ))

        # Outreach message generation (Claude Sonnet for superior writing quality)
        self.register_model_config(ModelConfig(
            name="outreach",
            model="claude-sonnet-4-5-20250929",
            provider=ModelProvider.ANTHROPIC,
            temperature=0.3,
            description="Claude Sonnet for personalized outreach message generation (call 1 of 2 — draft)",
            version="2.0.0",
        ))

        # Outreach cleanup pass (Claude Haiku — scrubs surface-level AI tells
        # from the draft without touching personalization or structure).
        self.register_model_config(ModelConfig(
            name="outreach_cleanup",
            model="claude-haiku-4-5-20251001",
            provider=ModelProvider.ANTHROPIC,
            temperature=0.1,
            description="Claude Haiku for de-LLM cleanup of outreach drafts (call 2 of 2 — register/AI-tell scrub)",
            version="1.0.0",
        ))

    def _register_default_prompts(self):
        """Register default prompts with versioning."""

        # Briefing system prompt
        self.register_prompt(Prompt(
            id="briefing_system",
            name="Briefing System Prompt",
            version="1.0.0",
            description="System prompt for meeting briefing generation",
            content="""You are an AI assistant generating meeting briefings for venture capital investors.

CRITICAL RULES:
- You may ONLY use the data provided from the database tables below.
- Do NOT use outside knowledge.
- If data is missing, say "Not found in table" or "Source not yet implemented."
- Do NOT infer, guess, or hallucinate facts.
- Be succinct but comprehensive.
- Use the exact structure provided.

Your output MUST follow the structure exactly as specified in the user prompt.""",
            author="system",
            tags=["briefing", "system", "vc"],
        ))

        # Founder summarization system prompt
        self.register_prompt(Prompt(
            id="founder_summary_system",
            name="Founder Summary System Prompt",
            version="1.0.0",
            description="System prompt for founder background summarization",
            content="""You are a VC research assistant creating concise founder backgrounds.
Your task is to summarize a founder's background in 2-4 sentences.

Rules:
- Focus on PRIOR experience (not their current role - that's already displayed elsewhere)
- Highlight: previous companies, notable roles, education, achievements
- Skip: current role details, generic skills lists, redundant info
- Be factual and concise
- If they were at notable companies (Google, Meta, OpenAI, etc.), mention it
- If they have a technical background (PhD, engineering), mention it
- If they previously founded or exited a company, mention it""",
            author="system",
            tags=["founder", "summarization"],
        ))

        # Founder summarization user prompt template
        self.register_prompt(Prompt(
            id="founder_summary_user",
            name="Founder Summary User Prompt",
            version="1.0.0",
            description="User prompt template for founder background summarization",
            content="""Summarize this founder's background for a VC meeting brief.

Founder: {name}
Current Role: {role_title} at {company_name}

Raw Background Data:
{raw_background}

Write a 2-4 sentence summary focusing on their PRIOR experience and credentials (not their current role at {company_name}).""",
            author="system",
            tags=["founder", "summarization", "template"],
            variables=["name", "role_title", "company_name", "raw_background"],
        ))

        # Outreach system prompt
        self.register_prompt(Prompt(
            id="outreach_system",
            name="Outreach System Prompt",
            version="1.0.0",
            description="System prompt for personalized outreach message generation",
            content="""You are an AI assistant generating personalized cold outreach messages for venture capital investors to send to startup founders.

CRITICAL RULES:
- Use ONLY the provided data about the company, founder, and investor. Do NOT hallucinate or infer facts.
- Reference specific data points from the provided context (funding rounds, signals, founder background, product details).
- Write in a peer-to-peer tone — one professional to another. NOT salesy, NOT generic.
- Show genuine interest by citing concrete details about the company or founder.
- If the founder has a notable background, mention shared context naturally (do not force it).
- Keep the message concise and respectful of the founder's time.

FORMAT RULES:
- For EMAIL format: Keep under 150 words. Start with a "Subject:" line on its own, then a blank line, then the message body.
- For LINKEDIN format: Keep under 100 words. No subject line. Open with a brief, personalized hook.

TONE:
- Professional but warm
- Curious, not presumptuous
- Specific, not templated
- Investor reaching out as a peer, not pitching services""",
            author="system",
            tags=["outreach", "system", "vc"],
        ))

    # =========================================================================
    # PROMPT MANAGEMENT
    # =========================================================================

    def register_prompt(self, prompt: Prompt) -> None:
        """
        Register a prompt in the registry.

        Args:
            prompt: Prompt to register
        """
        self._prompts[prompt.id] = prompt
        logger.debug(f"Registered prompt: {prompt.full_id}")

    def get_prompt(self, prompt_id: str) -> Prompt:
        """
        Get a prompt by ID.

        Args:
            prompt_id: Prompt identifier

        Returns:
            Prompt object

        Raises:
            KeyError: If prompt not found
        """
        if prompt_id not in self._prompts:
            raise KeyError(f"Prompt not found: {prompt_id}")
        return self._prompts[prompt_id]

    def list_prompts(self) -> list[dict]:
        """List all registered prompts with metadata."""
        return [p.to_dict() for p in self._prompts.values()]

    # =========================================================================
    # MODEL CONFIG MANAGEMENT
    # =========================================================================

    def register_model_config(self, config: ModelConfig) -> None:
        """
        Register a model configuration.

        Args:
            config: ModelConfig to register
        """
        self._model_configs[config.name] = config
        logger.debug(f"Registered model config: {config.name} ({config.model})")

    def get_model_config(self, name: str) -> ModelConfig:
        """
        Get a model configuration by name.

        Args:
            name: Config name (e.g., "briefing")

        Returns:
            ModelConfig object

        Raises:
            KeyError: If config not found
        """
        if name not in self._model_configs:
            raise KeyError(f"Model config not found: {name}")
        return self._model_configs[name]

    def list_model_configs(self) -> list[dict]:
        """List all registered model configurations."""
        return [c.to_dict() for c in self._model_configs.values()]

    # =========================================================================
    # CHANGE DETECTION
    # =========================================================================

    def get_prompt_changes(self, prompt_id: str, content: str) -> Optional[dict]:
        """
        Check if prompt content has changed from registered version.

        Args:
            prompt_id: Prompt identifier
            content: Current content to compare

        Returns:
            Dict with change info if changed, None if unchanged
        """
        if prompt_id not in self._prompts:
            return {"status": "new", "prompt_id": prompt_id}

        registered = self._prompts[prompt_id]
        new_hash = hashlib.sha256(content.encode()).hexdigest()[:12]

        if new_hash != registered.content_hash:
            return {
                "status": "changed",
                "prompt_id": prompt_id,
                "registered_version": registered.version,
                "registered_hash": registered.content_hash,
                "current_hash": new_hash,
            }

        return None

    def validate_prompts_unchanged(self) -> list[dict]:
        """
        Validate that prompts in code match registry.

        Returns list of any detected changes.
        """
        # This would be called in tests to detect untracked prompt changes
        changes = []

        # Import and check actual prompts used in code
        try:
            from agents.meeting_briefing.briefing_generator import SYSTEM_PROMPT
            change = self.get_prompt_changes("briefing_system", SYSTEM_PROMPT)
            if change:
                changes.append(change)
        except ImportError:
            pass

        return changes


# =============================================================================
# SINGLETON REGISTRY
# =============================================================================

_registry: Optional[PromptRegistry] = None


def get_registry() -> PromptRegistry:
    """Get or create the global prompt registry."""
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry


def get_prompt(prompt_id: str) -> Prompt:
    """Get a prompt from the global registry."""
    return get_registry().get_prompt(prompt_id)


def get_model_config(name: str) -> ModelConfig:
    """Get a model config from the global registry."""
    return get_registry().get_model_config(name)


# =============================================================================
# LLM CALL METADATA
# =============================================================================

@dataclass
class LLMCallMetadata:
    """
    Complete metadata for an LLM call, for reproducibility.

    This captures everything needed to reproduce a generation.
    """
    # Call identification
    call_id: str  # Unique ID for this call
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Prompt info
    prompt_id: Optional[str] = None
    prompt_version: Optional[str] = None
    prompt_hash: Optional[str] = None
    system_prompt_hash: Optional[str] = None
    user_prompt_hash: Optional[str] = None

    # Model info
    model: str = ""
    model_config_name: Optional[str] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None

    # Input/output
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0

    # Context
    company_id: Optional[str] = None
    operation: str = ""  # briefing, summarization, etc.

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def create(
        cls,
        operation: str,
        prompt: Optional[Prompt] = None,
        model_config: Optional[ModelConfig] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        **kwargs,
    ) -> "LLMCallMetadata":
        """
        Create metadata from prompt and config objects.

        Args:
            operation: Operation name (briefing, summarization)
            prompt: Optional Prompt object
            model_config: Optional ModelConfig object
            system_prompt: System prompt content (for hash)
            user_prompt: User prompt content (for hash)
            **kwargs: Additional fields
        """
        import uuid

        metadata = cls(
            call_id=str(uuid.uuid4()),
            operation=operation,
        )

        if prompt:
            metadata.prompt_id = prompt.id
            metadata.prompt_version = prompt.version
            metadata.prompt_hash = prompt.content_hash

        if model_config:
            metadata.model = model_config.model
            metadata.model_config_name = model_config.name
            metadata.temperature = model_config.temperature
            metadata.max_tokens = model_config.max_tokens

        if system_prompt:
            metadata.system_prompt_hash = hashlib.sha256(
                system_prompt.encode()
            ).hexdigest()[:12]

        if user_prompt:
            metadata.user_prompt_hash = hashlib.sha256(
                user_prompt.encode()
            ).hexdigest()[:12]

        # Apply additional kwargs
        for key, value in kwargs.items():
            if hasattr(metadata, key):
                setattr(metadata, key, value)

        return metadata
