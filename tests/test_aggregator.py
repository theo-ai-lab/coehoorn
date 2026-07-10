from datetime import UTC, datetime
from pathlib import Path

from coehoorn.aggregator import (
    build_report,
    compare_to_expected,
    load_report_json,
    write_comparison_json,
    write_report_json,
)
from coehoorn.schemas import (
    Archetype,
    ConversationTurn,
    Criterion,
    CriterionStatus,
    CriterionVerdict,
    Persona,
    Rubric,
    Transcript,
    Verdict,
    VerdictOutcome,
)


def _rubric():
    return Rubric(
        criteria=[Criterion(id="x", description="d"), Criterion(id="y", description="d")],
        overall_pass_threshold=1.0,
    )


def _t(persona_id="p00", arch=Archetype.EMOTIONAL):
    now = datetime.now(UTC)
    return Transcript(
        id=f"t-{persona_id}",
        persona=Persona(id=persona_id, archetype=arch, name="n", description="d"),
        turns=[
            ConversationTurn(index=0, role="user", content="u"),
            ConversationTurn(index=1, role="assistant", content="a"),
        ],
        started_at=now, completed_at=now,
    )


def _verdict_for(t, fail_x=False):
    return Verdict(
        transcript_id=t.id,
        criterion_verdicts=[
            CriterionVerdict(
                criterion_id="x",
                status=CriterionStatus.FAIL if fail_x else CriterionStatus.PASS,
                confidence=0.9,
                cited_turn_index=1 if fail_x else None,
                rationale="bad" if fail_x else "ok",
            ),
            CriterionVerdict(
                criterion_id="y", status=CriterionStatus.PASS, confidence=0.9,
                cited_turn_index=None, rationale="ok",
            ),
        ],
        outcome=VerdictOutcome.FAIL if fail_x else VerdictOutcome.PASS,
        worst_moment_turn_index=1 if fail_x else None,
    )


def test_build_and_round_trip_report(tmp_path: Path):
    t1, t2 = _t("p00"), _t("p01")
    v1, v2 = _verdict_for(t1, fail_x=True), _verdict_for(t2, fail_x=False)
    r = build_report(
        rubric=_rubric(),
        transcripts=[t1, t2],
        verdicts=[v1, v2],
        agent_endpoint="http://127.0.0.1:8001/chat",
    )
    out = write_report_json(r, tmp_path / "r.json")
    r2 = load_report_json(out)
    assert r == r2
    assert r2.pass_rate == 0.5


def test_compare_to_expected_diff():
    t0, t1 = _t("p00"), _t("p01")
    v0 = _verdict_for(t0, fail_x=True)  # actual: ['x']
    v1 = _verdict_for(t1, fail_x=False)  # actual: []
    r = build_report(
        rubric=_rubric(),
        transcripts=[t0, t1],
        verdicts=[v0, v1],
        agent_endpoint="x",
    )
    diff = compare_to_expected(r, {"p00": ["x"], "p01": ["x"]})
    assert diff["p00"]["match"] is True
    assert diff["p00"]["true_positives"] == ["x"]
    assert diff["p01"]["match"] is False
    assert diff["p01"]["false_negatives"] == ["x"]


def test_write_comparison_summary(tmp_path: Path):
    t0 = _t("p00")
    v0 = _verdict_for(t0, fail_x=True)
    r = build_report(
        rubric=_rubric(), transcripts=[t0], verdicts=[v0], agent_endpoint="x"
    )
    diff = compare_to_expected(r, {"p00": ["x"]})
    out = write_comparison_json(diff, tmp_path / "cmp.json")
    import json as _json
    payload = _json.loads(out.read_text())
    assert payload["summary"]["exact_matches"] == 1
    assert payload["summary"]["total_true_positives"] == 1
