"""
Jobscan calibration script.

PURPOSE:
Generate resumes and record internal scores so they can be compared manually
against Jobscan.

USAGE:
  python scripts/jobscan_calibration.py --output calibration_results.json

AFTER RUNNING:
  1. Upload each generated PDF to https://www.jobscan.co
  2. Paste the JD used for each resume into Jobscan
  3. Record Jobscan's score for each result
  4. Run: python scripts/jobscan_calibration.py --compare --results calibration_results.json
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_BASELINE_CALIBRATION = 4.0

TEST_CASES = [
    {
        "id": "fresher_backend",
        "description": "Fresher CS student applying for Backend Engineer",
        "profile_fixture": "fresher_profile",
        "jd_fixture": "backend_jd",
        "expected_range": [75, 92],
    },
    {
        "id": "experienced_backend",
        "description": "Experienced developer applying for Backend Engineer",
        "profile_fixture": "experienced_profile",
        "jd_fixture": "backend_jd",
        "expected_range": [82, 95],
    },
    {
        "id": "fresher_data_scientist",
        "description": "Fresher CS student applying for Data Scientist",
        "profile_fixture": "fresher_profile",
        "jd_fixture": "ds_jd",
        "expected_range": [68, 88],
    },
    {
        "id": "experienced_data_scientist",
        "description": "Experienced backend developer applying for Data Scientist",
        "profile_fixture": "experienced_profile",
        "jd_fixture": "ds_jd",
        "expected_range": [55, 78],
    },
    {
        "id": "experienced_backend_two_page",
        "description": "Experienced developer applying for Backend Engineer with two-page target",
        "profile_fixture": "experienced_profile",
        "jd_fixture": "backend_jd",
        "target_pages": 2,
        "expected_range": [82, 95],
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_default_env() -> None:
    """
    Let this script import app modules in local calibration environments.

    Real production credentials are not needed for fixture-based generation; these
    values only satisfy startup config validation when the developer has not set
    local .env values.
    """
    defaults = {
        "SUPABASE_URL": "https://calibration.local",
        "SUPABASE_JWT_SECRET": "calibration-secret-at-least-32-characters",
        "SUPABASE_SERVICE_ROLE_KEY": "calibration-service-role-key",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _load_conftest_module():
    conftest_path = BACKEND_ROOT / "tests" / "conftest.py"
    spec = importlib.util.spec_from_file_location(
        "jobscan_calibration_conftest", conftest_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load fixtures from {conftest_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_fixture(name: str):
    module = _load_conftest_module()
    fixture = getattr(module, name)
    factory = getattr(fixture, "__wrapped__", fixture)
    return factory()


def _jd_text(parsed_jd) -> str:
    values = [
        parsed_jd.job_title,
        parsed_jd.company or "",
        *parsed_jd.required_skills,
        *parsed_jd.preferred_skills,
        *parsed_jd.responsibilities,
        *(keyword.keyword for keyword in parsed_jd.keywords),
    ]
    return "\n".join(value for value in values if value)


def _score_from_optimization(optimization) -> float:
    if optimization.final_pdf_text_score:
        return float(optimization.final_pdf_text_score.overall_score)
    if optimization.final_json_score:
        return float(optimization.final_json_score.overall_score)
    return 0.0


async def run_calibration(output_path: str) -> None:
    """Generate resumes for all test cases and record internal scores."""
    _ensure_default_env()
    from app.config import get_settings
    from app.services.resume_optimization_loop import optimize_resume_for_ats

    settings = get_settings()
    results: list[dict[str, Any]] = []

    for case in TEST_CASES:
        print(f"\nRunning test case: {case['id']}")
        profile = load_fixture(case["profile_fixture"])
        parsed_jd = load_fixture(case["jd_fixture"])

        try:
            optimization = await optimize_resume_for_ats(
                profile=profile,
                parsed_jd=parsed_jd,
                generation_id=f"calibration_{case['id']}",
                target_pages=int(case.get("target_pages", 1)),
                target_ats_score=90.0,
            )
            internal_score = _score_from_optimization(optimization)
            result = {
                "id": case["id"],
                "description": case["description"],
                "profile_fixture": case["profile_fixture"],
                "jd_fixture": case["jd_fixture"],
                "jd_text": _jd_text(parsed_jd),
                "internal_score": round(internal_score, 1),
                "expected_range": case["expected_range"],
                "pdf_path": optimization.final_pdf_path or "",
                "docx_fallback_path": optimization.final_docx_fallback_path or "",
                "score_source": optimization.final_score_source,
                "latex_extraction_calibration": settings.LATEX_EXTRACTION_CALIBRATION,
                "jobscan_score": None,
                "delta": None,
                "within_8_points": None,
                "calibration_timestamp": _utc_now(),
            }
            print(f"  OK internal score: {internal_score:.1f}")
            print(f"  PDF: {result['pdf_path'] or '(no PDF produced)'}")
            print("  Upload this PDF to Jobscan and record the score.")
        except Exception as exc:
            result = {
                "id": case["id"],
                "description": case["description"],
                "profile_fixture": case["profile_fixture"],
                "jd_fixture": case["jd_fixture"],
                "expected_range": case["expected_range"],
                "jobscan_score": None,
                "delta": None,
                "within_8_points": None,
                "error": str(exc),
                "calibration_timestamp": _utc_now(),
            }
            print(f"  FAILED: {exc}")
        results.append(result)

    output = {
        "calibration_date": _utc_now(),
        "score_tolerance_points": 8.0,
        "baseline_latex_extraction_calibration": DEFAULT_BASELINE_CALIBRATION,
        "results": results,
    }
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"\nResults saved to {out_path}")
    print("NEXT STEPS:")
    print("  1. Open each generated PDF listed above.")
    print("  2. Go to https://www.jobscan.co.")
    print("  3. Upload the PDF and paste the corresponding jd_text.")
    print("  4. Record the Jobscan score in the jobscan_score field.")
    print(
        f"  5. Run: python scripts/jobscan_calibration.py --compare --results {out_path}"
    )


def compare_results(results_path: str) -> bool:
    """Compare internal scores against manually entered Jobscan scores."""
    data = json.loads(Path(results_path).read_text(encoding="utf-8"))
    results = data.get("results", [])
    completed = [
        r
        for r in results
        if r.get("jobscan_score") is not None and r.get("internal_score") is not None
    ]

    if not completed:
        print(
            "No Jobscan scores entered yet. Add jobscan_score values to the results file."
        )
        return False

    print("\nCALIBRATION COMPARISON RESULTS")
    print("=" * 60)
    all_pass = True
    for result in completed:
        delta = abs(float(result["internal_score"]) - float(result["jobscan_score"]))
        within_8 = delta <= 8.0
        result["delta"] = round(delta, 1)
        result["within_8_points"] = within_8
        status = "PASS" if within_8 else "FAIL"
        print(f"{status} {result['id']}")
        print(
            f"   Internal: {result['internal_score']} | "
            f"Jobscan: {result['jobscan_score']} | Delta: {delta:.1f}"
        )
        if not within_8:
            all_pass = False
            print("   Delta exceeds 8 points. Review LATEX_EXTRACTION_CALIBRATION.")

    data["last_compared_at"] = _utc_now()
    Path(results_path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    if all_pass:
        print("\nCALIBRATION PASSED: All scores are within 8 points of Jobscan.")
        return True

    avg_internal = sum(float(r["internal_score"]) for r in completed) / len(completed)
    avg_jobscan = sum(float(r["jobscan_score"]) for r in completed) / len(completed)
    suggested_adjustment = avg_jobscan - avg_internal
    suggested_value = DEFAULT_BASELINE_CALIBRATION + suggested_adjustment
    print("\nCALIBRATION ADJUSTMENT NEEDED")
    print(f"   Average internal score: {avg_internal:.1f}")
    print(f"   Average Jobscan score: {avg_jobscan:.1f}")
    print(
        f"   Suggested LATEX_EXTRACTION_CALIBRATION change: {suggested_adjustment:+.1f}"
    )
    print(f"   Suggested value: {suggested_value:.1f}")
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="calibration_results.json")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--results", default="calibration_results.json")
    args = parser.parse_args()

    if args.compare:
        compare_results(args.results)
    else:
        asyncio.run(run_calibration(args.output))


if __name__ == "__main__":
    main()
