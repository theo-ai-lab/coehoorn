"""Distill-into-the-floor — deterministic, offline, keyless tests.

Covers the effective-vote machinery (the correlation correction), the mock-jury
fixture, the conjectured residual siege, candidate mining, the OUT-OF-SAMPLE
holdout gate (and its teeth), the replaceable-fraction report, the full pipeline,
and the CLI. The live LLM jury is never called — only its honest key-gating is
asserted.
"""
from __future__ import annotations

import argparse
import json

import pytest
from pydantic import ValidationError

from coehoorn import distill
from coehoorn.distill import (
    DistillationReport,
    DistilledVerifier,
    EffectiveVotes,
    GoldCase,
    already_distilled_verifiers,
    conjectured_residual_siege,
    effective_votes,
    holdout_gate,
    llm_jury,
    mine_candidate_rule,
    mock_jury,
    redundant_mock_jury,
    run_distillation,
    run_jury,
)
from coehoorn.schemas import CriterionStatus, Rubric


def _votes(matrix: dict[str, list[CriterionStatus]]) -> dict[str, dict[str, CriterionStatus]]:
    """Turn ``{juror: [status per cell]}`` into the run-time vote matrix shape."""
    return {
        name: {f"c{i}": st for i, st in enumerate(row)} for name, row in matrix.items()
    }


F, P, A = CriterionStatus.FAIL, CriterionStatus.PASS, CriterionStatus.ABSTAIN


# --------------------------------------------------------------------------- #
# (1) The already-distilled verifiers (the framing).
# --------------------------------------------------------------------------- #
def test_already_distilled_verifiers_are_real_and_model_free():
    vs = already_distilled_verifiers()
    assert len(vs) == 5
    assert all(isinstance(v, DistilledVerifier) for v in vs)
    assert all(v.model_free and v.keyless for v in vs)
    # Each names a real location in this repo.
    locations = {v.location for v in vs}
    assert "coehoorn/judge.py:_criterion_fails" in locations
    assert "coehoorn/metamorphic.py:run_cite_mr" in locations
    assert "coehoorn/schemas.py:Report._referential_integrity" in locations
    # Each replaced a judgment call with a deterministic mechanism.
    assert all(v.replaced_judgment and v.mechanism for v in vs)


# --------------------------------------------------------------------------- #
# (2) Effective votes — the correlation correction.
# --------------------------------------------------------------------------- #
def test_identical_jurors_collapse_to_one_effective_vote():
    ev = effective_votes(_votes({"a": [F, P, F, P], "b": [F, P, F, P]}))
    assert ev.n_members == 2
    assert ev.mean_pairwise_correlation == pytest.approx(1.0)
    assert ev.effective_votes == pytest.approx(1.0)


def test_anticorrelated_jurors_count_as_independent():
    # Pearson -1 is clamped to 0 (treated as at-least-independent, never bonus).
    ev = effective_votes(_votes({"a": [F, P, F, P], "b": [P, F, P, F]}))
    assert ev.mean_pairwise_correlation == pytest.approx(0.0)
    assert ev.effective_votes == pytest.approx(2.0)


def test_single_juror_has_one_effective_vote():
    ev = effective_votes(_votes({"solo": [F, P, F]}))
    assert ev.n_members == 1 and ev.effective_votes == pytest.approx(1.0)


def test_constant_juror_is_treated_conservatively():
    # A constant juror vs a varying one: zero variance -> correlation 0 unless the
    # vectors are identical (they are not), so it is not over-counted as redundant.
    ev = effective_votes(_votes({"const": [F, F, F, F], "vary": [F, P, F, P]}))
    assert ev.mean_pairwise_correlation == pytest.approx(0.0)
    # Two identical constants are perfectly redundant -> one effective vote.
    ev2 = effective_votes(_votes({"a": [F, F, F], "b": [F, F, F]}))
    assert ev2.effective_votes == pytest.approx(1.0)


