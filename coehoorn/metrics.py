"""Detection-quality metrics — the meta-evaluation surface.

Coehoorn judges agents. This module judges Coehoorn's judge. Given the
true-positive / false-positive / false-negative counts produced by
``aggregator.compare_to_expected`` (judge verdicts vs. a hand-labeled
ground-truth fixture), it computes precision, recall, and F1 — each point
estimate paired with a Wilson score confidence interval.

The Wilson interval is the honest choice here: the
ground-truth set is small and one of the seeded failure modes is
stochastic (~30% per probe), so a bare "recall = 0.67" overclaims a
precision the sample size does not support. The interval says how much
the number can be trusted. A harness that demands cited, hedged verdicts
from agents-under-test owes the same rigor to its own scorecard.
"""
from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Two-sided 95% standard-normal quantile. Spelled out rather than imported
# from a stats package so the core stays dependency-free.
Z_95: float = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion.

    Returns ``(lower, upper)`` clamped to ``[0, 1]``. With ``n == 0`` there
    is no information, so the maximally-uncertain ``(0.0, 1.0)`` is returned
    rather than raising — callers treat the point estimate as undefined.
    """
    if n < 0 or successes < 0:
        raise ValueError("successes and n must be non-negative")
    if successes > n:
        raise ValueError(f"successes ({successes}) cannot exceed n ({n})")
    if n == 0:
        return (0.0, 1.0)

    p_hat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p_hat * (1 - p_hat) / n + z2 / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


class ProportionEstimate(BaseModel):
    """A point estimate of a proportion with its Wilson 95% interval.

    ``value`` is ``None`` when the denominator is zero (the proportion is
    undefined — e.g. precision when nothing was predicted). In that case the
    interval is the uninformative ``[0, 1]``.
    """

    model_config = ConfigDict(extra="forbid")

    value: float | None = Field(default=None, ge=0, le=1)
    lower: float = Field(ge=0, le=1)
    upper: float = Field(ge=0, le=1)
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> ProportionEstimate:
        if self.lower > self.upper:
            raise ValueError("interval lower must be <= upper")
        if self.numerator > self.denominator:
            raise ValueError("numerator cannot exceed denominator")
        return self

    @classmethod
    def from_counts(cls, numerator: int, denominator: int) -> ProportionEstimate:
        if denominator == 0:
            return cls(value=None, lower=0.0, upper=1.0, numerator=0, denominator=0)
        lower, upper = wilson_interval(numerator, denominator)
        return cls(
            value=numerator / denominator,
            lower=lower,
            upper=upper,
            numerator=numerator,
            denominator=denominator,
        )


class DetectionMetrics(BaseModel):
    """The confusion matrix for one detector (overall or per-criterion) and
    every scalar derived from it, each carrying its interval where it is a
    proportion.

    Precision is over predicted positives (``tp + fp``); recall over actual
    positives (``tp + fn``); specificity over actual negatives (``tn + fp``).
    ``balanced_accuracy`` is the mean of recall and specificity — the honest
    headline when the classes are lopsided. ``cohens_kappa`` discounts the
    agreement a coin-flip would reach by chance; it is ``None`` when one class
    is empty (kappa is undefined there). ``support`` is the ground-truth
    positive count this row was scored against.
    """

    model_config = ConfigDict(extra="forbid")

    tp: int = Field(ge=0)
    fp: int = Field(ge=0)
    fn: int = Field(ge=0)
    tn: int = Field(ge=0)
    precision: ProportionEstimate
    recall: ProportionEstimate
    specificity: ProportionEstimate
    f1: float | None = Field(default=None, ge=0, le=1)
    balanced_accuracy: float | None = Field(default=None, ge=0, le=1)
    cohens_kappa: float | None = Field(default=None, ge=-1, le=1)
    support: int = Field(ge=0)

    @classmethod
    def from_counts(
        cls, *, tp: int, fp: int, fn: int, tn: int = 0
    ) -> DetectionMetrics:
        precision = ProportionEstimate.from_counts(tp, tp + fp)
        recall = ProportionEstimate.from_counts(tp, tp + fn)
        specificity = ProportionEstimate.from_counts(tn, tn + fp)
        return cls(
            tp=tp,
            fp=fp,
            fn=fn,
            tn=tn,
            precision=precision,
            recall=recall,
            specificity=specificity,
            f1=_f1(precision.value, recall.value),
            balanced_accuracy=_mean(recall.value, specificity.value),
            cohens_kappa=cohens_kappa(tp, fp, fn, tn),
            support=tp + fn,
        )


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or precision + recall == 0:
        return None
    return 2 * precision * recall / (precision + recall)


def _mean(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return (a + b) / 2


def cohens_kappa(tp: int, fp: int, fn: int, tn: int) -> float | None:
    """Cohen's kappa for a 2x2 fail/pass confusion matrix.

    Returns ``None`` when the matrix is empty or one outcome class is absent
    (chance agreement is total, so kappa is undefined rather than 0).
    """
    total = tp + fp + fn + tn
    if total == 0:
        return None
    p_observed = (tp + tn) / total
    p_both_fail = ((tp + fp) / total) * ((tp + fn) / total)
    p_both_pass = ((fn + tn) / total) * ((fp + tn) / total)
    p_expected = p_both_fail + p_both_pass
    if p_expected >= 1.0:
        return None
    return (p_observed - p_expected) / (1 - p_expected)


class MetricsReport(BaseModel):
    """Meta-eval scorecard: how well the judge matched the ground truth,
    overall and per criterion, with the abstention rate reported alongside
    (abstained cells are excluded from the matrix, never scored as misses)."""

    model_config = ConfigDict(extra="forbid")

    overall: DetectionMetrics
    per_criterion: dict[str, DetectionMetrics]
    abstained: int = Field(default=0, ge=0)
    abstention_rate: float | None = Field(default=None, ge=0, le=1)


# Diff list-key -> confusion-matrix counter. Fixed structural data.
_CELL_KEYS = {
    "true_positives": "tp",
    "false_positives": "fp",
    "false_negatives": "fn",
    "true_negatives": "tn",
}


def metrics_from_comparison(diff: dict[str, dict]) -> MetricsReport:
    """Build a :class:`MetricsReport` from ``compare_to_expected`` output.

    ``diff`` is ``{persona_id: {true_positives, false_positives,
    false_negatives, true_negatives, abstained, ...}}`` where each value is a
    list of criterion ids. Overall counts sum across personas; per-criterion
    counts attribute each cell to the criterion it concerns.
    """
    totals = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    abstained = 0
    per: dict[str, dict[str, int]] = {}

    def _bump(cid: str, key: str) -> None:
        per.setdefault(cid, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})[key] += 1

    for entry in diff.values():
        for list_key, count_key in _CELL_KEYS.items():
            for cid in entry.get(list_key, []):
                totals[count_key] += 1
                _bump(cid, count_key)
        abstained += len(entry.get("abstained", []))

    per_criterion = {
        cid: DetectionMetrics.from_counts(
            tp=c["tp"], fp=c["fp"], fn=c["fn"], tn=c["tn"]
        )
        for cid, c in sorted(per.items())
    }
    scored = sum(totals.values())
    abstention_rate = abstained / (scored + abstained) if (scored + abstained) else None
    return MetricsReport(
        overall=DetectionMetrics.from_counts(**totals),
        per_criterion=per_criterion,
        abstained=abstained,
        abstention_rate=abstention_rate,
    )
