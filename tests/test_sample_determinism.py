"""The sample report must be byte-reproducible.

Coehoorn's whole thesis is determinism and reproducibility; the canonical
sample report it ships has to honor that. With a fixed RNG seed, a fixed
run_id, and fixed timestamps, two independent runs of the heuristic
pipeline against the stub must serialize to identical bytes.
"""
from __future__ import annotations

import random
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from coehoorn.aggregator import (
    build_report,
    compare_to_expected,
    pin_report_timestamps,
)
from coehoorn.conversation import run_conversations
from coehoorn.judge import judge_all
from coehoorn.metrics import metrics_from_comparison
from coehoorn.personas import generate_personas_heuristic
from coehoorn.rubric_parser import parse_rubric_file

REPO_ROOT = Path(__file__).resolve().parent.parent
STUB_DIR = REPO_ROOT / "apps" / "stub-agent"
SEED = 20260517
FIXED_RUN_ID = "coehoorn-sample-0000-0000-000000000000"
FIXED_CREATED = datetime(2026, 5, 17, 10, 8, 0, tzinfo=UTC)
FIXED_COMPLETED = datetime(2026, 5, 17, 10, 8, 4, tzinfo=UTC)


def _stub_adapter():
    random.seed(SEED)
    if str(STUB_DIR) not in sys.path:
        sys.path.insert(0, str(STUB_DIR))
    from app import app  # type: ignore

    from coehoorn.agent_adapter import CallableAdapter

    client = app.test_client()

    def _call(conversation):
        return client.post(
            "/chat", json={"conversation": conversation}
        ).get_json()["reply"]

    return CallableAdapter(_call)


async def _build_sample_report_json() -> str:
    rubric, rules = parse_rubric_file(REPO_ROOT / "examples" / "rubric_coach.yaml")
    personas = generate_personas_heuristic(n=6)
    agent = _stub_adapter()
    transcripts = await run_conversations(
        personas, agent, max_turns=4, mode="heuristic", concurrency=4
    )
    verdicts = judge_all(transcripts, rubric, rules, mode="heuristic")
    report = build_report(
        rubric=rubric,
        transcripts=transcripts,
        verdicts=verdicts,
        agent_endpoint="in-process://stub (deterministic seed=20260517)",
    )
    pinned = pin_report_timestamps(
        report,
        created_at=FIXED_CREATED,
        completed_at=FIXED_COMPLETED,
        run_id=FIXED_RUN_ID,
    )
    return pinned.model_dump_json(indent=2)


@pytest.mark.asyncio
async def test_sample_report_is_byte_reproducible():
    first = await _build_sample_report_json()
    second = await _build_sample_report_json()
    assert first == second
    assert FIXED_RUN_ID in first


@pytest.mark.asyncio
async def test_sample_meta_eval_is_stable_and_sane():
    import yaml

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
        rubric=rubric,
        transcripts=transcripts,
        verdicts=verdicts,
        agent_endpoint="in-process://stub",
        created_at=FIXED_CREATED,
        completed_at=FIXED_COMPLETED,
        run_id=FIXED_RUN_ID,
    )
    diff = compare_to_expected(report, expected)
    m = metrics_from_comparison(diff)
    # On the seeded sample the judge matches the ground truth exactly: no
    # false positives, no false negatives -> precision and recall both 1.0.
    assert m.overall.fp == 0
    assert m.overall.fn == 0
    assert m.overall.precision.value == 1.0
    assert m.overall.recall.value == 1.0