def test_abstentions_are_excluded_from_the_pairwise_set():
    # Co-decided cells only: the abstained cell drops out, the rest are identical.
    ev = effective_votes(_votes({"a": [F, A, P, F], "b": [F, P, P, F]}))
    # co-decided cells: 0 (F,F), 2 (P,P), 3 (F,F) -> identical -> rho 1.
    assert ev.effective_votes == pytest.approx(1.0)


def test_effective_votes_cannot_exceed_members():
    with pytest.raises(ValidationError):
        EffectiveVotes(
            n_members=2, n_pairs=1, mean_pairwise_correlation=0.0, effective_votes=5.0
        )


# --------------------------------------------------------------------------- #
# (2) The mock jury — four members, ~two effective votes (the headline lesson).
# --------------------------------------------------------------------------- #
def test_mock_jury_has_four_members_but_two_effective_votes():
    deriv, _ = conjectured_residual_siege()
    jv = run_jury(mock_jury(), deriv)
    assert jv.effective.n_members == 4
    # Four judges, two effective votes — the correlation correction made concrete.
    assert jv.effective.effective_votes == pytest.approx(2.0, abs=1e-6)
    assert jv.effective.mean_pairwise_correlation == pytest.approx(1 / 3, abs=1e-6)
    assert jv.trustworthy is True  # clears the 1.5 floor


def test_jury_high_consensus_excludes_the_split_borderline_cells():
    deriv, _ = conjectured_residual_siege()
    jv = run_jury(mock_jury(), deriv)
    # 3 clear PASS + 3 clear FAIL are unanimous; the 6 borderline cells split 2/2.
    assert len(jv.high_consensus_case_ids) == 6
    split = [c for c in jv.cells if not c.agree]
    assert len(split) == 6
    assert all(c.modal_fraction == pytest.approx(0.5) for c in split)


def test_redundant_jury_is_blocked_by_the_effective_vote_gate():
    deriv, _ = conjectured_residual_siege()
    jv = run_jury(redundant_mock_jury(9), deriv)
    # Nine clones -> one effective vote, no matter the member count.
    assert jv.effective.n_members == 9
    assert jv.effective.effective_votes == pytest.approx(1.0)
    assert jv.trustworthy is False
    assert jv.high_consensus_case_ids == []  # a correlated bloc cannot back a distill


def test_run_jury_rejects_empty_or_bad_threshold():
    deriv, _ = conjectured_residual_siege()
    with pytest.raises(ValueError):
        run_jury([], deriv)
    with pytest.raises(ValueError):
        run_jury(mock_jury(), deriv, consensus_threshold=0.0)


# --------------------------------------------------------------------------- #
# Conjectured residual siege.
# --------------------------------------------------------------------------- #
def test_residual_siege_is_conjectured_with_two_distinct_slices():
    deriv, hold = conjectured_residual_siege()
    assert len(deriv) == 12 and len(hold) == 6
    assert all(c.criterion_id == "tone_is_supportive" for c in deriv + hold)
    assert all("conjectured residual" in c.note for c in deriv + hold)
    # The two slices come from different conjectured seeds (a real out-of-sample split).
    assert {c.id.split("-r")[0] for c in deriv} == {"tone-deriv"}
    assert {c.id.split("-r")[0] for c in hold} == {"tone-holdout"}


# --------------------------------------------------------------------------- #
# (3) Candidate mining.
# --------------------------------------------------------------------------- #
def _labeled_high_consensus():
    deriv, _ = conjectured_residual_siege()
    jv = run_jury(mock_jury(), deriv)
    by_id = {c.id: c for c in deriv}
    modal = {cell.case_id: cell.modal_status for cell in jv.cells}
    return [(by_id[cid], modal[cid]) for cid in jv.high_consensus_case_ids]


def test_mine_candidate_recovers_recurring_support_signals():
    cand = mine_candidate_rule(
        "tone_is_supportive", _labeled_high_consensus(),
        jury_members=4, effective_votes=2.0,
    )
    assert cand is not None
    # The recurring, discriminating support signals — not idiosyncratic noise.
    assert cand.mined_lacks_any == ["believe", "proud", "support"]
    assert "nervous" in cand.scope_probe_any
    assert cand.n_pass_cells == 3 and cand.n_fail_cells == 3


