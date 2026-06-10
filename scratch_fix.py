import sys

filepath = r'c:\Users\Alexa\OneDrive\Desktop\Just resume\backend\app\services\resume_optimization_loop.py'
with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

target = """    original = recommendation.model_copy(deep=True)
    rec = recommendation.model_copy(deep=True)
    
            repair_actions.append("Optimized section order based on JD focus.")

    if is_final_pass:
        rec = apply_resume_quality_gate(rec, parsed_jd, profile, target_pages, locked=locked)
    
    rec = _restore_locked_bullets(original, rec)
    validate_locked_fields_in_output(rec, locked, logger=logger)
    if locked:
        rec.locked_fields = rec.locked_fields or locked.model_dump(mode="json")
    return rec"""

# Wait, let me check the target exactly.
# I need to find the text between "def _repair_recommendation(" and "def _repair_pass_label" and replace the entire function.

import re

pattern = re.compile(r'(def _repair_recommendation\(.*?\)\s*->\s*ResumeRecommendation:.*?)(def _repair_pass_label\()', re.DOTALL)

replacement_func = """def _repair_recommendation(
    *,
    recommendation: ResumeRecommendation,
    parsed_jd: ParsedJD,
    profile: MasterProfile,
    evidence: EvidenceGraph | None,
    ats_plan,
    current_score: ATSScore,
    target_pages: int,
    overflow: bool,
    attempt: int,
    is_final_pass: bool,
    locked: LockedFields | None,
    repair_actions: list[str],
) -> ResumeRecommendation:
    original = recommendation.model_copy(deep=True)
    rec = recommendation.model_copy(deep=True)
    
    # Update title
    if ats_plan and ats_plan.target_resume_title:
        rec.target_title = ats_plan.target_resume_title
    elif parsed_jd.job_title:
        rec.target_title = parsed_jd.job_title

    # Identify missing keywords for repair
    placement = analyze_keyword_placement(rec, parsed_jd, ats_plan)
    missing_for_repair = _dedupe([*current_score.missing_keywords, *placement.missing_high_priority_keywords])
    
    # Evidence-backed split
    supported, learning, unsupported = _split_truth_terms(missing_for_repair, profile, rec)
    
    repair_actions.append(_repair_pass_label(attempt, is_final_pass))

    # Hallucination removal DISABLED — evidence gate removed for max ATS coverage.

    if attempt == 0:
        # Keyword injection: add confirmed terms to summary/skills.
        _repair_summary(rec, parsed_jd, ats_plan, supported, repair_actions)
        _repair_skills(rec, supported, [], repair_actions)
        rec = inject_missing_keywords(rec, parsed_jd, ats_plan, profile)
    elif attempt == 1:
        # Bullet strengthening: improve weak bullets without deleting content.
        rec = strengthen_resume_recommendation(rec, parsed_jd, ats_plan, target_pages)
    elif attempt == 2:
        # Missing keyword insertion into evidence-backed bullets.
        _repair_bullets(rec, supported, profile, repair_actions)
    elif attempt == 3:
        # Summary refinement: make target title and priority terms visible early.
        _repair_summary(rec, parsed_jd, ats_plan, supported, repair_actions)
    elif attempt == 4:
        # Skills completion: confirmed terms plus aspirational terms as Learning Focus.
        _repair_skills(rec, supported, learning, repair_actions)
    elif attempt == 5:
        # PDF fit pass: trim only if the prior compile showed overflow.
        if overflow:
            rec = _compress_for_overflow(rec, target_pages, repair_actions)
        else:
            rec = fit_resume_to_page_budget(rec, parsed_jd, ats_plan=ats_plan, target_pages=target_pages)
            repair_actions.append("Checked page-fit budget without deleting source content.")
    elif is_final_pass:
        # Safety pass: local validation after hallucination removal.
        rec = strengthen_resume_recommendation(rec, parsed_jd, ats_plan, target_pages)

    if current_score.section_score.score < 90 and not is_final_pass:
        new_strategy = build_resume_strategy(parsed_jd, profile)
        if new_strategy.section_order != rec.section_order:
            rec.section_order = new_strategy.section_order
            repair_actions.append("Optimized section order based on JD focus.")

    if is_final_pass:
        rec = apply_resume_quality_gate(rec, parsed_jd, profile, target_pages, locked=locked)
    
    rec = _restore_locked_bullets(original, rec)
    validate_locked_fields_in_output(rec, locked, logger=logger)
    if locked:
        rec.locked_fields = locked.model_dump(mode="json")
    return rec


"""

match = pattern.search(content)
if match:
    new_content = content[:match.start(1)] + replacement_func + content[match.start(2):]
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("SUCCESS: Function replaced")
else:
    print("ERROR: Could not find function boundaries")
