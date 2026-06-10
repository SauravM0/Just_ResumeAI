# ATS Score Comparison

Use this guide with `../benchmark/score_comparison.csv` to compare internal ATS scoring against external ATS/review tools.

## Purpose

The comparison should show whether the internal ATS score tracks external scoring directionally and where it overestimates or underestimates resume quality.

## CSV Columns

| Column | Description |
| --- | --- |
| `case_id` | Stable id shared across profile, JD, resume output, reference output, and external score artifacts. |
| `target_role` | Role title or role family used for the benchmark case. |
| `profile_file` | Path to the source candidate profile in `benchmark/profiles/`. |
| `jd_file` | Path to the job description in `benchmark/jds/`. |
| `current_output_file` | Path to the current generated resume in `benchmark/current_outputs/`. |
| `reference_output_file` | Path to the reference resume in `benchmark/reference_outputs/`. |
| `internal_ats_score` | Score produced by the application. |
| `internal_score_scale` | Maximum internal score, usually `100`. |
| `internal_scoring_mode` | Internal scorer used, such as `fast_deterministic` or full pipeline scoring. |
| `exact_jd_keywords_score` | Fast scorer sub-score for exact JD keyword coverage. |
| `required_skills_score` | Fast scorer sub-score for required skills match. |
| `title_seniority_alignment_score` | Fast scorer sub-score for role title and seniority alignment. |
| `standard_sections_score` | Fast scorer sub-score for standard ATS section presence. |
| `parseability_score` | Fast scorer sub-score for simple ATS parseability signals. |
| `external_tool` | Name of the third-party ATS or resume review tool. |
| `external_ats_score` | Score produced by the external tool. |
| `external_score_scale` | Maximum external score, usually `100`. |
| `score_gap` | Internal score minus normalized external score. |
| `keyword_match_score` | Manual 1-5 review score for keyword match. |
| `role_alignment_score` | Manual 1-5 review score for role alignment. |
| `bullet_quality_score` | Manual 1-5 review score for bullet quality. |
| `skills_coverage_score` | Manual 1-5 review score for skills coverage. |
| `ats_parseability_score` | Manual 1-5 review score for ATS parseability. |
| `recruiter_readability_score` | Manual 1-5 review score for recruiter readability. |
| `reviewer` | Person who performed the manual quality review. |
| `review_date` | Review date in `YYYY-MM-DD` format. |
| `notes` | Short context, exceptions, or follow-up actions. |

## Normalizing Scores

Normalize external scores to the internal scale before comparing.

```text
normalized_external_score = external_ats_score / external_score_scale * internal_score_scale
score_gap = internal_ats_score - normalized_external_score
```

Interpretation:

| Gap | Meaning |
| ---: | --- |
| `-5` to `5` | Internal and external scores are broadly aligned. |
| Greater than `5` | Internal score may be overestimating quality. |
| Less than `-5` | Internal score may be underestimating quality. |

## Review Criteria

Use these manual criteria alongside score comparison. External ATS tools are useful signals, but they should not replace human quality review.

### Keyword Match

Measures whether the resume includes important JD keywords in natural, evidence-backed places.

Strong examples:

- Required technologies appear in skills and relevant experience bullets.
- JD terminology is reflected without copying entire phrases mechanically.
- Important keywords are supported by candidate evidence.

Weak examples:

- Missing must-have keywords from the JD.
- Keywords appear only in a skills list with no experience support.
- Repeated keyword stuffing that hurts readability.

### Role Alignment

Measures whether the resume positions the candidate for the target role.

Strong examples:

- Summary, skills, and most relevant bullets reinforce the target role.
- Seniority, scope, domain, and responsibilities match the JD.
- Less relevant experience is compressed or moved lower.

Weak examples:

- Generic resume could apply to many unrelated roles.
- Key responsibilities from the JD are not addressed.
- The strongest matching experience is buried.

### Bullet Quality

Measures whether bullets show concrete impact.

Strong examples:

- Bullets describe action, scope, and result.
- Metrics or scale are included when available.
- Claims are specific and credible.

Weak examples:

- Bullets are vague task lists.
- Outcomes are missing.
- Phrasing is repetitive or inflated.

### Skills Coverage

Measures whether required and preferred skills are covered accurately.

Strong examples:

- Must-have skills are present and supported.
- Preferred skills are included when profile evidence exists.
- Skills are grouped clearly for scanning and parsing.

Weak examples:

- Important skills are omitted.
- Unsupported skills are invented.
- Skill names are inconsistent across sections.

### ATS Parseability

Measures whether the resume can be parsed cleanly by ATS systems.

Strong examples:

- Standard section headings.
- Consistent dates and role formatting.
- Selectable text in PDF output.
- Simple layout without parsing-hostile elements.

Weak examples:

- Tables, images, icons, or columns interfere with text extraction.
- Contact information is not parseable.
- Dates, employers, or titles are inconsistent.

### Recruiter Readability

Measures whether a recruiter can quickly understand candidate fit.

Strong examples:

- The top third clearly communicates target fit.
- Most relevant accomplishments are easy to skim.
- Sections are ordered logically.

Weak examples:

- Important details require slow reading to find.
- Bullets are too dense, generic, or repetitive.
- Formatting makes comparison difficult.

## Reporting Pattern

For each benchmark batch, summarize:

- Average internal score.
- Average normalized external score.
- Average score gap.
- Cases where internal score overestimated quality by more than 5 points.
- Cases where internal score underestimated quality by more than 5 points.
- Manual criteria with the lowest average scores.
- Top fixes to improve alignment and output quality.