def test_mine_returns_none_without_both_classes_or_a_signal():
    deriv, _ = conjectured_residual_siege()
    only_pass = [(c, CriterionStatus.PASS) for c in deriv[:3]]
    assert mine_candidate_rule(
        "tone_is_supportive", only_pass, jury_members=4, effective_votes=2.0
    ) is None
    # Both classes but no discriminating recurring token: the support word also
    # appears in the FAIL reply, so it is subtracted away.
    same = [
        GoldCase(id="p1", criterion_id="tone_is_supportive", gold=CriterionStatus.PASS,
                 turns=[("user", "I am nervous"), ("assistant", "support support fine")]),
        GoldCase(id="p2", criterion_id="tone_is_supportive", gold=CriterionStatus.PASS,
                 turns=[("user", "I am nervous"), ("assistant", "support truly here")]),
        GoldCase(id="f1", criterion_id="tone_is_supportive", gold=CriterionStatus.FAIL,
                 gold_cited_turn=1,
                 turns=[("user", "I am nervous"), ("assistant", "support yourself alone")]),
    ]
    labeled = [(same[0], P), (same[1], P), (same[2], F)]
    assert mine_candidate_rule(
        "tone_is_supportive", labeled, jury_members=4, effective_votes=2.0
    ) is None


# --------------------------------------------------------------------------- #
# (4) The holdout gate (and its teeth) + (6) replaceable fraction.
# --------------------------------------------------------------------------- #
def test_holdout_gate_promotes_the_honest_candidate_out_of_sample():
    _deriv, hold = conjectured_residual_siege()
    cand = mine_candidate_rule(
        "tone_is_supportive", _labeled_high_consensus(),
        jury_members=4, effective_votes=2.0,
    )
    receipt = holdout_gate(cand, hold, threshold=0.8)
    assert receipt.promoted is True
    # 5/6 out-of-sample: the lone error is the near-miss that name-drops "support"
    # to dismiss the user — the cell the keyword rule legitimately cannot own.
    assert receipt.holdout_n == 6 and receipt.holdout_matches == 5
    assert receipt.holdout_agreement == pytest.approx(5 / 6)
    assert "effective votes" in receipt.provenance


def test_holdout_gate_has_teeth_against_an_overfit_candidate():
    # A candidate mined to a derivation-only token ("truly") does NOT generalize:
    # the holdout PASS replies lack it, so the rule wrongly FAILs them. The gate
    # must reject it — an in-sample fit earns nothing.
    _deriv, hold = conjectured_residual_siege()
    overfit = distill.DistillCandidate(
        criterion_id="tone_is_supportive",
        mined_lacks_any=["truly"],
        scope_probe_any=["nervous"],
        derived_from_n=3, n_pass_cells=2, n_fail_cells=1,
        jury_members=4, effective_votes=2.0,
        rationale="deliberately overfit token",
    )
    receipt = holdout_gate(overfit, hold, threshold=0.8)
    assert receipt.promoted is False
    assert receipt.holdout_agreement is not None
    assert receipt.holdout_agreement < 0.8


def test_holdout_gate_rejects_when_threshold_is_above_the_achieved_agreement():
    _deriv, hold = conjectured_residual_siege()
    cand = mine_candidate_rule(
        "tone_is_supportive", _labeled_high_consensus(),
        jury_members=4, effective_votes=2.0,
    )
    receipt = holdout_gate(cand, hold, threshold=0.95)  # above the 0.833 achieved
    assert receipt.promoted is False


def test_promotion_receipt_invariant_rejects_inconsistent_promotion():
    cand = mine_candidate_rule(
        "tone_is_supportive", _labeled_high_consensus(),
        jury_members=4, effective_votes=2.0,
    )
    with pytest.raises(ValidationError):
        distill.PromotionReceipt(
            candidate=cand, holdout_n=6, holdout_matches=3, holdout_decided=6,
            holdout_agreement=0.5, threshold=0.8, promoted=True,  # 0.5 < 0.8
            provenance="x",
        )


