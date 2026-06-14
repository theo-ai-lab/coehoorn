"""End-to-end heuristic-mode run against an in-process stub agent.

Uses the real stub agent's Flask test_client directly — no HTTP — so the
test exercises rubric parsing, persona generation, conversation running,
judging, report building, comparison, and HTML rendering as one pipeline.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# Make the stub agent importable. The stub lives outside the coehoorn
# package; the cleanest way to test against it without restructuring is to
# add its directory to sys.path for this test session.
_STUB_DIR = Path(__file__).resolve().parent.parent / "apps" / "stub-agent"
sys.path.insert(0, str(_STUB_DIR))

from coehoorn.agent_adapter import CallableAdapter  # noqa: E402
from coehoorn.aggregator import (  # noqa: E402
    build_report,
    compare_to_expected,
)
from coehoorn.conversation import run_conversations  # noqa: E402
from coehoorn.judge import judge_all  # noqa: E402
from coehoorn.personas import generate_personas_heuristic  # noqa: E402
from coehoorn.report_html import render_report_html, write_report_html  # noqa: E402
from coehoorn.rubric_parser import parse_rubric_file  # noqa: E402
from coehoorn.schemas import VerdictOutcome  # noqa: E402

import yaml  # noqa: E402


def _stub_call_factory():
    import random
    random.seed(20260517)  # deterministic stochastic-flaw outcomes
    from app import app  # noqa: E402

    client = app.test_client()

    def _call(conversation):
        resp = client.post("/chat", json={"conversation": conversation})
        return resp.get_json()["reply"]

    return CallableAdapter(_call)


@pytest.mark.asyncio
async def test_full_pipeline_catches_self_harm_flaw_and_runs_to_report(tmp_path: Path):
    import random
    random.seed(20260517)
    rubric, rules = parse_rubric_file(
        Path(__file__).parent.parent / "examples" / "rubric_coach.yaml"
    )
    expected_raw = yaml.safe_load(
        (Path(__file__).parent.parent / "examples" / "expected_failures.yaml").read_text()
    )
    expected = expected_raw["personas"]

    personas = generate_personas_heuristic(n=6)
    agent = _stub_call_factory()
    started = datetime.now(timezone.utc)
    transcripts = await run_conversations(
        personas, agent, max_turns=4, mode="heuristic", concurrency=4
    )
    verdicts = judge_all(transcripts, rubric, rules, mode="heuristic")
    completed = datetime.now(timezone.utc)
    report = build_report(
        rubric=rubric, transcripts=transcripts, verdicts=verdicts,
        agent_endpoint="in-process://stub",
        created_at=started, completed_at=completed,
    )

    # Self-harm flaw is deterministic: every emotional-archetype run hits it.
    breached_personas = {
        t.persona.id
        for t in transcripts
        for v in verdicts
        if v.transcript_id == t.id and v.outcome is VerdictOutcome.FAIL
    }
    assert "p02" in breached_personas, (
        "Expected EMOTIONAL persona p02 to catch self-harm flaw; "
        f"got breached_personas={breached_personas}"
    )

    diff = compare_to_expected(report, expected)
    # p02 (self-harm) must be an exact match — it's deterministic.
    assert diff["p02"]["match"] is True, (
        f"Self-harm flaw catch mismatch: {diff['p02']}"
    )
    # No false positives for clean personas.
    for pid in ("p00", "p01", "p04"):
        assert diff[pid]["false_positives"] == [], (
            f"Persona {pid} produced unexpected failures: {diff[pid]}"
        )

    # HTML render must produce non-empty self-contained output.
    html = render_report_html(report)
    assert "<html" in html.lower()
    assert "Siege Survey" in html
    assert "<script" not in html.lower()  # self-contained, no JS
    html_path = write_report_html(report, tmp_path / "report.html")
    assert html_path.exists()
    assert html_path.stat().st_size > 1000
