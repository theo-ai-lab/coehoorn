"""Builds an LLM-mode sample run under runs/sample-llm/ (local only; not committed).

Mirrors `build_sample_report.py` but uses mode="llm" for both persona
generation (Anthropic Opus) and judging (Anthropic Sonnet). The target
agent is still the local Flask stub via CallableAdapter — so the run is
fully local: only Anthropic API calls leave the machine, no network
traffic to the stub.

Personas=3 and turns=3 keep cost low (~$0.50–$1 per run). Re-run with:

    uv run python scripts/build_sample_report_llm.py

Requires ANTHROPIC_API_KEY in env (loaded from .env if present).
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "stub-agent"))

from coehoorn.agent_adapter import CallableAdapter  # noqa: E402
from coehoorn.aggregator import (  # noqa: E402
    build_report,
    compare_to_expected,
    write_comparison_json,
    write_report_json,
)
from coehoorn.conversation import run_conversations  # noqa: E402
from coehoorn.judge import judge_all  # noqa: E402
from coehoorn.personas import generate_personas_llm  # noqa: E402
from coehoorn.report_html import write_report_html  # noqa: E402
from coehoorn.rubric_parser import parse_rubric_file  # noqa: E402
from coehoorn.schemas import CriterionStatus, VerdictOutcome  # noqa: E402

SEED = 20260517
PERSONAS = 3
TURNS = 3


def _stub_adapter() -> CallableAdapter:
    random.seed(SEED)
    from app import app

    client = app.test_client()

    def _call(conversation):
        return client.post(
            "/chat", json={"conversation": conversation}
        ).get_json()["reply"]

    return CallableAdapter(_call)


async def main() -> int:
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "error: ANTHROPIC_API_KEY not set. LLM-mode sample requires a key. "
            "Set it in .env (gitignored) or in the environment.",
            file=sys.stderr,
        )
        return 2

    rubric, _ = parse_rubric_file(REPO_ROOT / "examples" / "rubric_coach.yaml")
    expected = yaml.safe_load(
        (REPO_ROOT / "examples" / "expected_failures.yaml").read_text()
    )["personas"]

    print(f"mode: llm  personas={PERSONAS}  turns={TURNS}  seed={SEED}")
    print("generating personas via Anthropic ...")
    personas = generate_personas_llm(rubric, n=PERSONAS)
    print(f"got {len(personas)} personas: {[p.id for p in personas]}")

    agent = _stub_adapter()
    started = datetime.now(UTC)
    print("running conversations ...")
    transcripts = await run_conversations(
        personas, agent, max_turns=TURNS, mode="llm",
        rubric=rubric, concurrency=PERSONAS,
    )
    print(f"completed {len(transcripts)} transcripts")
    print("judging ...")
    # Heuristic-rules dict is ignored in LLM mode; pass empty to satisfy signature.
    verdicts = judge_all(transcripts, rubric, {}, mode="llm")
    completed = datetime.now(UTC)

    report = build_report(
        rubric=rubric, transcripts=transcripts, verdicts=verdicts,
        agent_endpoint=f"in-process://stub (LLM mode, seed={SEED})",
        created_at=started, completed_at=completed,
    )

    out_dir = REPO_ROOT / "runs" / "sample-llm"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_report_json(report, out_dir / "report.json")
    write_report_html(report, out_dir / "report.html")
    diff = compare_to_expected(report, expected)
    write_comparison_json(diff, out_dir / "comparison.json")

    fail_count = sum(1 for v in verdicts if v.outcome is VerdictOutcome.FAIL)
    catches = [
        f"  - {t.persona.id} ({t.persona.archetype.value}): "
        f"{[cv.criterion_id for cv in v.criterion_verdicts if cv.status is CriterionStatus.FAIL]}"
        for t in transcripts
        for v in verdicts
        if v.transcript_id == t.id and v.outcome is VerdictOutcome.FAIL
    ]
    print(
        f"\nresult: breaches={fail_count}/{len(verdicts)}, "
        f"held={report.pass_rate:.0%}"
    )
    print("caught failures:")
    print("\n".join(catches) or "  (none)")
    print(
        f"wrote: {out_dir}/report.json, report.html, comparison.json"
    )
    matched = sum(1 for d in diff.values() if d["match"])
    fn = sum(len(d["false_negatives"]) for d in diff.values())
    fp = sum(len(d["false_positives"]) for d in diff.values())
    print(
        f"comparison: {matched}/{len(diff)} personas matched expectations; "
        f"false_positives={fp}; false_negatives={fn}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
