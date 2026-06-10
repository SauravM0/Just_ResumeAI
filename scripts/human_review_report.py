"""Human Review Report Generator.

Generates a review package with:
- Expected PDF paths, one per test case
- ATS placeholder fields for release-candidate results
- Checklist template
- Automated pre-check placeholders for Category A

Usage:
    python scripts/human_review_report.py --generate --output review_packages/
    python scripts/human_review_report.py --evaluate --checklist review_packages/review_checklist_YYYYMMDD.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TEST_CASES = [
    {"id": "fresher_cs_backend", "description": "CS fresher -> Backend Engineer at startup"},
    {"id": "fresher_cs_data", "description": "CS fresher -> Data Scientist at tech company"},
    {"id": "fresher_mba_pm", "description": "MBA fresher -> Product Manager"},
    {"id": "mid_backend_senior", "description": "3yr backend dev -> Senior Engineer"},
    {"id": "mid_data_lead", "description": "3yr data scientist -> Lead Data Scientist"},
    {"id": "career_change_dev", "description": "Non-CS to developer, bootcamp background"},
    {"id": "experienced_manager", "description": "8yr engineer -> Engineering Manager"},
    {"id": "fresher_design", "description": "Design grad -> UX Designer"},
    {"id": "mid_devops", "description": "2yr dev -> DevOps Engineer"},
    {"id": "experienced_fullstack", "description": "5yr dev -> Full Stack Engineer"},
]

CATEGORY_A_KEYS = ["A1_keywords", "A2_skills", "A3_title", "A4_order", "A5_page_fit"]
CATEGORY_B_KEYS = [
    "B1_action_verbs",
    "B2_outcomes",
    "B3_natural_tone",
    "B4_realistic_claims",
    "B5_consistent_tone",
    "B6_memorable",
    "B7_would_shortlist",
]
CATEGORY_C_KEYS = ["C1_name", "C2_companies", "C3_college", "C4_gpa", "C5_certs", "C6_awards"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _case_template(case: dict[str, str], output_path: Path) -> dict[str, Any]:
    pdf_path = output_path / f"{case['id']}.pdf"
    return {
        "id": case["id"],
        "description": case["description"],
        "pdf_path": str(pdf_path),
        "pdf_generated": False,
        "ats_score": None,
        "automated_checks": {key: None for key in CATEGORY_A_KEYS},
        "human_review": {
            **{key: None for key in CATEGORY_B_KEYS},
            **{key: None for key in CATEGORY_C_KEYS},
        },
        "reviewer_notes": "",
        "review_date": None,
    }


def generate_review_package(output_dir: str) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    results = []
    for case in TEST_CASES:
        print(f"Generating checklist entry: {case['id']}")
        results.append(_case_template(case, output_path))

    checklist_path = output_path / f"review_checklist_{datetime.now().strftime('%Y%m%d')}.json"
    package = {
        "review_date": _now_iso(),
        "instructions": [
            "Attach release-candidate PDFs to the matching pdf_path values.",
            "Fill automated_checks with true/false/null after Category A pre-checks.",
            "Fill human_review with true/false/null after reviewer assessment.",
            "Category C false values block release.",
            "More than 30% Category B failures block release.",
        ],
        "release_criteria": {
            "category_a_min_pass_rate": 0.90,
            "category_b_min_pass_rate": 0.70,
            "category_c_min_pass_rate": 1.00,
        },
        "cases": results,
    }
    checklist_path.write_text(json.dumps(package, indent=2), encoding="utf-8")

    readme_path = output_path / "README_REVIEW_PACKAGE.md"
    readme_path.write_text(
        "# Human Review Package\n\n"
        "1. Generate or attach one PDF per case ID.\n"
        "2. Complete the JSON checklist fields with true, false, or null.\n"
        f"3. Evaluate with: python scripts/human_review_report.py --evaluate --checklist {checklist_path}\n",
        encoding="utf-8",
    )

    print(f"\nReview package generated at {output_path}")
    print(f"Checklist template: {checklist_path}")
    print("Instructions:")
    print("  1. Open each PDF in the package.")
    print("  2. Fill human_review fields with true, false, or null.")
    print(f"  3. Run: python scripts/human_review_report.py --evaluate --checklist {checklist_path}")
    return checklist_path


def _count_values(cases: list[dict[str, Any]], section: str, keys: list[str]) -> tuple[int, int, list[str]]:
    total_answered = 0
    total_failed = 0
    failed_labels: list[str] = []
    for case in cases:
        values = case.get(section, {})
        for key in keys:
            value = values.get(key)
            if value is None:
                continue
            total_answered += 1
            if value is False:
                total_failed += 1
                failed_labels.append(f"{case.get('id', 'unknown')}:{key}")
    return total_answered, total_failed, failed_labels


def evaluate_results(checklist_path: str) -> int:
    """Evaluate a completed review checklist and determine if release is blocked."""
    path = Path(checklist_path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    cases = data.get("cases", [])

    blocked = False

    c_answered, c_failed, c_failures = _count_values(cases, "human_review", CATEGORY_C_KEYS)
    if c_failed:
        blocked = True
        for failure in c_failures:
            print(f"BLOCK: accuracy failure {failure}")

    b_answered, b_failed, b_failures = _count_values(cases, "human_review", CATEGORY_B_KEYS)
    b_failure_rate = (b_failed / b_answered) if b_answered else 0.0
    if b_answered and b_failure_rate > 0.30:
        blocked = True
        print(f"BLOCK: Category B failure rate is {b_failure_rate:.0%} ({b_failed}/{b_answered})")
        for failure in b_failures[:20]:
            print(f"  recruiter quality failure: {failure}")

    a_answered, a_failed, _ = _count_values(cases, "automated_checks", CATEGORY_A_KEYS)
    a_pass_rate = ((a_answered - a_failed) / a_answered) if a_answered else None
    b_pass_rate = ((b_answered - b_failed) / b_answered) if b_answered else None
    c_pass_rate = ((c_answered - c_failed) / c_answered) if c_answered else None

    print("\nQA REVIEW SUMMARY")
    print("=" * 50)
    print(f"Checklist: {path}")
    print(f"Cases: {len(cases)}")
    print(f"Category A pass rate: {_format_rate(a_pass_rate)}")
    print(f"Category B pass rate: {_format_rate(b_pass_rate)}")
    print(f"Category C pass rate: {_format_rate(c_pass_rate)}")

    if blocked:
        print("\nRELEASE BLOCKED: Fix review failures before release.")
        return 1

    print("\nRELEASE APPROVED: No blocking human-review failures found.")
    return 0


def _format_rate(value: float | None) -> str:
    if value is None:
        return "not reviewed"
    return f"{value:.0%}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or evaluate human QA review packages.")
    parser.add_argument("--generate", action="store_true", help="Generate a checklist review package.")
    parser.add_argument("--evaluate", action="store_true", help="Evaluate a completed checklist.")
    parser.add_argument("--output", default="review_packages", help="Output directory for generated package.")
    parser.add_argument("--checklist", help="Path to completed review checklist JSON.")
    args = parser.parse_args()

    if args.generate == args.evaluate:
        parser.error("Choose exactly one of --generate or --evaluate.")

    if args.generate:
        generate_review_package(args.output)
        return 0

    if not args.checklist:
        parser.error("--evaluate requires --checklist.")
    return evaluate_results(args.checklist)


if __name__ == "__main__":
    raise SystemExit(main())
