"""Tests for the detection-quality metrics (the meta-eval surface).

The point and interval values below are hand-computed from the Wilson
score formula so the test pins the math, not just the code's own output.
"""
from __future__ import annotations

import math

import pytest

from coehoorn.metrics import (
    DetectionMetrics,
    ProportionEstimate,
    cohens_kappa,
    metrics_from_comparison,
    wilson_interval,
)


def _approx(a: float, b: float, tol: float = 1e-4) -> bool:
    return math.isclose(a, b, abs_tol=tol)


class TestWilsonInterval:
    def test_n_zero_is_maximally_uncertain(self):
        assert wilson_interval(0, 0) == (0.0, 1.0)

    def test_one_of_one(self):
        lo, hi = wilson_interval(1, 1)
        assert _approx(lo, 0.2065)
        assert hi == 1.0

    def test_zero_of_ten(self):
        lo, hi = wilson_interval(0, 10)
        assert lo == 0.0
        assert _approx(hi, 0.2775)

    def test_half(self):
        lo, hi = wilson_interval(5, 10)
        # symmetric around 0.5
        assert _approx((lo + hi) / 2, 0.5)
        assert _approx(lo, 0.2366)
        assert _approx(hi, 0.7634)

    def test_interval_within_unit(self):
        for s, n in [(0, 1), (3, 7), (7, 7), (33, 100)]:
            lo, hi = wilson_interval(s, n)
            assert 0.0 <= lo <= hi <= 1.0

    def test_rejects_bad_counts(self):
        with pytest.raises(ValueError):
            wilson_interval(5, 3)  # successes > n
        with pytest.raises(ValueError):
            wilson_interval(-1, 3)


class TestProportionEstimate:
    def test_defined(self):
        est = ProportionEstimate.from_counts(3, 4)
        assert est.value == 0.75
        assert est.numerator == 3
        assert est.denominator == 4
        assert 0.0 <= est.lower <= 0.75 <= est.upper <= 1.0

    def test_undefined_when_no_denominator(self):
        est = ProportionEstimate.from_counts(0, 0)
        assert est.value is None
        assert est.lower == 0.0
        assert est.upper == 1.0


class TestDetectionMetrics:
    def test_perfect(self):
        m = DetectionMetrics.from_counts(tp=3, fp=0, fn=0)
        assert m.precision.value == 1.0
        assert m.recall.value == 1.0
        assert m.f1 == 1.0
        assert m.support == 3

    def test_precision_recall_split(self):
        # tp=2, fp=1, fn=2 -> precision 2/3, recall 2/4=0.5
        m = DetectionMetrics.from_counts(tp=2, fp=1, fn=2)
        assert _approx(m.precision.value, 2 / 3)
        assert _approx(m.recall.value, 0.5)
        assert _approx(m.f1, 2 * (2 / 3 * 0.5) / (2 / 3 + 0.5))
        assert m.support == 4

    def test_no_predictions_no_actuals(self):
        m = DetectionMetrics.from_counts(tp=0, fp=0, fn=0)
        assert m.precision.value is None
        assert m.recall.value is None
        assert m.f1 is None

    def test_recall_zero_when_all_missed(self):
        m = DetectionMetrics.from_counts(tp=0, fp=0, fn=4)
        assert m.recall.value == 0.0
        assert m.precision.value is None  # nothing predicted
        assert m.f1 is None


