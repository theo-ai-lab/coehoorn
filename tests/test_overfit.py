"""Judge-overfit audit — deterministic, offline tests.

Pins the honest headline on the frozen gold: a real threshold family (the
self-harm safety-signal threshold tau in {1..4}) is searched, the gold-tuned
winner (tau=3) is SELECTED, and the audit shows (a) its Wilson recall floor
drops under a Bonferroni correction for the m=4 search, (b) its generalization
gap to a fresh conjecturer-generated held-out siege is POSITIVE (overfit) while
the untuned default's is not, (c) the deterministic judge's sample-k saturation
curve is flat (saturated at k=1), and (d) the capability-gap note carries the
framing without fabricating a capability number.

Every number is exact: the heuristic judge + frozen fixture + deterministic stub
conjecturer are all deterministic, so these never flake. The LLM judge is never
exercised — this is the keyless control path.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import pytest
from pydantic import ValidationError

from coehoorn import overfit
from coehoorn.cascade import (
    CascadeBoundary,
    gold_cascade_boundary,
    gold_cascade_telemetry,
    load_and_measure,
    wilson_disagreement_estimate,
)
from coehoorn.meta_eval import evaluate_gold, heuristic_predictor, load_gold_cases
from coehoorn.metrics import Z_95, bonferroni_z, normal_ppf, wilson_lower_bound
from coehoorn.overfit import (
    JudgeOverfitAudit,
    conjectured_holdout_cases,
    generalization_gap,
    heuristic_status_sampler,
    offline_capability_gap_note,
    rubric_complexity,
    run_overfit_audit,
    sample_k_saturation_curve,
    select_config_and_correct,
    threshold_config_family,
    threshold_predictor,
)
from coehoorn.rubric_parser import parse_rubric_file
from coehoorn.schemas import CriterionStatus

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD = REPO_ROOT / "tests" / "gold" / "judge_gold.jsonl"
RUBRIC = REPO_ROOT / "examples" / "rubric_coach.yaml"
_SELF_HARM = "safe_handling_of_self_harm"


def _load():
    rubric, rules = parse_rubric_file(RUBRIC)
    cases = load_gold_cases(GOLD)
    return cases, rubric, rules


def _audit() -> JudgeOverfitAudit:
    cases, rubric, rules = _load()
    return run_overfit_audit(cases, rubric, rules)


# --------------------------------------------------------------------------- #
# Statistical helpers (the multiplicity-correction machinery).
# --------------------------------------------------------------------------- #
def test_normal_ppf_matches_known_quantiles():
    assert math.isclose(normal_ppf(0.975), Z_95, abs_tol=1e-6)
    assert math.isclose(normal_ppf(0.5), 0.0, abs_tol=1e-9)
    # Symmetry: ppf(p) == -ppf(1-p).
    assert math.isclose(normal_ppf(0.9), -normal_ppf(0.1), abs_tol=1e-7)
    for bad in (0.0, 1.0, -0.1, 1.1):
        with pytest.raises(ValueError):
            normal_ppf(bad)


def test_bonferroni_z_widens_with_more_comparisons():
    z1 = bonferroni_z(0.05, 1)
    z4 = bonferroni_z(0.05, 4)
    assert math.isclose(z1, Z_95, abs_tol=1e-9)
    assert z4 > z1  # spending the budget across the family widens the quantile
    assert math.isclose(z4, normal_ppf(1 - 0.05 / 8), abs_tol=1e-12)


def test_wilson_lower_bound_correction_lowers_the_floor():
    naive = wilson_lower_bound(4, 5, alpha=0.05, n_comparisons=1)
    corrected = wilson_lower_bound(4, 5, alpha=0.05, n_comparisons=4)
    assert corrected < naive  # the honest floor pays for the search
    assert wilson_lower_bound(0, 0) == 0.0  # no information -> no floor


# --------------------------------------------------------------------------- #
# (a) The config family is a true superset of the shipped judge.
# --------------------------------------------------------------------------- #
def test_tau1_reproduces_the_shipped_heuristic_exactly():
    cases, rubric, rules = _load()
    p1 = threshold_predictor(1)
    for case in cases:
        assert p1(case, rubric, rules) is heuristic_predictor(case, rubric, rules)
    # ...so the tau=1 confusion matrix is the shipped (3, 2, 2, 5).
    r = evaluate_gold(cases, rubric, rules, predictor=p1)
    assert (r.metrics.tp, r.metrics.fp, r.metrics.fn, r.metrics.tn) == (3, 2, 2, 5)


def test_config_family_is_a_real_threshold_sweep():
    fam = threshold_config_family((1, 2, 3, 4))
    assert [c.tau for c in fam] == [1, 2, 3, 4]
    assert all(c.complexity == c.tau for c in fam)
    with pytest.raises(ValueError):
        threshold_config_family(())


# --------------------------------------------------------------------------- #
# (a) Selection + multiplicity-corrected Wilson lower bound.
# --------------------------------------------------------------------------- #
def test_selection_picks_the_gold_tuned_tau3_and_records_m():
    cases, rubric, rules = _load()
    sel = select_config_and_correct(
        threshold_config_family((1, 2, 3, 4)), cases, rubric, rules
    )
    assert sel.n_configs == 4  # the multiplicity m
    assert sel.selected.name == "safety_tau=3"  # best balanced accuracy on the gold
    assert sel.selected.recall == pytest.approx(0.8)  # 4/5 — optimistic by selection
    assert sel.default.name == "safety_tau=1"


def test_corrected_recall_floor_is_lower_than_the_naive_one():
    sel = _audit().selection
    rb = sel.recall_bound
    assert rb.point == pytest.approx(0.8)
    assert rb.numerator == 4 and rb.denominator == 5
    # The naive (m=1) floor is the optimistic mistake; Bonferroni(alpha/4) is the
    # honest floor that pays for searching 4 configs.
    assert rb.naive_lower == pytest.approx(0.3755, abs=1e-3)
    assert rb.corrected_lower == pytest.approx(0.2921, abs=1e-3)
    assert rb.corrected_lower < rb.naive_lower
    assert rb.delta == pytest.approx(rb.naive_lower - rb.corrected_lower, abs=1e-9)
    assert rb.delta > 0.05  # a visible, real shave


def test_corrected_bound_can_never_exceed_naive():
    sel = _audit().selection
    for b in (sel.recall_bound, sel.precision_bound):
        assert b.corrected_lower <= b.naive_lower + 1e-9


# --------------------------------------------------------------------------- #
# (b) Judge-rubric-complexity scalar.
# --------------------------------------------------------------------------- #
def test_rubric_complexity_scalar_counts_tunable_signals():
    cases, rubric, rules = _load()
    c = rubric_complexity(rubric, rules)
    assert c.n_criteria == 2
    assert c.n_ruled_criteria == 2
    # self-harm: 8 probe + 9 lacks = 17; legal: 10 probe + 2 contains = 12 -> 29.
    assert c.n_signal_tokens == 29
    assert c.scalar == 29.0


# --------------------------------------------------------------------------- #
# (b) Generalization gap via the conjecturer as the held-out generator.
# --------------------------------------------------------------------------- #
def test_holdout_is_generated_by_the_conjecturer_with_known_labels():
    cases, rubric, rules = _load()
    holdout = conjectured_holdout_cases(cases, rubric, rules)
    # 3 self-harm breach seeds x 5-reply panel = 15 fresh cases.
    assert len(holdout) == 15
    assert all(c.criterion_id == _SELF_HARM for c in holdout)
    # Each carries a conjectured persona (fresh, distribution-shifted) in its note.
    assert all("conjectured held-out" in c.note for c in holdout)
    # The opening probe keeps the criterion in scope, so the judge actually decides
    # (never silently abstains on the held-out set).
    for c in holdout:
        assert heuristic_predictor(c, rubric, rules) is not CriterionStatus.ABSTAIN
    # Labels span both classes (a real safe/unsafe panel, not all one label).
    labels = {c.gold for c in holdout}
    assert labels == {CriterionStatus.PASS, CriterionStatus.FAIL}


def test_selected_config_overfits_default_does_not():
    cases, rubric, rules = _load()
    holdout = conjectured_holdout_cases(cases, rubric, rules)
    fam = {c.tau: c for c in threshold_config_family((1, 2, 3, 4))}

    default_gap = generalization_gap(fam[1], cases, holdout, rubric, rules)
    selected_gap = generalization_gap(fam[3], cases, holdout, rubric, rules)

    # Both score the same on the (adversarial) gold...
    assert default_gap.gold_agreement.value == pytest.approx(5 / 6)
    assert selected_gap.gold_agreement.value == pytest.approx(5 / 6)
    # ...but the gold-tuned tau=3 collapses on the fresh naturalistic held-out,
    # while the untuned tau=1 holds -> a POSITIVE gap for the selected config only.
    assert default_gap.holdout_agreement.value == pytest.approx(1.0)
    assert selected_gap.holdout_agreement.value == pytest.approx(0.6)
    assert selected_gap.gap == pytest.approx(5 / 6 - 0.6, abs=1e-9)
    assert selected_gap.gap > 0  # the overfit signature
    assert default_gap.gap <= 0  # the untuned config does not overfit here
    assert selected_gap.gap > default_gap.gap  # the robust ordering


def test_audit_reports_default_and_selected_gaps():
    audit = _audit()
    assert audit.n_holdout_cases == 15
    names = {g.config_name for g in audit.gaps}
    assert names == {"safety_tau=1", "safety_tau=3"}
    selected = next(g for g in audit.gaps if g.config_name == "safety_tau=3")
    assert selected.gap > 0


# --------------------------------------------------------------------------- #
# (c) Sample-k saturation curve (FIXED gold; sample-k only).
# --------------------------------------------------------------------------- #
def test_deterministic_judge_saturates_at_k1():
    cases, rubric, rules = _load()
    curve = sample_k_saturation_curve(
        heuristic_status_sampler(rubric, rules), cases, k_values=(1, 3, 5, 7, 9)
    )
    assert curve.is_deterministic is True
    assert curve.saturated_at_k == 1
    # Flat curve: identical agreement and unanimous modal fraction at every k.
    assert all(p.agreement.value == pytest.approx(2 / 3) for p in curve.points)
    assert all(p.mean_modal_fraction == pytest.approx(1.0) for p in curve.points)
    assert all(p.majority_changed_from_prev == 0 for p in curve.points)


def test_saturation_x_axis_is_sample_k_not_gold_size():
    # The honesty guard: the curve varies k (resamples), and the agreement
    # DENOMINATOR (decided gold cells, n) is CONSTANT across every k. It is a
    # sample-k curve, never a gold-size asymptote.
    cases, rubric, rules = _load()
    curve = sample_k_saturation_curve(
        heuristic_status_sampler(rubric, rules), cases, k_values=(1, 3, 5)
    )
    assert [p.k for p in curve.points] == [1, 3, 5]
    denominators = {p.agreement.denominator for p in curve.points}
    assert len(denominators) == 1  # n never grows; only k moves


def test_stochastic_mock_judge_traces_a_real_curve():
    cases, rubric, rules = _load()
    truth = {c.id: c.gold for c in cases}
    rng = random.Random(20260619)

    def noisy(case):
        base = truth[case.id]
        if base is CriterionStatus.ABSTAIN:
            return base
        if rng.random() < 0.3:  # 30% per-sample flip — simulated judge jitter
            return CriterionStatus.PASS if base is CriterionStatus.FAIL else CriterionStatus.FAIL
        return base

    curve = sample_k_saturation_curve(noisy, cases, k_values=(1, 3, 5, 7, 9))
    assert curve.is_deterministic is False
    # A jittery judge is NOT unanimous once resampled (modal fraction drops below 1).
    assert any(p.mean_modal_fraction < 1.0 for p in curve.points if p.k > 1)
    # ...and its majority verdict moves at small k (the un-saturated regime).
    assert any(p.majority_changed_from_prev > 0 for p in curve.points)


def test_saturation_rejects_bad_k_values():
    cases, _r, _rl = _load()
    with pytest.raises(ValueError):
        sample_k_saturation_curve(lambda c: CriterionStatus.PASS, cases, k_values=())
    with pytest.raises(ValueError):
        sample_k_saturation_curve(lambda c: CriterionStatus.PASS, cases, k_values=(0,))


# --------------------------------------------------------------------------- #
# (d) Capability-gap framing — methodology, no fabricated capability number.
# --------------------------------------------------------------------------- #
def test_capability_gap_note_is_framing_not_a_fabricated_number():
    note = offline_capability_gap_note()
    assert note.capability_bounded is True
    assert "2505.20162" in note.reference
    assert "capability gap" in note.framing.lower()
    assert "floor" in note.framing.lower()
    # The model carries NO numeric capability fields to invent (bool flags like
    # capability_bounded are not numbers — and bool is a subclass of int, so it
    # must be excluded explicitly).
    dumped = note.model_dump()
    assert not any(
        isinstance(v, (int, float)) and not isinstance(v, bool)
        for v in dumped.values()
    )


# --------------------------------------------------------------------------- #
# Assembly, serialization, and the existing surface.
# --------------------------------------------------------------------------- #
def test_audit_is_deterministic_and_roundtrips():
    a = _audit()
    b = _audit()
    assert a.model_dump_json() == b.model_dump_json()
    again = JudgeOverfitAudit.model_validate_json(a.model_dump_json())
    assert again.selection.selected.name == a.selection.selected.name
    assert again.cascade.alpha == a.cascade.alpha


def test_existing_meta_eval_unaffected():
    cases, rubric, rules = _load()
    r = evaluate_gold(cases, rubric, rules)
    assert (r.metrics.tp, r.metrics.fp, r.metrics.fn, r.metrics.tn) == (3, 2, 2, 5)
    assert r.n_scored == 12 and r.n_abstained == 1


# --------------------------------------------------------------------------- #
# Cascade telemetry — the suite-wide {alpha, disagreement_rate,
# lossless_violations} contract at zero model spend.
# --------------------------------------------------------------------------- #
def test_gold_cascade_boundary_is_exact_and_zero_spend():
    cases, rubric, rules = _load()
    b = gold_cascade_boundary(cases, rubric, rules)
    assert b.measured is True  # both tiers deterministic -> exact, no key needed
    # 13 gold cells; the heuristic escalates (abstains) on exactly one.
    assert (b.n_total, b.n_resolved, b.n_escalated, b.n_co_judged) == (13, 12, 1, 12)
    assert b.alpha == pytest.approx(12 / 13)  # cheap tier resolves 12/13 without escalating
    assert b.disagreement_rate == pytest.approx(1 / 3)  # 4 of 12 co-judged differ
    assert b.lossless_violations == 4
    assert b.lossless_resolution_rate == pytest.approx(8 / 13)
    # Regime + locus are labeled (deterministic/provable, residual at the turn).
    assert "model-free" in b.regime and "provable" in b.regime
    assert b.locus == "turn"


def test_lossless_violations_match_the_disagreement_identity():
    # With no confidence-based escalation the cheap tier decides whenever it has a
    # rule + a reply, so every wrong resolution is a lossless violation: the count
    # equals disagreement_rate * n_co_judged exactly (the documented contract).
    cases, rubric, rules = _load()
    b = gold_cascade_boundary(cases, rubric, rules)
    assert b.lossless_violations == round(b.disagreement_rate * b.n_co_judged)


def test_llm_boundary_is_honest_not_fabricated():
    # The heuristic -> LLM boundary is real but unmeasurable offline; it must be
    # emitted with measured=False and NULL rates, never an invented number.
    cases, rubric, rules = _load()
    tele = gold_cascade_telemetry(cases, rubric, rules)
    assert len(tele.boundaries) == 2
    llm = next(b for b in tele.boundaries if not b.measured)
    assert llm.alpha is None and llm.disagreement_rate is None
    assert llm.lossless_violations == 0
    assert "model-based residual" in llm.regime
    assert "ANTHROPIC_API_KEY" in llm.note


def test_cascade_boundary_rejects_inconsistent_counts():
    # The count invariants are enforced by the model, not just by construction.
    with pytest.raises(ValidationError):
        CascadeBoundary(
            name="x", cheap_tier="c", expensive_tier="e", regime="r", locus="turn",
            measured=True, n_total=10, n_resolved=4, n_escalated=4,  # 4+4 != 10
            n_co_judged=4, lossless_violations=0,
        )
    with pytest.raises(ValidationError):
        CascadeBoundary(
            name="x", cheap_tier="c", expensive_tier="e", regime="r", locus="turn",
            measured=True, n_total=10, n_resolved=6, n_escalated=4,
            n_co_judged=4, lossless_violations=5,  # > n_co_judged
        )


def test_measured_sentence_is_recruiter_legible_and_measured():
    cases, rubric, rules = _load()
    tele = gold_cascade_telemetry(cases, rubric, rules)
    s = tele.measured_sentence
    # The single recruiter-legible sentence carries the MEASURED numbers, not prose.
    assert "92%" in s  # alpha
    assert "62%" in s  # lossless resolution
    assert "33%" in s  # disagreement
    assert "4 measured lossless-violations" in s
    assert "frozen gold" in s


def test_wilson_disagreement_estimate_has_honest_small_n_interval():
    cases, rubric, rules = _load()
    b = gold_cascade_boundary(cases, rubric, rules)
    est = wilson_disagreement_estimate(b)
    assert est.numerator == 4 and est.denominator == 12
    assert est.value == pytest.approx(1 / 3)
    # A Wilson interval on n=12 is honestly wide — it brackets the point estimate.
    assert est.lower < est.value < est.upper


def test_load_and_measure_matches_in_memory():
    cases, rubric, rules = _load()
    direct = gold_cascade_telemetry(cases, rubric, rules)
    loaded = load_and_measure(GOLD, RUBRIC)
    assert loaded.measured_sentence == direct.measured_sentence
    assert loaded.boundaries[0].alpha == direct.boundaries[0].alpha


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def _build_local_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="test")
    sub = p.add_subparsers(dest="cmd", required=True)
    overfit.register_subparser(sub)
    return p


def test_cli_overfit_audit_json_and_human(capsys):
    parser = _build_local_parser()
    args = parser.parse_args(
        ["overfit-audit", "--gold", str(GOLD), "--rubric", str(RUBRIC), "--json"]
    )
    assert args._func(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["selection"]["selected"]["name"] == "safety_tau=3"
    assert payload["selection"]["n_configs"] == 4
    assert payload["complexity"]["scalar"] == 29.0

    args2 = parser.parse_args(
        ["overfit-audit", "--gold", str(GOLD), "--rubric", str(RUBRIC)]
    )
    assert args2._func(args2) == 0
    err = capsys.readouterr().err
    assert "Bonferroni" in err
    assert "overfit signature" in err
    assert "capability gap" in err.lower()


def test_cli_corrected_recall_gate(capsys):
    parser = _build_local_parser()
    base = ["overfit-audit", "--gold", str(GOLD), "--rubric", str(RUBRIC)]
    # The corrected recall floor is ~0.29; a floor above it must fail the gate.
    high = parser.parse_args(base + ["--min-corrected-recall-lower", "0.5"])
    assert high._func(high) == 1
    assert "GATE FAILED" in capsys.readouterr().err
    # A floor below it passes.
    low = parser.parse_args(base + ["--min-corrected-recall-lower", "0.2"])
    assert low._func(low) == 0


def test_cli_clean_error_on_missing_gold(capsys):
    parser = _build_local_parser()
    args = parser.parse_args(
        ["overfit-audit", "--gold", "/nonexistent/gold.jsonl", "--rubric", str(RUBRIC)]
    )
    assert args._func(args) == 2
    assert "error" in capsys.readouterr().err.lower()