# --------------------------------------------------------------------------- #
# Full pipeline.
# --------------------------------------------------------------------------- #
def test_run_distillation_end_to_end_is_deterministic_and_roundtrips():
    a = run_distillation()
    b = run_distillation()
    assert a.model_dump_json() == b.model_dump_json()  # deterministic
    again = DistillationReport.model_validate_json(a.model_dump_json())
    assert again.coverage.replaceable_fraction == pytest.approx(a.coverage.replaceable_fraction)

    assert a.candidate is not None and a.promotion is not None
    assert a.promotion.promoted is True
    # The honest, OUT-OF-SAMPLE replaceable fraction (not the in-sample fit).
    assert a.coverage.replaceable_fraction == pytest.approx(5 / 6)
    assert a.coverage.deterministic_coverage_before == 0.0
    assert a.coverage.deterministic_coverage_after == pytest.approx(5 / 6)
    assert a.coverage.llm_residual_after == pytest.approx(1 / 6)


def test_distillation_blocked_by_redundant_jury_yields_no_promotion():
    r = run_distillation(jury=redundant_mock_jury(4))
    assert r.candidate is None
    assert r.promotion is None
    assert r.coverage.replaceable_fraction == 0.0
    assert r.coverage.llm_residual_after == 1.0  # LLM judge still owns the residual


def test_replaceable_coverage_complementary_invariant():
    r = run_distillation()
    cov = r.coverage
    assert cov.deterministic_coverage_after + cov.llm_residual_after == pytest.approx(1.0)
    assert cov.deterministic_coverage_before + cov.llm_residual_before == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Key-gated live jury (no fake fallback).
# --------------------------------------------------------------------------- #
def test_llm_jury_raises_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rubric = Rubric.model_validate(
        {"criteria": [{"id": "tone_is_supportive", "description": "tone"}],
         "overall_pass_threshold": 1.0}
    )
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        llm_jury(rubric, "tone_is_supportive", models=("claude-sonnet-4-6",))


def test_llm_jury_requires_a_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-placeholder")
    rubric = Rubric.model_validate(
        {"criteria": [{"id": "tone_is_supportive", "description": "tone"}],
         "overall_pass_threshold": 1.0}
    )
    with pytest.raises(ValueError, match="at least one model"):
        llm_jury(rubric, "tone_is_supportive", models=())


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
RUBRIC = "examples/rubric_coach.yaml"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="test")
    sub = p.add_subparsers(dest="cmd", required=True)
    distill.register_subparser(sub)
    return p


def test_cli_distill_floor_json_and_human(capsys):
    p = _parser()
    args = p.parse_args(["distill-floor", "--rubric", RUBRIC, "--json"])
    assert args._func(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["jury"]["effective"]["effective_votes"] == pytest.approx(2.0, abs=1e-6)
    assert payload["promotion"]["promoted"] is True
    assert payload["coverage"]["replaceable_fraction"] == pytest.approx(5 / 6)
    assert len(payload["prior_verifiers"]) == 5

    args2 = p.parse_args(["distill-floor", "--rubric", RUBRIC])
    assert args2._func(args2) == 0
    err = capsys.readouterr().err
    assert "EFFECTIVE votes" in err and "Nine-Judges-Two-Votes" in err
    assert "HOLDOUT GATE" in err


def test_cli_distill_replaceable_gate(capsys):
    p = _parser()
    base = ["distill-floor", "--rubric", RUBRIC]
    high = p.parse_args([*base, "--min-replaceable-fraction", "0.95"])
    assert high._func(high) == 1
    assert "GATE FAILED" in capsys.readouterr().err
    low = p.parse_args([*base, "--min-replaceable-fraction", "0.8"])
    assert low._func(low) == 0


def test_cli_distill_llm_without_key_exits_two(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = _parser()
    args = p.parse_args(["distill-floor", "--rubric", RUBRIC, "--mode", "llm"])
    assert args._func(args) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_cli_distill_clean_error_on_missing_rubric(capsys):
    p = _parser()
    args = p.parse_args(["distill-floor", "--rubric", "/nonexistent/rubric.yaml"])
    assert args._func(args) == 2
    assert "error" in capsys.readouterr().err.lower()
