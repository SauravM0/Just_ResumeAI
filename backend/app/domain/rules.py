"""
Deterministic domain rules that the AI must respect.
These are hard constraints enforced AFTER AI generation, not prompt-only.
"""

# ─── Page Budget ─────────────────────────────────────────────────────────────

MAX_RESUME_PAGES = 1
MAX_BULLETS_PER_EXPERIENCE = 5
MIN_BULLETS_PER_EXPERIENCE = 2
MAX_EXPERIENCES = 4
MAX_PROJECTS = 3
MAX_SKILLS_CATEGORIES = 6
MAX_CERTIFICATIONS = 4
MAX_SUMMARY_WORDS = 60

# ─── Bullet Rules ───────────────────────────────────────────────────────────

MIN_BULLET_LENGTH = 30   # characters
MAX_BULLET_LENGTH = 200  # characters

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
MIN_KEYWORD_COVERAGE_PERCENT = 60.0

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
]

# ─── Scoring Weights ────────────────────────────────────────────────────────

SCORE_WEIGHT_KEYWORD = 0.50
SCORE_WEIGHT_READABILITY = 0.30
SCORE_WEIGHT_FORMAT = 0.20
