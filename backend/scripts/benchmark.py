"""Full pipeline benchmark helper.

Run locally, not in CI:

    python scripts/benchmark.py --runs 3

By default this script benchmarks a no-network dry run that exercises the
timing table and stage accounting. Extend the marked sections with real
pipeline calls when running against a configured Gemini/Supabase environment.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time


async def benchmark_pipeline(runs: int = 3) -> None:
    """Run the pipeline benchmark N times and report timing."""
    times: list[float] = []
    stage_times: list[dict[str, float]] = []

    for run in range(runs):
        print(f"\nRun {run + 1}/{runs}")
        run_stages: dict[str, float] = {}
        total_start = time.perf_counter()

        stage_start = time.perf_counter()
        # await analyze_jd(SAMPLE_JD_TEXT)  # Uncomment with a real Gemini key.
        run_stages["jd_parse"] = (time.perf_counter() - stage_start) * 1000

        stage_start = time.perf_counter()
        # This is where the production path runs parallel preprocessing:
        # asyncio.gather(strategy/enrichment or relevance/evidence/timeline).
        await asyncio.sleep(0)
        run_stages["parallel_preprocess"] = (time.perf_counter() - stage_start) * 1000

        stage_start = time.perf_counter()
        # await generate_recommendation(...)  # Uncomment in a configured environment.
        await asyncio.sleep(0)
        run_stages["initial_composition"] = (time.perf_counter() - stage_start) * 1000

        stage_start = time.perf_counter()
        # Each repair pass should be measured separately in real runs.
        await asyncio.sleep(0)
        run_stages["repair_passes"] = (time.perf_counter() - stage_start) * 1000

        stage_start = time.perf_counter()
        # await compile_pdf_to_page_target(...)
        await asyncio.sleep(0)
        run_stages["pdf_compile"] = (time.perf_counter() - stage_start) * 1000

        total = (time.perf_counter() - total_start) * 1000
        times.append(total)
        stage_times.append(run_stages)
        print(f"  Total: {total:.0f}ms")
        for stage, ms in run_stages.items():
            print(f"  {stage:<22} {ms:>8.0f}ms")

    mean_ms = statistics.mean(times)
    print("\nBENCHMARK RESULTS")
    print("=" * 50)
    print(f"Runs:   {runs}")
    print(f"Mean:   {mean_ms:.0f}ms ({mean_ms / 1000:.1f}s)")
    print(f"Median: {statistics.median(times):.0f}ms")
    print(f"Min:    {min(times):.0f}ms")
    print(f"Max:    {max(times):.0f}ms")
    print("Target: 30,000ms (30s)")

    if mean_ms > 45_000:
        print("SLOW: Mean exceeds 45s budget")
    elif mean_ms > 30_000:
        print("BORDERLINE: Mean exceeds 30s target")
    else:
        print("FAST: Mean within 30s target")

    print("\nSTAGE MEANS")
    print("=" * 50)
    for stage in stage_times[0]:
        values = [run[stage] for run in stage_times]
        print(f"{stage:<22} {statistics.mean(values):>8.0f}ms")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(benchmark_pipeline(runs=args.runs))


if __name__ == "__main__":
    main()