class TestMetricsFromComparison:
    def _diff(self):
        # Shape mirrors aggregator.compare_to_expected output.
        return {
            "p02": {
                "expected_failures": ["safe_handling_of_self_harm"],
                "actual_failures": ["safe_handling_of_self_harm"],
                "true_positives": ["safe_handling_of_self_harm"],
                "false_positives": [],
                "false_negatives": [],
                "match": True,
            },
            "p03": {
                "expected_failures": ["no_fabricated_legal_citations"],
                "actual_failures": [],
                "true_positives": [],
                "false_positives": [],
                "false_negatives": ["no_fabricated_legal_citations"],
                "match": False,
            },
            "p04": {
                "expected_failures": [],
                "actual_failures": ["no_fabricated_legal_citations"],
                "true_positives": [],
                "false_positives": ["no_fabricated_legal_citations"],
                "false_negatives": [],
                "match": False,
            },
        }

    def test_overall_counts(self):
        report = metrics_from_comparison(self._diff())
        assert report.overall.tp == 1
        assert report.overall.fp == 1
        assert report.overall.fn == 1
        assert _approx(report.overall.precision.value, 0.5)
        assert _approx(report.overall.recall.value, 0.5)

    def test_per_criterion_breakdown(self):
        report = metrics_from_comparison(self._diff())
        assert set(report.per_criterion) == {
            "safe_handling_of_self_harm",
            "no_fabricated_legal_citations",
        }
        sh = report.per_criterion["safe_handling_of_self_harm"]
        assert (sh.tp, sh.fp, sh.fn) == (1, 0, 0)
        legal = report.per_criterion["no_fabricated_legal_citations"]
        assert (legal.tp, legal.fp, legal.fn) == (0, 1, 1)

    def test_round_trips_through_json(self):
        report = metrics_from_comparison(self._diff())
        dumped = report.model_dump_json()
        from coehoorn.metrics import MetricsReport

        again = MetricsReport.model_validate_json(dumped)
        assert again.overall.tp == report.overall.tp


class TestSpecificityAndBalancedAccuracy:
    def test_specificity_over_actual_negatives(self):
        m = DetectionMetrics.from_counts(tp=1, fp=1, fn=0, tn=3)
        # specificity = tn / (tn + fp) = 3/4
        assert _approx(m.specificity.value, 0.75)

    def test_balanced_accuracy_is_mean_of_recall_and_specificity(self):
        m = DetectionMetrics.from_counts(tp=3, fp=2, fn=2, tn=5)
        assert _approx(m.recall.value, 0.6)
        assert _approx(m.specificity.value, 5 / 7)
        assert _approx(m.balanced_accuracy, (0.6 + 5 / 7) / 2)

    def test_balanced_accuracy_none_when_no_negatives(self):
        m = DetectionMetrics.from_counts(tp=3, fp=0, fn=0, tn=0)
        assert m.specificity.value is None
        assert m.balanced_accuracy is None


class TestCohensKappa:
    def test_perfect_agreement_is_one(self):
        # tp=5, tn=5, no errors -> observed agreement 1, kappa 1
        assert _approx(cohens_kappa(5, 0, 0, 5), 1.0)

    def test_known_value(self):
        # tp=3, fp=2, fn=2, tn=5 -> kappa computed by hand below
        # p_o = 8/12, p_e = (5/12)^2 + (7/12)^2 = 0.51388..., kappa = 0.31426
        assert _approx(cohens_kappa(3, 2, 2, 5), 0.31426, tol=1e-4)

    def test_undefined_when_one_class_absent(self):
        # No negatives at all -> chance agreement total -> kappa undefined
        assert cohens_kappa(4, 0, 0, 0) is None

    def test_empty_is_none(self):
        assert cohens_kappa(0, 0, 0, 0) is None


class TestMetricsAbstention:
    def test_abstained_counted_and_excluded(self):
        diff = {
            "p0": {
                "true_positives": ["a"],
                "false_positives": [],
                "false_negatives": [],
                "true_negatives": ["b"],
                "abstained": ["c"],
            }
        }
        report = metrics_from_comparison(diff)
        assert report.abstained == 1
        # one abstained of three cells -> 1/3
        assert _approx(report.abstention_rate, 1 / 3)
        assert report.overall.tp == 1
        assert report.overall.tn == 1
        assert "c" not in report.per_criterion  # abstained cell isn't scored
