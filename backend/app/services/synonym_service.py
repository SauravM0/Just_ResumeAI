"""Shared synonym and alias matching for ATS terms."""

from __future__ import annotations

from collections import OrderedDict


_SYNONYM_MAP: dict[str, list[str]] = {
    "react": ["React", "React.js", "ReactJS", "react-js"],
    "node": ["Node", "Node.js", "NodeJS", "node-js"],
    "vue": ["Vue", "Vue.js", "VueJS", "vue-js"],
    "next": ["Next", "Next.js", "NextJS", "next-js"],
    "nuxt": ["Nuxt", "Nuxt.js", "NuxtJS", "nuxt-js"],
    "express": ["Express", "Express.js", "ExpressJS", "express-js"],
    "javascript": ["JavaScript", "JS"],
    "typescript": ["TypeScript", "TS"],
    "postgresql": ["PostgreSQL", "Postgres"],
    "mongodb": ["MongoDB", "Mongo"],
    "oracle database": ["Oracle Database", "Oracle DB", "OracleDB"],
    "pl/sql": ["PL/SQL", "PLSQL"],
    "ci/cd": ["CI/CD", "CICD", "CI CD"],
    "ui/ux": ["UI/UX", "UI UX"],
    "obdx": ["OBDX", "Oracle Banking Digital Experience"],
    "cemli": ["CEMLI", "CEMLIs"],
    "git": ["Git", "GIT"],
    "open banking apis": ["Open Banking APIs", "Open Banking API", "Banking APIs"],
    "non-production environments": ["Non-production environments", "non-production", "non production"],
    "mobile app development": ["Mobile App development", "mobile app development"],
}

_ALIAS_TO_CANONICAL: dict[str, str] = {}
for canonical, aliases in _SYNONYM_MAP.items():
    _ALIAS_TO_CANONICAL[canonical] = canonical
    for alias in aliases:
        key = alias.strip().casefold()
        _ALIAS_TO_CANONICAL[key] = canonical
        _ALIAS_TO_CANONICAL[key.replace(".", "")] = canonical
        _ALIAS_TO_CANONICAL[key.replace("-", "")] = canonical
        _ALIAS_TO_CANONICAL[key.replace("/", "")] = canonical
        _ALIAS_TO_CANONICAL[key.replace("/", " ")] = canonical
        _ALIAS_TO_CANONICAL[key.removesuffix(".js")] = canonical


def get_canonical(term: str) -> str:
    """Return the lowercase canonical form of a technology or ATS term."""
    normalized = " ".join(str(term or "").strip().casefold().split())
    stripped_js = normalized.removesuffix(".js")
    compact = normalized.replace(".", "").replace("-", "").replace("/", "")
    slash_spaced = normalized.replace("/", " ")
    return (
        _ALIAS_TO_CANONICAL.get(normalized)
        or _ALIAS_TO_CANONICAL.get(stripped_js)
        or _ALIAS_TO_CANONICAL.get(compact)
        or _ALIAS_TO_CANONICAL.get(slash_spaced)
        or normalized
    )


def get_all_forms(term: str) -> list[str]:
    """Return canonical plus all known aliases for a term, preserving order."""
    canonical = get_canonical(term)
    forms = [canonical, *_SYNONYM_MAP.get(canonical, []), term]
    deduped: OrderedDict[str, str] = OrderedDict()
    for form in forms:
        cleaned = " ".join(str(form or "").strip().split())
        if cleaned:
            deduped.setdefault(cleaned.casefold(), cleaned)
    return list(deduped.values())


def terms_match(term_a: str, term_b: str) -> bool:
    """Return True when two terms refer to the same known technology or ATS term."""
    return get_canonical(term_a) == get_canonical(term_b)
