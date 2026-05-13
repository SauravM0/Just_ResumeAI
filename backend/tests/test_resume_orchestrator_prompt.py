from __future__ import annotations

from app.ai.orchestrators.resume_orchestrator import _render_composer_system_prompt


def test_composer_system_prompt_keeps_instructional_braces_literal() -> None:
    prompt = _render_composer_system_prompt(
        min_len=80,
        max_len=220,
        min_bullets=3,
        max_bullets=5,
        min_sum=70,
        max_sum=120,
        seniority="intern",
    )

    assert "Min 80 chars, max 220 chars." in prompt
    assert "Primary experience: 3-6 bullets" in prompt
    assert "Seniority: intern" in prompt
    assert "{company}" in prompt
    assert "{JD title}" in prompt
    assert "{degree}" in prompt

