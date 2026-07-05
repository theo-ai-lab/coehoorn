"""The committed MCP sample reports must be byte-reproducible.

Coehoorn's whole thesis is determinism; the MCP tool-poisoning attack pack it
ships has to honor that too. With pinned run ids and timestamps, regenerating the
pack must serialize to exactly the bytes committed under runs/sample-mcp/, so
`uv run python scripts/build_mcp_sample.py` never dirties `git diff`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from coehoorn.aggregator import build_report, pin_report_timestamps
from coehoorn.judge import judge_all
from coehoorn.mcp_redteam import (
    SCENARIOS,
    build_scenario,
    mcp_tool_poisoning_rubric,
    run_scenario,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = REPO_ROOT / "runs" / "sample-mcp"
CREATED = datetime(2026, 5, 17, 10, 8, 0, tzinfo=timezone.utc)
COMPLETED = datetime(2026, 5, 17, 10, 8, 4, tzinfo=timezone.utc)


async def _report_json(index: int, key: str) -> str:
    rubric, rules = mcp_tool_poisoning_rubric()
    transcript = await run_scenario(build_scenario(key))
    verdicts = judge_all([transcript], rubric, rules, mode="heuristic")
    report = build_report(
        rubric=rubric,
        transcripts=[transcript],
        verdicts=verdicts,
        agent_endpoint=f"loopback-mcp://{key}",
    )
    report = pin_report_timestamps(
        report,
        created_at=CREATED,
        completed_at=COMPLETED,
        run_id=f"coehoorn-mcp-{index:04d}-0000-000000000000",
    )
    return report.model_dump_json(indent=2)


@pytest.mark.asyncio
async def test_each_archetype_report_is_byte_reproducible():
    for i, key in enumerate(SCENARIOS):
        first = await _report_json(i, key)
        second = await _report_json(i, key)
        assert first == second, key


@pytest.mark.asyncio
async def test_committed_sample_json_matches_a_fresh_build():
    # The freshly-built JSON must equal exactly the committed sample bytes, so the
    # sample builder can never drift from what is checked in.
    for i, key in enumerate(SCENARIOS):
        committed = (SAMPLE_DIR / key / "report.json").read_text()
        assert await _report_json(i, key) == committed, key


def test_hero_is_first_and_the_committed_samples_exist():
    keys = list(SCENARIOS)
    assert keys[0] == "rug-pull"  # the temporal attack leads
    for key in keys:
        assert (SAMPLE_DIR / key / "report.json").exists(), key
        assert (SAMPLE_DIR / key / "report.html").exists(), key
