"""
Prompt Templates for Outreach Agent
=====================================

Two-call pipeline for cold outreach generation:

  1. ``build_draft_prompt`` — voice-matched draft. The model focuses on
     personalization, investor voice, structural pattern, and grounded
     content rules (length matching, no salesy phrasing, no prior-employment
     references, etc.). Surface-level AI tells are NOT enforced here.

  2. ``build_cleanup_prompt`` — register/de-LLM pass. A smaller model
     rewrites the draft to remove AI tells (em dashes, banned intensifiers,
     "feels"/"exactly"/"really" patterns) without changing personalization
     claims, structure, or facts.

The legacy ``build_generation_prompt`` is kept as a thin alias for
``build_draft_prompt`` so older callers continue to work.

Usage:
    from agents.outreach.prompts import build_draft_prompt, build_cleanup_prompt

    draft_msgs = build_draft_prompt(
        investor_profile=profile,
        founder_context=founder_text,
        style_examples=samples,
        context_type_pattern=pattern_text,
    )
    draft = llm.invoke(draft_msgs).content

    cleanup_msgs = build_cleanup_prompt(
        draft_text=draft,
        investor_profile=profile,
        output_format="email",
    )
    final = small_llm.invoke(cleanup_msgs).content
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from langchain_core.messages import SystemMessage, HumanMessage

if TYPE_CHECKING:
    from .context import InvestorProfile, EmailSample


# =========================================================================
# CALL 1 — DRAFT: SYSTEM PROMPT (role + content rules)
# =========================================================================
#
# Surface-level AI tells (em dashes, banned words, intensifier sentences)
# are intentionally NOT enforced here — they belong to the cleanup pass.
# This keeps the draft prompt focused on content quality: getting the right
# signals, the right structure, and the investor's voice.

DRAFT_SYSTEM_PROMPT = """\
You are a ghostwriter drafting a cold outreach email from a specific NEA \
investor to a startup founder.

Your job is to produce an email that sounds exactly like the investor wrote it \
themselves. You have access to the investor's profile (voice, intro patterns, \
structural habits, sign-off style) and a set of real emails they have sent in \
the past. Internalize those patterns and do not deviate from them.

Focus on three things and three things only:
  1. PERSONALIZATION — pick the right signals about this founder and company.
  2. STRUCTURE — match the investor's natural opening, body, ask, and sign-off.
  3. LENGTH — match the investor's natural length for this context type.

A separate copy-editor pass will scrub surface-level style issues (banned \
words, em dashes, intensifier phrasing). Do not try to second-guess that pass; \
focus on getting the substance right.

Output the message text ONLY. No preamble, no commentary, no "Here's a draft" \
wrapper. Start with "Subject:" for email format or the greeting for LinkedIn."""

# Kept for backwards compatibility with any external imports.
SYSTEM_PROMPT = DRAFT_SYSTEM_PROMPT


# =========================================================================
# CALL 1 — DRAFT: PERSONALIZATION
# =========================================================================

PERSONALIZATION_INSTRUCTIONS = """\
PERSONALIZATION PRIORITY (use in this order — never use more than 3 per email, \
go deep not wide):

1. A specific technical detail about the product — architecture, a named \
feature, a design decision. This is the strongest signal of genuine interest.
2. A reference to the founder's published paper, blog post, or research. Shows \
you did your homework beyond the company page.
3. Shared background — same employer, same university, same research area. \
Must be real and verifiable.
4. A recent milestone — funding round, product launch, key hire, partnership. \
Timely and concrete.
5. Market thesis alignment — the investor has an active thesis that this \
company fits into. Explain the connection, don't just assert it.
6. Portfolio relevance — a specific portfolio company that is complementary \
(not competitive). Only mention if the connection is meaningful.
7. Geographic proximity — only if it enables an in-person meeting and the \
investor is known to offer those.

RULES:
- Pick at most 3 signals and develop them with specificity.
- Going deep on 1-2 signals beats shallow references to 5.

