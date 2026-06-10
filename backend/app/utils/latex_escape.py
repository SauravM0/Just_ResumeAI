"""
LaTeX special character escaping and sanitization utilities.
"""

from __future__ import annotations

import re
import unicodedata

from app.domain.rules import LATEX_SPECIAL_CHARS

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_RESUME_EXPORT_TEXT_REPLACEMENTS = str.maketrans({
    "\u00a0": " ",
    "\u00ad": "",
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\u2060": "",
    "\ufeff": "",
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
})


def normalize_unicode_for_resume_export(text: str | None) -> str:
    """Normalize user text before it becomes LaTeX, DOCX, or extracted PDF text."""
    if not text:
        return ""

    normalized = unicodedata.normalize("NFKC", str(text)).translate(_RESUME_EXPORT_TEXT_REPLACEMENTS)
    return _CONTROL_CHAR_RE.sub(" ", normalized)


def escape_latex(text: str) -> str:
    """
    Escape LaTeX special characters in user-provided text.
    Order matters: backslash must be escaped first to avoid double-escaping.
    Handles: & % $ # _ { } ~ ^ \\
    """
    if not text:
        return ""

    text = normalize_unicode_for_resume_export(text)
    text = text.replace("\\", r"\textbackslash{}")

    for char in LATEX_SPECIAL_CHARS:
        text = text.replace(char, f"\\{char}")

    text = text.replace("\\~", r"\textasciitilde{}")
    text = text.replace("\\^", r"\textasciicircum{}")

    return text


def sanitize_latex_url(url: str) -> str:
    """
    Sanitize a URL for use in LaTeX \\href commands.
    URLs need less aggressive escaping than body text.
    """
    if not url:
        return ""
    url = normalize_unicode_for_resume_export(url)
    url = url.replace("\\", "").replace("{", "%7B").replace("}", "%7D")
    # Escape the subset of LaTeX-sensitive characters that commonly appear in URLs.
    url = url.replace("%", "\\%")
    url = url.replace("#", "\\#")
    url = url.replace("&", "\\&")
    return url


def strip_latex_commands(text: str) -> str:
    """
    Remove LaTeX commands from text for plain-text analysis (e.g. word counting).
    """
    # Remove \command{...} patterns
    text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
    # Remove remaining backslash commands
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    return text.strip()
