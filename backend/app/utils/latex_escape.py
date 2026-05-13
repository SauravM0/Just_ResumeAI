"""
LaTeX special character escaping and sanitization utilities.
"""

from __future__ import annotations

import re

from app.domain.rules import LATEX_SPECIAL_CHARS


def escape_latex(text: str) -> str:
    """
    Escape LaTeX special characters in user-provided text.
    Order matters: backslash must be escaped first to avoid double-escaping.
    Handles: & % $ # _ { } ~ ^ \\
    """
    if not text:
        return ""

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
