"""
Deterministic domain rules that the AI must respect.
These are hard constraints enforced AFTER AI generation, not prompt-only.
"""

# ─── Page Budget ─────────────────────────────────────────────────────────────

MAX_RESUME_PAGES = 1
MAX_BULLETS_PER_EXPERIENCE = 6  # Raised from 5: allows primary roles enough depth for ATS keyword coverage.
MIN_BULLETS_PER_EXPERIENCE = 3  # Raised from 2: forces Achievement Formula compliance instead of thin entries.
MAX_EXPERIENCES = 4
MAX_PROJECTS = 3
MAX_SKILLS_CATEGORIES = 6
MAX_CERTIFICATIONS = 4
MAX_SUMMARY_WORDS = 120  # Raised from 60: gives the summary room for 8-12 priority JD keywords naturally.

# ─── Bullet Rules ───────────────────────────────────────────────────────────

MIN_BULLET_LENGTH = 80   # Raised from 30: rejects vague one-clause bullets and soft-skill filler.
MAX_BULLET_LENGTH = 220  # Raised from 200: preserves quantified achievement bullets without awkward truncation.

# Action verbs that strong bullets should start with
ACTION_VERBS = [
    "achieved", "administered", "analyzed", "architected", "automated",
    "built", "collaborated", "conducted", "configured", "consolidated",
    "created", "debugged", "decreased", "delivered", "deployed",
    "designed", "developed", "directed", "drove", "eliminated",
    "enabled", "engineered", "enhanced", "established", "evaluated",
    "executed", "expanded", "facilitated", "guided", "identified",
    "implemented", "improved", "increased", "initiated", "integrated",
    "introduced", "launched", "led", "managed", "mentored",
    "migrated", "modernized", "monitored", "negotiated", "optimized",
    "orchestrated", "overhauled", "partnered", "pioneered", "planned",
    "presented", "proposed", "published", "rationalized", "re-architected",
    "rebuilt", "reduced", "refactored", "redesigned", "resolved",
    "revamped", "scaled", "secured", "simplified", "spearheaded",
    "standardized", "streamlined", "strengthened", "supervised", "transformed",
    "troubleshot", "unified", "upgraded", "utilized",
]

# ─── Keyword Rules ──────────────────────────────────────────────────────────

# Minimum keyword coverage percentage to consider resume "ATS-ready"
MIN_KEYWORD_COVERAGE_PERCENT = 80.0  # Raised from 60: matches the new ATS-ready quality bar.

# Keywords with these categories are considered critical
CRITICAL_KEYWORD_CATEGORIES = ["technical_skill", "required_tool", "certification"]

# ─── LaTeX Rules ─────────────────────────────────────────────────────────────

# Characters that must be escaped in LaTeX content
LATEX_SPECIAL_CHARS = ['&', '%', '$', '#', '_', '{', '}', '~', '^']

# Template field names (must match the fixed LaTeX template)
TEMPLATE_FIELDS = [
    "FULL_NAME",
    "EMAIL",
    "PHONE",
    "LOCATION",
    "LINKEDIN",
    "GITHUB",
    "PORTFOLIO",
    "SUMMARY",
    "EXPERIENCE_ENTRIES",
    "EDUCATION_ENTRIES",
    "SKILLS_ENTRIES",
    "PROJECTS_ENTRIES",
    "CERTIFICATIONS_ENTRIES",
    "ACHIEVEMENTS_ENTRIES",
]

# ─── Scoring Weights ────────────────────────────────────────────────────────

SCORE_WEIGHT_KEYWORD = 0.50
SCORE_WEIGHT_READABILITY = 0.30
SCORE_WEIGHT_FORMAT = 0.20