HARD GROUNDING RULE — NO EXCEPTIONS:
Every personalization claim must be traceable word-for-word to the provided \
investor profile and company data. This is a strict, verifiable requirement.

Banned patterns:
- Do not reference technical terms, methodologies, or jargon not present in \
  the investor's bio or thesis.
- Do not cite portfolio companies not listed in the investor's profile data.
- Do not reference the founder's or investor's prior employers, schools, or \
  career history unless explicitly stated in the provided data.
- Do not invent or infer details. If a connection exists only in your training \
  data, omit it — it will be flagged as a hallucination."""


# =========================================================================
# CALL 1 — DRAFT: CONTENT ANTI-PATTERNS
# =========================================================================
#
# These are *content-level* anti-patterns: structural, register, and grounding
# issues that the draft model needs to internalize. Surface AI-tells (em dashes,
# banned intensifiers, "feels"/"exactly"/"really") have been moved to the
# cleanup pass below.

CONTENT_ANTI_PATTERNS = """\
THINGS TO AVOID:

- Generic openings: "I hope this email finds you well", "I came across your \
company and was impressed." Start with something only this founder would \
recognize.
- Disconnected portfolio drops: Don't list portfolio companies unless they \
connect to the founder's work. "We backed Databricks" means nothing without a \
reason.
- Vague compliments: "Your product is interesting" or "I love what you're \
building." Be specific or say nothing.
- Asking for a meeting without showing homework: The ask comes AFTER you've \
demonstrated genuine understanding.
- Length mismatches: If the investor writes short, punchy emails (e.g., \
Madison), do not produce a 200-word essay. If the investor writes long, \
detailed emails (e.g., Ashley on thesis topics), do not produce a 3-sentence \
stub. Match the investor's natural length for this context type.
- Salesy language: "Exciting opportunity", "I'd love to explore synergies." \
Write like a peer, not a salesperson.
- Over-formality: "I hope this message finds you in good spirits." Match the \
investor's actual register — some use "Hey!", some use "Hi", some skip \
greetings entirely.
- Exclamation inflation: If the investor uses one exclamation mark per email, \
do not use five.
- Copying example sentences: Style examples show PATTERNS, not sentences to \
reuse. Never lift phrases verbatim from the examples.
- Referencing prior employment: Do not mention the founder's previous \
employers, past roles, or career history (e.g., "as a former Google \
engineer..."). This reads as surveillance. Focus only on their current \
product, public writing, and announced milestones."""

# Legacy alias for any external code expecting the old name.
ANTI_PATTERN_INSTRUCTIONS = CONTENT_ANTI_PATTERNS


# =========================================================================
# CALL 1 — DRAFT: SAMPLE USAGE
# =========================================================================

SAMPLE_SELECTION_INSTRUCTIONS = """\
HOW TO USE THE STYLE EXAMPLES:

These are real emails sent by this investor. They are here to teach you the \
investor's voice — not to be copied.

- Absorb the PATTERNS: greeting style, sentence structure, paragraph rhythm, \
how they transition from hook to ask, how they introduce themselves, how they \
sign off.
- Weight examples whose context_type matches the current scenario more heavily. \
If you're writing a thesis-driven deep-dive, the thesis-driven examples matter \
most.
- Never copy sentences from the examples. The founder may have seen similar \
emails — recycled phrasing feels automated.
- If examples conflict with each other (e.g., different intro patterns), prefer \
the pattern from the example whose context_type is closest to the current task."""


# =========================================================================
# CALL 2 — CLEANUP: SYSTEM PROMPT (de-LLM rewrite)
# =========================================================================

