"""Tests for the Pydantic wire-contract schemas — the trust boundary.

These exercise the invariants the rest of the system relies on:
- A failed CriterionVerdict must cite a turn; a pass/abstain must not.
- An abstention must explain itself.
- Verdict.outcome is bound to its criteria: fail needs a cited breach and a
  worst moment that matches it; pass forbids any breach; abstain requires
  every criterion to abstain.
- Report enforces 1:1 transcript/verdict, criterion coverage, and that cited
  turn indices exist in the linked transcript.
- Round-trip (dump_json -> validate_json) preserves equality without
  weakening extra="forbid", including the computed pass/abstention rates.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from coehoorn.schemas import (
    Archetype,
    ConversationTurn,
    Criterion,
    CriterionStatus,
    CriterionVerdict,
    Persona,
    Report,
    Rubric,
    Transcript,
    Verdict,
    VerdictOutcome,
)


def _persona(pid="p00", arch=Archetype.EMOTIONAL):
    return Persona(id=pid, archetype=arch, name="Casey", description="distressed user")


def _rubric():
    return Rubric(
        criteria=[
            Criterion(id="safe_handling_of_self_harm", description="x"),
            Criterion(id="no_fabricated_legal_citations", description="y"),
        ],
        overall_pass_threshold=1.0,
    )


def _cv(cid, status, *, cited=None, rationale="ok"):
    return CriterionVerdict(
        criterion_id=cid, status=status, confidence=0.9,
        cited_turn_index=cited, rationale=rationale,
    )


def _two_turn_transcript(tid="t1"):
    now = datetime.now(timezone.utc)
    return Transcript(
        id=tid,
        persona=_persona(),
        turns=[
            ConversationTurn(index=0, role="user", content="hi"),
            ConversationTurn(index=1, role="assistant", content="hello"),
        ],
        started_at=now,
        completed_at=now,
    )


# --- CriterionVerdict status invariants -----------------------------------

def test_fail_requires_cited_turn():
    with pytest.raises(ValidationError):
        _cv("x", CriterionStatus.FAIL, cited=None, rationale="missing citation")


def test_fail_requires_non_empty_rationale():
    with pytest.raises(ValidationError):
        _cv("x", CriterionStatus.FAIL, cited=0, rationale="   ")


def test_pass_forbids_cited_turn():
    with pytest.raises(ValidationError):
        _cv("x", CriterionStatus.PASS, cited=1)


def test_abstain_forbids_cited_turn():
    with pytest.raises(ValidationError):
        _cv("x", CriterionStatus.ABSTAIN, cited=1, rationale="no basis")


def test_abstain_requires_rationale():
    with pytest.raises(ValidationError):
        _cv("x", CriterionStatus.ABSTAIN, cited=None, rationale="  ")


def test_pass_with_no_citation_is_valid():
    cv = _cv("x", CriterionStatus.PASS)
    assert cv.status is CriterionStatus.PASS
    assert cv.cited_turn_index is None


# --- Verdict outcome invariants -------------------------------------------

def test_outcome_fail_requires_worst_moment():
    with pytest.raises(ValidationError):
        Verdict(
            transcript_id="t1",
            criterion_verdicts=[_cv("x", CriterionStatus.FAIL, cited=1, rationale="bad")],
            outcome=VerdictOutcome.FAIL,
            worst_moment_turn_index=None,
        )


def test_outcome_fail_worst_moment_must_match_a_failed_citation():
    with pytest.raises(ValidationError):
        Verdict(
            transcript_id="t1",
            criterion_verdicts=[_cv("x", CriterionStatus.FAIL, cited=1, rationale="bad")],
            outcome=VerdictOutcome.FAIL,
            worst_moment_turn_index=2,  # no failed criterion cites turn 2
        )


def test_outcome_fail_requires_a_failed_criterion():
    with pytest.raises(ValidationError):
        Verdict(
            transcript_id="t1",
            criterion_verdicts=[_cv("x", CriterionStatus.PASS)],
            outcome=VerdictOutcome.FAIL,
            worst_moment_turn_index=1,
        )


def test_outcome_pass_forbids_worst_moment():
    with pytest.raises(ValidationError):
        Verdict(
            transcript_id="t1",
            criterion_verdicts=[_cv("x", CriterionStatus.PASS)],
            outcome=VerdictOutcome.PASS,
            worst_moment_turn_index=1,
        )


def test_outcome_pass_forbids_a_breach():
    with pytest.raises(ValidationError):
        Verdict(
            transcript_id="t1",
            criterion_verdicts=[_cv("x", CriterionStatus.FAIL, cited=1, rationale="bad")],
            outcome=VerdictOutcome.PASS,
            worst_moment_turn_index=None,
        )


def test_outcome_abstain_requires_all_criteria_abstain():
    with pytest.raises(ValidationError):
        Verdict(
            transcript_id="t1",
            criterion_verdicts=[
                _cv("x", CriterionStatus.ABSTAIN, rationale="no basis"),
                _cv("y", CriterionStatus.PASS),
            ],
            outcome=VerdictOutcome.ABSTAIN,
            worst_moment_turn_index=None,
        )


def test_outcome_pass_rejected_when_all_abstain():
    with pytest.raises(ValidationError):
        Verdict(
            transcript_id="t1",
            criterion_verdicts=[_cv("x", CriterionStatus.ABSTAIN, rationale="no basis")],
            outcome=VerdictOutcome.PASS,
            worst_moment_turn_index=None,
        )


def test_valid_abstain_verdict():
    v = Verdict(
        transcript_id="t1",
        criterion_verdicts=[_cv("x", CriterionStatus.ABSTAIN, rationale="no basis")],
        outcome=VerdictOutcome.ABSTAIN,
        worst_moment_turn_index=None,
    )
    assert v.outcome is VerdictOutcome.ABSTAIN


# --- Report-level invariants + round-trip ---------------------------------

def test_report_round_trip_preserves_equality_with_extras_forbidden():
    now = datetime.now(timezone.utc)
    t = _two_turn_transcript()
    v = Verdict(
        transcript_id=t.id,
        criterion_verdicts=[
            _cv("safe_handling_of_self_harm", CriterionStatus.PASS),
            _cv("no_fabricated_legal_citations", CriterionStatus.ABSTAIN, rationale="no rule"),
        ],
        outcome=VerdictOutcome.PASS,
        worst_moment_turn_index=None,
    )
    r = Report(
        created_at=now, completed_at=now,
        agent_endpoint="http://127.0.0.1:8001/chat",
        rubric=_rubric(), transcripts=[t], verdicts=[v],
    )
    assert r.pass_rate == 1.0
    assert r.abstention_rate == 0.0
    r2 = Report.model_validate_json(r.model_dump_json())
    assert r == r2


def test_report_rejects_cited_turn_not_in_transcript():
    now = datetime.now(timezone.utc)
    t = _two_turn_transcript()
    bad_v = Verdict(
        transcript_id=t.id,
        criterion_verdicts=[
            _cv("safe_handling_of_self_harm", CriterionStatus.FAIL, cited=99, rationale="bad"),
            _cv("no_fabricated_legal_citations", CriterionStatus.PASS),
        ],
        outcome=VerdictOutcome.FAIL,
        worst_moment_turn_index=99,
    )
    with pytest.raises(ValidationError):
        Report(
            created_at=now, completed_at=now,
            agent_endpoint="x", rubric=_rubric(), transcripts=[t], verdicts=[bad_v],
        )


def test_report_rejects_duplicate_persona_ids():
    now = datetime.now(timezone.utc)
    # Two distinct transcripts, same persona id — a silent-undercount hazard.
    t1 = _two_turn_transcript(tid="t1")
    t2 = _two_turn_transcript(tid="t2")  # _persona() is p00 for both
    v1 = Verdict(
        transcript_id="t1",
        criterion_verdicts=[
            _cv("safe_handling_of_self_harm", CriterionStatus.PASS),
            _cv("no_fabricated_legal_citations", CriterionStatus.PASS),
        ],
        outcome=VerdictOutcome.PASS, worst_moment_turn_index=None,
    )
    v2 = Verdict(
        transcript_id="t2",
        criterion_verdicts=[
            _cv("safe_handling_of_self_harm", CriterionStatus.PASS),
            _cv("no_fabricated_legal_citations", CriterionStatus.PASS),
        ],
        outcome=VerdictOutcome.PASS, worst_moment_turn_index=None,
    )
    with pytest.raises(ValidationError):
        Report(
            created_at=now, completed_at=now, agent_endpoint="x",
            rubric=_rubric(), transcripts=[t1, t2], verdicts=[v1, v2],
        )


def test_report_rejects_unknown_field():
    now = datetime.now(timezone.utc)
    t = _two_turn_transcript()
    v = Verdict(
        transcript_id=t.id,
        criterion_verdicts=[
            _cv("safe_handling_of_self_harm", CriterionStatus.PASS),
            _cv("no_fabricated_legal_citations", CriterionStatus.PASS),
        ],
        outcome=VerdictOutcome.PASS,
        worst_moment_turn_index=None,
    )
    payload = Report(
        created_at=now, completed_at=now, agent_endpoint="x",
        rubric=_rubric(), transcripts=[t], verdicts=[v],
    ).model_dump()
    payload["surprise_field"] = "uh oh"
    with pytest.raises(ValidationError):
        Report.model_validate(payload)
