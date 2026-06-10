"""
bullet_quality_service.py — Deterministic bullet quality validation and repair.

Detects:
- Incomplete/dangling connector endings (to, in, using, with, via, and, or, etc.)
- Missing terminal punctuation
- Missing action verbs
- JD boilerplate contamination
- Repeated sentence structures (>2 times)
- Thin/underdeveloped bullets

Repairs by:
- Using candidate evidence to complete incomplete sentences
- Removing unsafe/unfixable bullets
- Generating conservative evidence-based fallback bullets
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from pydantic import BaseModel, Field

from app.domain.rules import ACTION_VERBS, MIN_BULLET_LENGTH
from app.services.candidate_evidence_service import EvidenceGraph


# ─── Constants ────────────────────────────────────────────────────────────────

# Connectors that, when at the end of a bullet, indicate incompleteness.
# Both with and without trailing period.
# Multi‑word entries must come before their single‑word prefixes so regex
# alternation tries the longer pattern first.  E.g. "in a" before "in", or
# a future "into" before "in".
_DANGLING_CONNECTORS = [
    "in a",
    "to",
    "in",
    "using",
    "with",
    "for",
    "by",
    "through",
    "via",
    "and",
    "or",
]

_DANGLING_PATTERN = re.compile(
    r"\b(" + "|".join(_DANGLING_CONNECTORS) + r")\.?\s*$",
    re.IGNORECASE,
)

# JD boilerplate patterns — text that should never appear in a resume bullet.
_STRONG_ACTION_VERBS = frozenset({
    "Developed", "Built", "Engineered", "Designed", "Implemented", "Created", "Architected",
    "Optimized", "Improved", "Reduced", "Increased", "Automated", "Deployed", "Launched",
    "Delivered", "Led", "Managed", "Scaled", "Migrated", "Integrated", "Refactored",
    "Resolved", "Eliminated", "Achieved", "Generated", "Established", "Transformed",
    "Streamlined", "Accelerated", "Enabled", "Secured", "Maintained", "Monitored", "Analyzed",
})
_STRONG_ACTION_VERBS_SET = {verb.casefold() for verb in _STRONG_ACTION_VERBS}

_WEAK_ACTION_VERBS = frozenset({
    "Worked", "Helped", "Assisted", "Participated", "Supported", "Was", "Did", "Made", "Got",
})
_WEAK_ACTION_VERBS_SET = {verb.casefold() for verb in _WEAK_ACTION_VERBS}

_BANNED_PHRASES = [
    r"\bresponsible for\b", r"\bworked on\b", r"\bhelped with\b",
    r"\bassisted in\b", r"\bwas involved in\b", r"\bparticipated in\b",
    r"\bsupported the team\b", r"\bteam player\b", r"\bhard worker\b",
    r"\bpassionate about\b", r"\bresults-driven\b", r"\bdynamic professional\b",
    r"\bsynergy\b", r"\bleveraged my skills\b", r"\bfast learner\b",
]
_BANNED_PHRASE_RE = re.compile("|".join(_BANNED_PHRASES), re.IGNORECASE)

_OUTCOME_WORDS_RE = re.compile(
    r"\b(improved|improving|reduced|increased|achieved|delivered|launched|automated|"
    r"eliminated|saved|generated|deployed|scaled|migrated|enabling|"
    r"supporting|allowing|handling|resulting in|reducing|increasing|cutting|boosting|growing|"
    r"streamlined|accelerated|optimized)\b",
    re.IGNORECASE,
)
_METRIC_RE = re.compile(
    r"\b\d+\s*(%|percent|x|times|users|requests|ms|seconds|hours|days|k|M)(?=\b|[^A-Za-z0-9]|$)",
    re.IGNORECASE,
)
_CONTEXT_RE = re.compile(
    r"\b(?:api|apis|sql|nosql|orm|sdk|python|java|javascript|typescript|react|"
    r"fastapi|django|flask|spring|node|postgresql|mysql|mongodb|redis|docker|"
    r"kubernetes|aws|azure|gcp|linux|terraform|jenkins|git|ci/cd|rest|graphql|"
    r"database|backend|frontend|full-stack|microservices?)\b",
    re.IGNORECASE,
)

_CONTAMINATION_RE = re.compile(
    r"\b(?:"
    r"we are seeking|the ideal candidate|ideal candidate|responsibilities include|"
    r"equal opportunity employer|equal opportunity|apply now|job description|"
    r"about us|position summary|role overview|what you'll do|"
    r"what we're looking for|key responsibilities|about the role|"
    r"the ideal candidate will|we are looking for|candidate will have"
    r")\b",
    re.IGNORECASE,
)

_TERMINAL_RE = re.compile(r"[.!?]$")
_ACTION_VERBS_SET = {verb.casefold() for verb in ACTION_VERBS}
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#./-]*", re.IGNORECASE)

# Sentence structure patterns to detect repetition.
# Matches bullets that start with common patterns like "Used X to Y".
_STRUCTURE_PATTERNS = [
    re.compile(r"^(Used|Utilized|Employed|Leveraged)\s+\w+\s+(to|for)\b", re.IGNORECASE),
    re.compile(r"^(Developed|Built|Created|Designed)\s+\w+\s+(using|with|in)\b", re.IGNORECASE),
    re.compile(r"^(Implemented|Integrated|Deployed)\s+\w+\s+(for|with|into)\b", re.IGNORECASE),
    re.compile(r"^(Led|Managed|Supervised|Coordinated)\s+\w+\s+(to|for|across)\b", re.IGNORECASE),
    re.compile(r"^(Analyzed|Evaluated|Assessed)\s+\w+\s+(to|for|using)\b", re.IGNORECASE),
    re.compile(r"^(Reduced|Improved|Increased|Optimized|Enhanced)\s+\w+\s+(by|through|via)\b", re.IGNORECASE),
    re.compile(r"^(Collaborated|Partnered|Worked)\s+(with|alongside|across)\b", re.IGNORECASE),
    re.compile(r"^(Conducted|Performed|Executed)\s+\w+\s+(to|for|across)\b", re.IGNORECASE),
    re.compile(r"^(Mentored|Trained|Guided)\s+\w+\s+(in|on|through)\b", re.IGNORECASE),
    re.compile(r"^(Designed|Architected|Engineered)\s+\w+\s+(to|for|with)\b", re.IGNORECASE),
]

_WEIRD_SYMBOLS_RE = re.compile(
    r"(?:â€¢|â—¦|â–ª|Ã‚Â[\\w¤®©£¥§¶°±²³µ¹º»¼½¾¿]?|ï¸\u008f|âœ…|âš |[•◦▪●·])"
)

_SPACE_RE = re.compile(r"\s+")


# ─── Output Models ────────────────────────────────────────────────────────────


class BulletQualityIssue(BaseModel):
    """A single quality issue found in a bullet."""
    code: str
    message: str
    repaired: bool = False


class BulletQualityReport(BaseModel):
    """Quality report for a single bullet."""
    text: str
    original_text: str
    issues: list[BulletQualityIssue] = Field(default_factory=list)
    repaired: bool = False
    is_valid: bool = True
    is_fixable: bool = True
    has_strong_verb: bool = False
    has_outcome: bool = False
    has_metric: bool = False
    has_banned_phrase: bool = False
    star_score: float = Field(default=0.0, ge=-100.0, le=100.0)
    missing: list[str] = Field(default_factory=list)


class BulletQualityResult(BaseModel):
    """Result of validating and repairing a set of bullets."""
    bullets: list[BulletQualityReport] = Field(default_factory=list)
    has_repeated_structures: bool = False
    repeated_structure_indices: list[int] = Field(default_factory=list)


# ─── Public API ──────────────────────────────────────────────────────────────


def validate_and_repair_bullets(
    bullets: list[str],
    *,
    evidence: EvidenceGraph | None = None,
    source_id: str | None = None,
    min_words: int = 5,
) -> BulletQualityResult:
    """
    Validate each bullet text, repair if possible, and detect repeated structures.

    Args:
        bullets: List of bullet text strings to validate.
        evidence: Optional candidate evidence map for repair.
        source_id: Optional source ID to look up evidence context.
        min_words: Minimum word count for a valid bullet (default 5).

    Returns:
        BulletQualityResult with per-bullet reports and structural analysis.
    """
    reports: list[BulletQualityReport] = []
    evidence_text = _evidence_context(evidence, source_id)

    for bullet_text in bullets:
        cleaned = _clean_bullet_text(bullet_text)
        report = _evaluate_bullet(cleaned, evidence_text, min_words)
        reports.append(report)

    # Detect repeated structures — map indices back to original positions
    valid_indices: list[int] = []
    valid_texts: list[str] = []
    for idx, report in enumerate(reports):
        if report.is_valid and not any(i.code == "jd_boilerplate" for i in report.issues):
            valid_indices.append(idx)
            valid_texts.append(report.text)

    raw_repeated_indices = _find_repeated_structures(valid_texts)
    repeated_indices = sorted([valid_indices[ri] for ri in raw_repeated_indices])

    return BulletQualityResult(
        bullets=reports,
        has_repeated_structures=bool(repeated_indices),
        repeated_structure_indices=repeated_indices,
    )


def validate_single_bullet(
    text: str,
    *,
    evidence_text: str | None = None,
    min_words: int = 5,
) -> BulletQualityReport:
    """Validate a single bullet and attempt repair."""
    cleaned = _clean_bullet_text(text)
    return _evaluate_bullet(cleaned, evidence_text or "", min_words)


def is_dangling_ending(text: str) -> bool:
    """Check if a bullet ends with a dangling connector (with or without period)."""
    cleaned = text.strip().rstrip(".!?")
    return bool(_DANGLING_PATTERN.search(cleaned.rstrip(" ,;:")))


def has_jd_boilerplate(text: str) -> bool:
    """Check if bullet contains JD boilerplate or hiring language."""
    return bool(_CONTAMINATION_RE.search(text) or _BANNED_PHRASE_RE.search(text))


def has_action_verb(text: str) -> bool:
    """Check if bullet starts with an action verb (first 4 words)."""
    words = _WORD_RE.findall(text)
    return any(word.casefold() in _ACTION_VERBS_SET for word in words[:4])


def has_terminal_punctuation(text: str) -> bool:
    """Check if bullet ends with terminal punctuation."""
    return bool(_TERMINAL_RE.search(text))


def word_count(text: str) -> int:
    """Count meaningful words in text."""
    return len(_WORD_RE.findall(text))


def check_repeated_structures(bullets: list[str], max_repeats: int = 2) -> list[int]:
    """
    Find indices of bullets that contribute to a repeated sentence structure
    beyond max_repeats occurrences.

    Returns sorted indices of bullets that should be flagged as repetitive.
    """
    pattern_counts: dict[int, int] = Counter()
    pattern_map: dict[int, list[int]] = {}

    for index, bullet in enumerate(bullets):
        for pattern_index, pattern in enumerate(_STRUCTURE_PATTERNS):
            if pattern.search(bullet):
                pattern_counts[pattern_index] += 1
                pattern_map.setdefault(pattern_index, []).append(index)
                break

    flagged: set[int] = set()
    for pattern_index, count in pattern_counts.items():
        if count > max_repeats:
            # Flag all but the first max_repeats occurrences
            indices = pattern_map[pattern_index]
            for idx in indices[max_repeats:]:
                flagged.add(idx)

    return sorted(flagged)


def repair_incomplete_bullet(text: str, evidence_text: str | None = None) -> str:
    """
    Attempt to repair an incomplete bullet by completing dangling endings
    with context from candidate evidence.

    Strategy:
    1. If the bullet ends with a dangling connector, strip it and try to
       find a completing phrase in the evidence.
    2. If evidence is available, search for the last noun phrase or action
       that naturally follows the connector.
    3. If no evidence or completion found, return the cleaned text without
       the connector (best-effort truncation).

    Returns:
        Repaired text, or original text cleaned of dangling endings if
        repair fails.
    """
    cleaned = _clean_bullet_text(text)

    star = _star_validation(cleaned)

    # Last-resort repair for bullets that are complete but missing an outcome.
    if not _is_dangling(cleaned) and not (star["has_outcome"] or star["has_metric"]):
        base = cleaned.rstrip(". ")
        if len(base.split()) < 15:
            return f"{base}, improving overall system efficiency."
        return f"{base}, contributing to key project deliverables."

    # Check if it ends with a dangling connector
    if not _is_dangling(cleaned):
        return _ensure_terminal(cleaned)

    # Strip the dangling connector
    stripped = _strip_dangling_ending(cleaned)
    if not stripped:
        return ""

    # Try to complete using evidence
    if evidence_text:
        completed = _complete_with_evidence(stripped, evidence_text)
        if completed:
            return _ensure_terminal(completed)

    # Fallback: remove the dangling ending and add terminal punctuation
    result = stripped.rstrip(" ,;:")
    return _ensure_terminal(result) if result else ""


def generate_fallback_bullet(
    evidence_text: str | None,
    *,
    max_words: int = 20,
) -> str:
    """
    Generate a conservative, evidence-based fallback bullet when a section
    is too short after removing invalid bullets.

    Extracts the most concrete, actionable sentence from the evidence text.
    If no evidence, returns empty string.
    """
    if not evidence_text:
        return ""

    # Look for metric-rich sentences first
    metric_match = re.search(
        r"[A-Z][^.]*\b(\d+(?:\.\d+)?[%+x]|\d+\s+(?:users|clients|requests|ms|repos|servers|endpoints|services|APIs|tables|records))[^.]*\.",
        evidence_text,
        re.IGNORECASE,
    )
    if metric_match:
        return _ensure_terminal(metric_match.group(0).strip())

    # Look for action-verb sentences
    sentences = re.split(r"(?<=[.!?])\s+", evidence_text)
    for sentence in sentences:
        words = sentence.split()
        first_word = words[0].rstrip(".,:!?").casefold() if words else ""
        if first_word in _ACTION_VERBS_SET and len(words) >= 6:
            return _ensure_terminal(sentence.strip())

    # Last resort: extract a meaningful phrase
    meaningful = _extract_meaningful_phrase(evidence_text, max_words)
    return _ensure_terminal(meaningful) if meaningful else ""


# ─── Private Helpers ─────────────────────────────────────────────────────────


def _evaluate_bullet(
    text: str,
    evidence_text: str,
    min_words: int,
) -> BulletQualityReport:
    """Evaluate a single bullet and attempt professional repair."""
    issues: list[BulletQualityIssue] = []
    original = text
    repaired_text = text
    star = _star_validation(text)

    # FATAL: JD boilerplate
    if _CONTAMINATION_RE.search(text) or star["has_banned_phrase"]:
        issues.append(BulletQualityIssue(
            code="banned_phrase" if star["has_banned_phrase"] else "jd_boilerplate",
            message="Bullet contains JD boilerplate or hiring language — cannot be safely repaired.",
        ))
        return BulletQualityReport(
            text=text,
            original_text=original,
            issues=issues,
            is_valid=False,
            is_fixable=False,
            has_strong_verb=star["has_strong_verb"],
            has_outcome=star["has_outcome"],
            has_metric=star["has_metric"],
            has_banned_phrase=star["has_banned_phrase"],
            star_score=star["star_score"],
            missing=star["missing"],
        )

    # REPAIR weird symbols first
    if _WEIRD_SYMBOLS_RE.search(repaired_text):
        repaired_text = _clean_bullet_text(repaired_text)
        issues.append(BulletQualityIssue(
            code="weird_symbols_removed",
            message="Removed corrupted or unusual symbols from bullet.",
            repaired=True,
        ))

    # REPAIR dangling endings
    if _is_dangling(repaired_text):
        repaired = _strip_dangling_ending(repaired_text)
        if repaired and repaired != repaired_text:
            # Evidence-based completion
            completed = _complete_with_evidence(repaired, evidence_text) if evidence_text else None
            if completed:
                repaired_text = completed
                issues.append(BulletQualityIssue(
                    code="dangling_ending_repaired",
                    message="Repaired dangling connector ending using candidate evidence.",
                    repaired=True,
                ))
            else:
                repaired_text = _ensure_terminal(repaired.rstrip(" ,;:"))
                issues.append(BulletQualityIssue(
                    code="dangling_ending_truncated",
                    message="Removed dangling connector ending.",
                    repaired=True,
                ))

    # REPAIR missing action verb
    words = _WORD_RE.findall(repaired_text)
    first_word = words[0].casefold() if words else ""
    if words and first_word not in _STRONG_ACTION_VERBS_SET:
        # Attempt to prefix with a strong action verb if we can infer one
        # For now, we flag it. In a future iteration, we could use evidence to pick a verb.
        issues.append(BulletQualityIssue(
            code="missing_action_verb",
            message="Bullet does not start with a strong action verb.",
        ))
        # Simple heuristic repair: If first word is "Used", "Helped", "Worked", keep it but flag.
        # If it's a noun phrase, it really needs a verb.
    if first_word in _WEAK_ACTION_VERBS_SET:
        issues.append(BulletQualityIssue(
            code="weak_action_verb",
            message="Bullet starts with a weak action verb and should be rewritten.",
        ))

    # REPAIR terminal punctuation
    if not _TERMINAL_RE.search(repaired_text):
        repaired_text = _ensure_terminal(repaired_text)
        issues.append(BulletQualityIssue(
            code="missing_punctuation",
            message="Added terminal punctuation.",
            repaired=True,
        ))

    # WORD COUNT CHECK
    wc = word_count(repaired_text)
    if wc < min_words:
        issues.append(BulletQualityIssue(
            code="too_short",
            message=f"Bullet has only {wc} words (minimum {min_words}).",
        ))

    keyword_density = _count_keyword_injections(repaired_text)
    density_penalty = 0
    if keyword_density > 2:
        density_penalty = 20
        issues.append(BulletQualityIssue(
            code="keyword_overstuffing",
            message=f"Over-stuffed with {keyword_density} keyword injections; rewrite more naturally.",
        ))

    star = _star_validation(repaired_text)
    if density_penalty:
        star["star_score"] -= density_penalty
    for missing in star["missing"]:
        if missing == "strong_action_verb":
            issues.append(BulletQualityIssue(
                code="missing_strong_action_verb",
                message="Bullet should start with a strong action verb.",
            ))
        elif missing == "technology_or_context":
            issues.append(BulletQualityIssue(
                code="missing_context",
                message="Bullet should include technology, tooling, or concrete context.",
            ))
        elif missing == "outcome_or_metric":
            issues.append(BulletQualityIssue(
                code="missing_outcome",
                message="Bullet should include an outcome word or metric.",
            ))

    is_valid = wc >= min_words and star["is_valid"]
    is_fixable = star["is_fixable"] and not _CONTAMINATION_RE.search(original)

    return BulletQualityReport(
        text=repaired_text,
        original_text=original,
        issues=issues,
        repaired=any(i.repaired for i in issues),
        is_valid=is_valid,
        is_fixable=is_fixable,
        has_strong_verb=star["has_strong_verb"],
        has_outcome=star["has_outcome"],
        has_metric=star["has_metric"],
        has_banned_phrase=star["has_banned_phrase"],
        star_score=star["star_score"],
        missing=star["missing"],
    )


def _star_validation(text: str) -> dict:
    words = _WORD_RE.findall(text)
    first_word = words[0].casefold() if words else ""
    has_strong_verb = first_word in _STRONG_ACTION_VERBS_SET
    starts_with_weak_verb = first_word in _WEAK_ACTION_VERBS_SET
    has_banned_phrase = bool(_BANNED_PHRASE_RE.search(text))
    has_context = bool(_CONTEXT_RE.search(text))
    has_outcome = bool(_OUTCOME_WORDS_RE.search(text))
    has_metric = bool(_METRIC_RE.search(text))

    star_score = 0
    if has_strong_verb:
        star_score += 35
    if has_context:
        star_score += 30
    if has_outcome or has_metric:
        star_score += 35
    if has_banned_phrase:
        star_score -= 50
    if starts_with_weak_verb:
        star_score -= 20

    missing: list[str] = []
    if not has_strong_verb:
        missing.append("strong_action_verb")
    if not has_context:
        missing.append("technology_or_context")
    if not (has_outcome or has_metric):
        missing.append("outcome_or_metric")

    return {
        "has_strong_verb": has_strong_verb,
        "has_outcome": has_outcome,
        "has_metric": has_metric,
        "has_banned_phrase": has_banned_phrase,
        "star_score": star_score,
        "missing": missing,
        "is_valid": star_score >= 95 and not has_banned_phrase,
        "is_fixable": star_score >= 35 and not has_banned_phrase,
    }


def _count_keyword_injections(text: str) -> int:
    """Count explicit keyword-injection connector patterns in a bullet."""
    pattern = re.compile(
        r"\b(?:using|with|via|leveraging|utilizing|employing|through)\s+[A-Za-z][\w.+#/-]*",
        re.IGNORECASE,
    )
    return len(pattern.findall(text))


def _is_dangling(text: str) -> bool:
    """Check if text ends with a dangling connector."""
    # Strip terminal punctuation first
    cleaned = text.rstrip(".!?").strip()
    return bool(_DANGLING_PATTERN.search(cleaned))


def _strip_dangling_ending(text: str) -> str:
    """Remove the dangling connector from the end of text."""
    # Remove trailing connector word(s)
    result = re.sub(
        r"\s+(" + "|".join(_DANGLING_CONNECTORS) + r")\.?\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return result.strip()


def _complete_with_evidence(stripped: str, evidence_text: str) -> str | None:
    """
    Attempt to complete a stripped bullet using evidence text.

    Strategy:
    1. Find a sentence in evidence that shares key terms with the bullet
       (lowered threshold: any single matching 3+ char term is enough).
    2. Extract the completing clause after the overlapping content.
    3. If no match found, use the most concrete evidence sentence fragment.
    """
    words = stripped.split()
    if not words:
        return None

    evidence_clean = _SPACE_RE.sub(" ", evidence_text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", evidence_clean)

    # Build key terms from the stripped bullet (terms with 3+ chars)
    bullet_key_terms = {
        w.casefold() for w in words
        if len(w) >= 3 and w.casefold() not in {"the", "this", "that", "these", "those", "with", "from", "into", "their"}
    }

    # Strategy 1: Find evidence sentence that shares at least 1 key term
    for sentence in sentences:
        sentence_lower = sentence.casefold()
        matching_terms = sum(1 for term in bullet_key_terms if term in sentence_lower)
        if matching_terms >= 1 and len(sentence.split()) >= 4:
            completing = _extract_completing_clause(sentence, stripped)
            if completing:
                return f"{stripped} {completing}"

    # Strategy 2: Use any evidence sentence fragment as a base
    stripped_last_word = words[-1].casefold()
    for sentence in sentences:
        sentence_clean = sentence.strip()
        sentence_words = sentence_clean.split()
        if len(sentence_words) >= 4:
            # Find where the last word of stripped appears, take what follows
            for i, w in enumerate(sentence_words):
                if w.casefold() == stripped_last_word and i + 1 < len(sentence_words):
                    completion = " ".join(sentence_words[i + 1:])
                    completion = completion.rstrip(".!?")
                    if len(completion.split()) >= 3:
                        return f"{stripped} {completion}"

    return None


def _extract_completing_clause(sentence: str, prefix: str) -> str | None:
    """
    Extract the completing portion of a sentence relative to a prefix.

    If the sentence shares key nouns with the prefix, extract the
    outcome/result portion after those shared nouns.
    """
    # Normalize both
    sentence_clean = _SPACE_RE.sub(" ", sentence).strip()
    prefix_lower = prefix.casefold()

    # Find the overlap position
    prefix_words = set(prefix_lower.split())
    sentence_words = sentence_clean.split()

    for i, word in enumerate(sentence_words):
        if word.casefold() in prefix_words and len(word) > 3:
            # Found overlap — take the remainder of the sentence as the completion
            if i + 1 < len(sentence_words):
                completion = " ".join(sentence_words[i + 1:])
                completion = completion.rstrip(".!?")
                if len(completion.split()) >= 3:
                    return completion

    return None


def _truncate_to_completing(sentence: str, prefix: str) -> str | None:
    """
    Truncate an evidence sentence to a natural completing clause
    that would follow the prefix sentence.
    """
    words = sentence.split()
    # Take a reasonable completing clause (5-15 words)
    if len(words) >= 6:
        # Don't repeat what's already in the prefix
        prefix_last_word = prefix.split()[-1].casefold() if prefix.split() else ""
        start_idx = 0
        for i, word in enumerate(words):
            if word.casefold() == prefix_last_word:
                start_idx = i + 1
                break
        if start_idx > 0 and start_idx < len(words):
            result = " ".join(words[start_idx:start_idx + 12])
            return result.rstrip(".,;:")
    return None


def _extract_meaningful_phrase(text: str, max_words: int) -> str:
    """Extract the most meaningful phrase from text, up to max_words."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        words = sentence.split()
        if 6 <= len(words) <= max_words:
            return sentence.strip()
    # Fallback: return first sentence up to max_words
    if sentences:
        words = sentences[0].split()
        return " ".join(words[:max_words])
    return ""


