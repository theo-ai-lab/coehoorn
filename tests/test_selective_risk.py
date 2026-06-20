"""Selective-risk certificate — deterministic, offline, keyless tests.

Pins the distribution-free bound primitives, the conjectured certification siege,
the heuristic and (offline mock-)jury certificates, the convergence framing, the
effective-vote backing, and the CLI. The live LLM judge/jury is never called —
only its honest key-gating is asserted.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from coehoorn import selective_risk
from coehoorn.distill import conjectured_residual_siege, mock_jury
from coehoorn.meta_eval import load_gold_cases
from coehoorn.rubric_parser import parse_rubric_file
from coehoorn.schemas import CriterionStatus
from coehoorn.selective_risk import (
    SelectiveRiskCertificate,
    SelectiveRiskReport,
    certify_selective_risk,
    conjectured_certification_siege,
    heuristic_certification_sampler,
    hoeffding_upper_bound,
    hoeffding_width,
    jury_consensus_sampler,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD = REPO_ROOT / "tests" / "gold" / "judge_gold.jsonl"
RUBRIC = REPO_ROOT / "examples" / "rubric_coach.yaml"


def _load():
    rubric, rules = parse_rubric_file(RUBRIC)
    cases = load_gold_cases(GOLD)
    return cases, rubric, rules


def _heuristic_report():
    cases, rubric, rules = _load()
    siege = conjectured_certification_siege(cases, rubric, rules)
    sampler = heuristic_certification_sampler(rubric, rules)
    return certify_selective_risk(sampler, siege, judge_name="heuristic")


# --------------------------------------------------------------------------- #
# Distribution-free bound primitives.
# --------------------------------------------------------------------------- #
def test_hoeffding_width_matches_the_closed_form_and_shrinks():
    # sqrt(ln(1/delta) / (2n))
    assert hoeffding_width(50, 0.05) == pytest.approx(
        math.sqrt(math.log(1 / 0.05) / (2 * 50))
    )
    assert hoeffding_width(0) == 1.0  # no information
    assert hoeffding_width(10) > hoeffding_width(100)  # monotone in n


def test_hoeffding_width_converges_at_one_over_sqrt_n():
    # Quadrupling n halves the width (the O(1/sqrt(N)) convergence rate).
    assert hoeffding_width(100) / hoeffding_width(400) == pytest.approx(2.0, abs=1e-9)


def test_hoeffding_upper_bound_is_point_plus_width_and_clamped():
    assert hoeffding_upper_bound(2, 17, 0.05) == pytest.approx(
        2 / 17 + hoeffding_width(17, 0.05)
    )
    assert hoeffding_upper_bound(0, 0) == 1.0  # no information -> vacuous
    assert hoeffding_upper_bound(10, 10, 0.05) == 1.0  # clamped to 1
    with pytest.raises(ValueError):
        hoeffding_upper_bound(5, 3)  # errors > n


# --------------------------------------------------------------------------- #
# The conjectured certification siege.
# --------------------------------------------------------------------------- #
def test_certification_siege_is_conjectured_and_mixes_decided_and_abstained():
    cases, rubric, rules = _load()
    siege = conjectured_certification_siege(cases, rubric, rules)
    # 15 clean self-harm + 2 near-miss + 12 tone = 29 conjectured cells.
    assert len(siege) == 29
    crits = {c.criterion_id for c in siege}
    assert crits == {"safe_handling_of_self_harm", "tone_is_supportive"}
    # The near-miss cells are true breaches the heuristic will wrongly pass.
    nearmiss = [c for c in siege if c.id.startswith("cert-nearmiss")]
    assert len(nearmiss) == 2 and all(c.gold is CriterionStatus.FAIL for c in nearmiss)


# --------------------------------------------------------------------------- #
# The heuristic certificate (the keyless headline).
# --------------------------------------------------------------------------- #
def test_heuristic_certificate_has_selective_coverage_and_nonzero_risk():
    c = _heuristic_report().certificate
    # The judge abstains on the 12 tone cells (no offline rule) -> coverage < 1.
    assert c.n_labeled == 29 and c.n_decided == 17 and c.n_abstained_by_judge == 12
    assert c.coverage == pytest.approx(17 / 29)
    # It decides the 17 self-harm cells and errs on the 2 near-misses.
    assert c.n_errors == 2
    assert c.empirical_selective_risk.value == pytest.approx(2 / 17)
    assert c.effective_votes is None  # single judge, not a jury


def test_heuristic_certificate_bounds_are_distribution_free_and_loose_at_small_n():
    c = _heuristic_report().certificate
    assert c.hoeffding_upper == pytest.approx(2 / 17 + hoeffding_width(17, 0.05))
    # The Hoeffding (finite-sample, distribution-free) bound is >= the point
    # estimate and, at this tiny n, conservative vs the asymptotic Wilson upper.
    assert c.hoeffding_upper >= c.empirical_selective_risk.value
    assert c.hoeffding_upper >= c.wilson_upper
    # The width is large at n=17 — the honest signal that this is not a tight number.
    assert c.hoeffding_width > 0.25
    assert c.distribution_free_conditional is True
    assert "2509.12527" in c.reference
    assert "converging" in c.honesty.lower() or "converges" in c.honesty.lower()


def test_certificate_convergence_curve_demonstrates_one_over_sqrt_n():
    rep = _heuristic_report()
    pts = {p.n: p.hoeffding_width for p in rep.convergence}
    assert 8 in pts and 512 in pts
    # Widths strictly shrink with N and quarter-N halves the width.
    ns = sorted(pts)
    assert all(pts[a] > pts[b] for a, b in zip(ns, ns[1:]))
    assert pts[64] / pts[256] == pytest.approx(2.0, abs=1e-9)


def test_certificate_is_deterministic_and_roundtrips():
    a = _heuristic_report()
    b = _heuristic_report()
    assert a.model_dump_json() == b.model_dump_json()
    again = SelectiveRiskReport.model_validate_json(a.model_dump_json())
    assert again.certificate.hoeffding_upper == pytest.approx(a.certificate.hoeffding_upper)


def test_certificate_count_invariant_is_enforced():
    c = _heuristic_report().certificate
    bad = c.model_dump()
    bad["n_errors"] = c.n_decided + 1  # errors cannot exceed decided
    with pytest.raises(ValidationError):
        SelectiveRiskCertificate.model_validate(bad)


# --------------------------------------------------------------------------- #
# The jury certificate — effective votes, not member count.
# --------------------------------------------------------------------------- #
def test_jury_certificate_reports_effective_votes_below_member_count():
    deriv, hold = conjectured_residual_siege()
    siege = deriv + hold
    sampler, eff = jury_consensus_sampler(mock_jury(), siege)
    rep = certify_selective_risk(
        sampler, siege, judge_name="mock jury", effective=eff
    )
    c = rep.certificate
    assert c.effective_votes is not None
    assert c.effective_votes.n_members == 4
    # The correlation correction: fewer effective votes than members.
    assert c.effective_votes.effective_votes < 4
    assert c.effective_votes.effective_votes >= 1
    # The jury decides every tone cell (coverage 1.0) and is bounded honestly.
    assert c.coverage == pytest.approx(1.0)
    assert 0.0 <= c.hoeffding_upper <= 1.0


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="test")
    sub = p.add_subparsers(dest="cmd", required=True)
    selective_risk.register_subparser(sub)
    return p


def test_cli_selective_risk_json_and_human(capsys):
    p = _parser()
    args = p.parse_args(
        ["selective-risk", "--gold", str(GOLD), "--rubric", str(RUBRIC), "--json"]
    )
    assert args._func(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["certificate"]["n_decided"] == 17
    assert payload["certificate"]["n_errors"] == 2
    assert payload["certificate"]["hoeffding_upper"] > payload["certificate"][
        "empirical_selective_risk"
    ]["value"]
    assert len(payload["convergence"]) == 8

    args2 = p.parse_args(
        ["selective-risk", "--gold", str(GOLD), "--rubric", str(RUBRIC)]
    )
    assert args2._func(args2) == 0
    err = capsys.readouterr().err
    assert "coverage" in err.lower()
    assert "O(1/sqrt(N))" in err
    assert "2509.12527" in err


def test_cli_selective_risk_mock_jury_reports_effective_votes(capsys):
    p = _parser()
    args = p.parse_args(
        ["selective-risk", "--gold", str(GOLD), "--rubric", str(RUBRIC),
         "--judge", "mock-jury"]
    )
    assert args._func(args) == 0
    err = capsys.readouterr().err
    assert "EFFECTIVE votes" in err
    assert "NOT member count" in err


def test_cli_selective_risk_upper_bound_gate(capsys):
    p = _parser()
    base = ["selective-risk", "--gold", str(GOLD), "--rubric", str(RUBRIC)]
    # The Hoeffding upper bound is ~0.41; a ceiling below it must fail the gate.
    low = p.parse_args(base + ["--max-risk-upper", "0.2"])
    assert low._func(low) == 1
    assert "GATE FAILED" in capsys.readouterr().err
    # A ceiling above it passes (gating on the upper bound, not the point estimate).
    high = p.parse_args(base + ["--max-risk-upper", "0.6"])
    assert high._func(high) == 0


def test_cli_selective_risk_llm_jury_without_key_exits_two(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = _parser()
    args = p.parse_args(
        ["selective-risk", "--gold", str(GOLD), "--rubric", str(RUBRIC),
         "--judge", "llm-jury"]
    )
    assert args._func(args) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_cli_selective_risk_clean_error_on_missing_gold(capsys):
    p = _parser()
    args = p.parse_args(
        ["selective-risk", "--gold", "/nonexistent/gold.jsonl", "--rubric", str(RUBRIC)]
    )
    assert args._func(args) == 2
    assert "error" in capsys.readouterr().err.lower()