CLEANUP_SYSTEM_PROMPT = """\
You are a copy-editor rewriting a draft outreach message so it does not read \
as AI-written. The draft was already written in the investor's voice with the \
right personalization and structure. Your only job is to scrub surface-level \
AI tells.

Output the rewritten message text ONLY. No preamble, no commentary, no \
explanation of changes. Preserve the original Subject: line verbatim if \
present, then a blank line, then the rewritten body.

HARD CONSTRAINTS — DO NOT VIOLATE:
- Do NOT invent new facts, names, links, or claims. If the draft references a \
  product, paper, person, or company, keep that reference exactly as-is.
- Do NOT change the personalization. If the draft cites a specific feature, a \
  funding round, a paper, a shared employer — keep the citation and what it \
  says about the founder.
- Do NOT restructure paragraphs or change the message's argument. Sentence-level \
  rewrites only.
- Do NOT lengthen the message. You may shorten if a sentence collapses neatly, \
  but the draft's overall length is correct — preserve it.
- If a banned phrase is load-bearing and you cannot cleanly rewrite around it \
  without inventing content, leave the original sentence."""

CLEANUP_RULES = """\
WHAT TO FIX:

1. Em dashes (—). Replace mid-sentence em dashes with a comma, period, or \
parenthesis. Rewrite the sentence if needed. EXCEPTION: if the investor's \
greeting style uses a dash (e.g., "James—"), preserve that single instance \
in the greeting and nowhere else.

2. Banned words and phrases. Rewrite the sentence to remove these. Do not \
substitute one banned word for another.
   - "exactly" as a validator: "is exactly what / where / the kind of"
   - "feels" applied to a company, market, or timing: "feels right", \
"feels timely", "feels like the right moment"
   - "really" as an intensifier: "really interesting", "really compelling"
   - "caught my eye" / "catches my attention" / "caught my attention"
   - "uniquely positioned", "poised to", "screams", "exploding", \
"game-changing", "transformative", "revolutionary"
   - "I'd love to learn more" — replace with a specific question grounded in \
the draft itself
   - "What you're building is [adjective]" as a standalone sentence
   - "I've been following your work" as a lead-in

3. Intensifier-led sentences. If a sentence opens with an intensifier before \
the observation ("This is genuinely impressive", "That's incredibly clever"), \
flip it to lead with the observation itself.

4. Exclamation inflation. If the body has more than one exclamation mark per \
short message, demote the extras to periods. Keep at most one.

5. AI-flavored connective tissue. Phrases like "moreover", "furthermore", \
"that said", "with that in mind" when they don't add meaning — cut them and \
let the next sentence stand on its own.

CHECK BEFORE OUTPUTTING:
- No em dashes in the body (greeting exception aside).
- No banned words.
- No intensifier-led sentences.
- Length within ±10% of the draft.
- Personalization claims unchanged."""


# =========================================================================
# CALL 1 — DRAFT PROMPT ASSEMBLER
# =========================================================================

