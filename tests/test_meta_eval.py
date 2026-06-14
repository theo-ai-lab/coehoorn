"""Meta-eval: the heuristic judge scored against the frozen gold set.

These pin the exact confusion matrix on a deterministic fixture (heuristic
judge + fixed gold => exact numbers, never flaky) and enforce the honest-
reporting discipline: the regression gate is the Wilson LOWER bound, not the
point estimate, with n stated inline.
"""
from __future__ import annotations

import math
from pathlib import Path

from coehoorn.meta_eval import evaluate_gold, load_gold_cases
from coehoorn.rubric_parser import parse_rubric_file

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD = REPO_ROOT / "tests" / "gold" / "judge_gold.jsonl"
RUBRIC = REPO_ROOT / "examples" / "rubric_coach.yaml"

# Committed regression floors. The eval is deterministic so the point values
# are exact, but the GATE is the interval floor — the discipline Coehoorn
# preaches, applied to its own CI. n is stated so the floor is interpretable.
RECALL_LOWER_FLOOR = 0.20  # n_pos = 5
PRECISION_LOWER_FLOOR = 0.20  # n_pred_pos = 5


def _result():
    rubric, rules = parse_rubric_file(RUBRIC)
    cases = load_gold_cases(GOLD)
    return evaluate_gold(cases, rubric, rules)


def test_gold_confusion_matrix_is_exact():
    m = _result().metrics
    assert (m.tp, m.fp, m.fn, m.tn) == (3, 2, 2, 5)


def test_gold_abstention_is_excluded_not_scored():
    r = _result()
    assert r.n_abstained == 1  # the tone_is_supportive cell
    assert r.n_scored == 12


def test_gold_point_estimates():
    m = _result().metrics
    assert math.isclose(m.precision.value, 0.6, abs_tol=1e-9)
    assert math.isclose(m.recall.value, 0.6, abs_tol=1e-9)
    assert math.isclose(m.specificity.value, 5 / 7, abs_tol=1e-9)
    assert m.balanced_accuracy is not None
    assert math.isclose(m.balanced_accuracy, (0.6 + 5 / 7) / 2, abs_tol=1e-9)
    assert m.cohens_kappa is not None and m.cohens_kappa > 0


def test_heuristic_beats_both_baselines_on_balanced_accuracy():
    r = _result()
    # Both dumb baselines sit at 0.5 balanced accuracy by construction.
    assert math.isclose(r.baseline_always_breach.balanced_accuracy, 0.5, abs_tol=1e-9)
    assert math.isclose(r.baseline_always_hold.balanced_accuracy, 0.5, abs_tol=1e-9)
    assert r.metrics.balanced_accuracy > r.baseline_always_breach.balanced_accuracy
    assert r.metrics.balanced_accuracy > r.baseline_always_hold.balanced_accuracy


def test_ci_floor_gate_holds():
    # The gate: lower Wilson bound of recall and precision must clear the
    # committed floors. This catches a real regression (a judge that stops
    # detecting breaches) without flaking on small-n noise.
    m = _result().metrics
    assert m.recall.lower >= RECALL_LOWER_FLOOR, (
        f"recall lower bound {m.recall.lower:.3f} (n={m.recall.denominator}) "
        f"fell below floor {RECALL_LOWER_FLOOR}"
    )
    assert m.precision.lower >= PRECISION_LOWER_FLOOR, (
        f"precision lower bound {m.precision.lower:.3f} "
        f"(n={m.precision.denominator}) fell below floor {PRECISION_LOWER_FLOOR}"
    )


def test_gold_eval_serializes():
    r = _result()
    from coehoorn.meta_eval import GoldEvalResult

    again = GoldEvalResult.model_validate_json(r.model_dump_json())
    assert again.metrics.tp == r.metrics.tp