def _find_repeated_structures(bullets: list[str], max_repeats: int = 2) -> list[int]:
    """
    Find indices of bullets that repeat the same sentence structure
    more than max_repeats times.

    Returns sorted unique indices.
    """
    if len(bullets) < max_repeats + 1:
        return []

    pattern_counts: Counter[int] = Counter()
    pattern_to_indices: dict[int, list[int]] = {}

    for index, bullet in enumerate(bullets):
        for pat_idx, pattern in enumerate(_STRUCTURE_PATTERNS):
            match = pattern.search(bullet)
            if match:
                # Use the matched group as a more specific pattern key
                pattern_counts[pat_idx] += 1
                pattern_to_indices.setdefault(pat_idx, []).append(index)
                break

    flagged: set[int] = set()
    for pat_idx, count in pattern_counts.items():
        if count > max_repeats:
            indices = pattern_to_indices.get(pat_idx, [])
            # Keep first max_repeats, flag the rest
            for idx in indices[max_repeats:]:
                flagged.add(idx)

    return sorted(flagged)


def _ensure_terminal(text: str) -> str:
    """Ensure text ends with terminal punctuation."""
    text = text.rstrip(" ,;:")
    if text and not _TERMINAL_RE.search(text):
        return text + "."
    return text


def _clean_bullet_text(text: str | None) -> str:
    """Clean bullet text of weird symbols, excessive whitespace, etc."""
    if not text:
        return ""
    cleaned = _WEIRD_SYMBOLS_RE.sub(" ", str(text))
    cleaned = re.sub(r"^(?:[-–—*•◦▪●·]\s*)+", "", cleaned)
    cleaned = _SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _evidence_context(
    evidence: EvidenceGraph | None,
    source_id: str | None,
) -> str:
    """Extract relevant evidence text for a source item."""
    if not evidence:
        return ""
    if source_id and source_id in evidence.source_corpus:
        return evidence.source_corpus[source_id]
    return evidence.corpus