def build_draft_prompt(
    investor_profile: "InvestorProfile",
    founder_context: str,
    company_context: str,
    style_examples: list["EmailSample"],
    context_type_pattern: str,
    output_format: str = "email",
    outreach_goal: Optional[str] = None,
    event_details: Optional[str] = None,
    prior_relationship_details: Optional[str] = None,
) -> list[SystemMessage | HumanMessage]:
    """
    Assemble the messages list for the DRAFT call (call 1 of 2).

    The cleanup pass (call 2) is built separately by ``build_cleanup_prompt``
    and applied to the draft's output.

    Args:
        investor_profile: The investor's profile dataclass.
        founder_context: Formatted string with founder name, title, background.
        company_context: Formatted string with company data, signals, news.
        style_examples: Selected EmailSample objects for few-shot learning.
        context_type_pattern: The email_pattern string from the matched
            ContextTypeConfig describing the structural guidance.
        output_format: "email" or "linkedin".

    Returns:
        List of [SystemMessage, HumanMessage] ready for LLM.invoke().
    """
    system_parts = [
        DRAFT_SYSTEM_PROMPT,
        "",
        PERSONALIZATION_INSTRUCTIONS,
        "",
        CONTENT_ANTI_PATTERNS,
        "",
        SAMPLE_SELECTION_INSTRUCTIONS,
    ]
    system_content = "\n\n".join(system_parts)

    user_parts: list[str] = []

    user_parts.append("## INVESTOR PROFILE")
    user_parts.append(investor_profile.format_for_prompt())

    instructions: list[str] = []
    if outreach_goal:
        instructions.append(f"Goal: {outreach_goal}")
    if prior_relationship_details:
        instructions.append(f"Prior relationship: {prior_relationship_details}")
    if event_details:
        instructions.append(f"Event context: {event_details}")
    if instructions:
        user_parts.append("## INVESTOR INSTRUCTIONS")
        user_parts.append(
            "The investor has provided the following context. "
            "Let it shape the hook, tone, and opening of the email — "
            "it takes priority over generic personalization signals."
        )
        user_parts.append("\n".join(instructions))

    user_parts.append("## CONTEXT TYPE PATTERN")
    user_parts.append(
        f"Follow this structural pattern for the email:\n{context_type_pattern}"
    )

    user_parts.append("## TARGET CONTACT")
    user_parts.append(founder_context)

    user_parts.append("## COMPANY DATA")
    user_parts.append(company_context)

    if style_examples:
        user_parts.append("## STYLE EXAMPLES")
        for i, sample in enumerate(style_examples, 1):
            meta_line = (
                f"[context_type={sample.context_type}, "
                f"length={sample.length}]"
            )
            user_parts.append(f"### Example {i} {meta_line}")
            user_parts.append(sample.body)

    format_label = "EMAIL" if output_format == "email" else "LINKEDIN"
    user_parts.append("## OUTPUT REQUIREMENTS")
    user_parts.append(f"- Format: {format_label}")
    if output_format == "email":
        user_parts.append(
            "- Start with a Subject: line, then a blank line, then the body."
        )
    else:
        user_parts.append(
            "- No subject line. Open with a personalized hook."
        )
    user_parts.append(
        f"- Sign off as {investor_profile.full_name}"
        + (f" from {investor_profile.firm_name}."
           if hasattr(investor_profile, "firm_name") and investor_profile.firm_name
           else ".")
    )
    user_parts.append(
        "- Match the investor's voice exactly. Refer to the profile and "
        "examples above."
    )

    user_content = "\n\n".join(user_parts)

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]


# Legacy alias so any older call sites keep working.
build_generation_prompt = build_draft_prompt


# =========================================================================
# CALL 2 — CLEANUP PROMPT ASSEMBLER
# =========================================================================

def build_cleanup_prompt(
    draft_text: str,
    investor_profile: "InvestorProfile",
    output_format: str = "email",
) -> list[SystemMessage | HumanMessage]:
    """
    Assemble the messages list for the CLEANUP call (call 2 of 2).

    The cleanup pass rewrites surface-level AI tells out of the draft without
    changing personalization, structure, facts, or overall length.

    Args:
        draft_text: The raw draft message from call 1 (includes Subject: line
            for emails).
        investor_profile: The investor's profile dataclass (used only to note
            greeting-dash exceptions).
        output_format: "email" or "linkedin".

    Returns:
        List of [SystemMessage, HumanMessage] ready for LLM.invoke().
    """
    system_content = "\n\n".join([CLEANUP_SYSTEM_PROMPT, CLEANUP_RULES])

    user_parts: list[str] = []
    user_parts.append("## INVESTOR")
    user_parts.append(
        f"Name: {investor_profile.full_name}"
        + (f"\nFirm: {investor_profile.firm_name}"
           if hasattr(investor_profile, "firm_name") and investor_profile.firm_name
           else "")
    )

    format_label = "EMAIL" if output_format == "email" else "LINKEDIN"
    user_parts.append("## FORMAT")
    user_parts.append(format_label)

    user_parts.append("## DRAFT TO CLEAN UP")
    user_parts.append(draft_text)

    user_parts.append("## OUTPUT")
    if output_format == "email":
        user_parts.append(
            "Return the cleaned message only. Preserve the Subject: line "
            "verbatim if present, then a blank line, then the rewritten body. "
            "No preamble."
        )
    else:
        user_parts.append(
            "Return the cleaned message only. No preamble, no commentary."
        )

    user_content = "\n\n".join(user_parts)

    return [
        SystemMessage(content=system_content),
        HumanMessage(content=user_content),
    ]
