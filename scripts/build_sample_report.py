"""Builds a seeded, deterministic sample run that the README links to.

Runs in-process against the stub agent with a fixed random seed so the
stochastic citation flaw catch is reproducible. Writes:

  runs/sample/report.json
  runs/sample/report.html
  runs/sample/comparison.json

Re-run with: `uv run python scripts/build_sample_report.py`.
"""
from __future__ import annotations

import asyncio
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "stub-agent"))

from coehoorn.agent_adapter import CallableAdapter  # noqa: E402
from coehoorn.aggregator import (  # noqa: E402
    build_report,
    compare_to_expected,
    pin_report_timestamps,
    write_comparison_json,
    write_report_json,
)
from coehoorn.conversation import run_conversations  # noqa: E402
from coehoorn.judge import judge_all  # noqa: E402
from coehoorn.metrics import metrics_from_comparison  # noqa: E402
from coehoorn.meta_eval import evaluate_gold, load_gold_cases  # noqa: E402
from coehoorn.personas import generate_personas_heuristic  # noqa: E402
from coehoorn.report_html import write_report_html  # noqa: E402
from coehoorn.rubric_parser import parse_rubric_file  # noqa: E402
from coehoorn.schemas import CriterionStatus, VerdictOutcome  # noqa: E402

SEED = 20260517
# Pinned provenance so the committed sample is byte-reproducible: the README
# quickstart command must regenerate it without dirtying `git diff`.
SAMPLE_RUN_ID = "coehoorn-sample-0000-0000-000000000000"
SAMPLE_CREATED = datetime(2026, 5, 17, 10, 8, 0, tzinfo=timezone.utc)
SAMPLE_COMPLETED = datetime(2026, 5, 17, 10, 8, 4, tzinfo=timezone.utc)


def _stub_adapter():
    random.seed(SEED)
    from app import app  # noqa: E402

    client = app.test_client()

    def _call(conversation):
        return client.post("/chat", json={"conversation": conversation}).get_json()["reply"]

    return CallableAdapter(_call)


async def main() -> int:
    rubric, rules = parse_rubric_file(REPO_ROOT / "examples" / "rubric_coach.yaml")
    expected = yaml.safe_load(
        (REPO_ROOT / "examples" / "expected_failures.yaml").read_text()
    )["personas"]

    personas = generate_personas_heuristic(n=6)
    agent = _stub_adapter()
    transcripts = await run_conversations(
        personas, agent, max_turns=4, mode="heuristic", concurrency=4
    )
    verdicts = judge_all(transcripts, rubric, rules, mode="heuristic")
    report = build_report(
        rubric=rubric, transcripts=transcripts, verdicts=verdicts,
        agent_endpoint="in-process://stub (deterministic seed=20260517)",
    )
    report = pin_report_timestamps(
        report,
        created_at=SAMPLE_CREATED,
        completed_at=SAMPLE_COMPLETED,
        run_id=SAMPLE_RUN_ID,
    )

    diff = compare_to_expected(report, expected)
    metrics = metrics_from_comparison(diff)
    # The report's calibration panel shows the HONEST gold score (the judge vs
    # an adversarial gold set, ~0.66 balanced accuracy), not the run's own
    # self-fulfilling 1.00 against its expected-failures fixture.
    gold_cases = load_gold_cases(REPO_ROOT / "tests" / "gold" / "judge_gold.jsonl")
    judge_eval = evaluate_gold(gold_cases, rubric, rules)

    out_dir = REPO_ROOT / "runs" / "sample"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_report_json(report, out_dir / "report.json")
    write_report_html(report, out_dir / "report.html", judge_eval=judge_eval)
    write_comparison_json(diff, out_dir / "comparison.json")

    fail_count = sum(1 for v in verdicts if v.outcome is VerdictOutcome.FAIL)
    catches = [
        f"  - {t.persona.id} ({t.persona.archetype.value}): "
        f"{[cv.criterion_id for cv in v.criterion_verdicts if cv.status is CriterionStatus.FAIL]}"
        for t in transcripts
        for v in verdicts
        if v.transcript_id == t.id and v.outcome is VerdictOutcome.FAIL
    ]
    print(f"seed={SEED}, breaches={fail_count}/{len(verdicts)}, held={report.pass_rate:.0%}")
    print("caught failures:")
    print("\n".join(catches) or "  (none)")
    print(f"wrote: {out_dir}/report.json, report.html, comparison.json")
    matches = sum(1 for d in diff.values() if d["match"])
    fn = sum(len(d["false_negatives"]) for d in diff.values())
    print(f"comparison: {matches}/{len(diff)} personas matched expectations; false_negatives={fn}")
    print(
        f"meta-eval (judge vs expected): precision={metrics.overall.precision.value} "
        f"recall={metrics.overall.recall.value} abstention_rate={metrics.abstention_rate}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
