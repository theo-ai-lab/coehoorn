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


def normal_ppf(p: float) -> float:
    """Inverse standard-normal CDF (the quantile / probit function).

    Pure stdlib (Acklam's rational approximation, max abs error ~1.2e-9 over the
    open unit interval) so the core stays SciPy-free — the same discipline as the
    erfc-based survival function in :mod:`coehoorn.metamorphic`. Used to derive a
    Bonferroni-adjusted z for a multiplicity-corrected Wilson bound (a tuned
    config's lower bound must use a wider quantile than the naive 95%).

    Raises ``ValueError`` outside the open interval ``(0, 1)`` — ``+/-inf`` is not
    a usable z for a confidence quantile.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"normal_ppf requires 0 < p < 1; got {p}")
    # Acklam's algorithm: rational approximations on three regions.
    a = (
        -3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
        1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
        6.680131188771972e01, -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
        -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
        3.754408661907416e00,
    )
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    return x


def bonferroni_z(alpha: float = 0.05, n_comparisons: int = 1) -> float:
    """Two-sided standard-normal z for a Bonferroni-adjusted family of size m.

    Returns ``Phi^-1(1 - alpha / (2 * m))``. With ``m == 1`` this is the ordinary
    two-sided ``z`` (``~1.96`` at ``alpha=0.05``); with ``m > 1`` the quantile
    widens, which is exactly the point — a confidence bound on the *selected* best
    of ``m`` searched configs must spend its error budget across the whole family,
    or it overstates the floor of a config that was tuned on the eval set.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1); got {alpha}")
    if n_comparisons < 1:
        raise ValueError(f"n_comparisons must be >= 1; got {n_comparisons}")
    return normal_ppf(1.0 - alpha / (2.0 * n_comparisons))


def wilson_lower_bound(
    successes: int, n: int, *, alpha: float = 0.05, n_comparisons: int = 1
) -> float:
    """Wilson score lower bound, optionally Bonferroni-corrected for selection.

    ``n_comparisons == 1`` (the default) returns the ordinary two-sided
    ``1 - alpha`` Wilson lower bound. ``n_comparisons == m > 1`` returns the
    *simultaneous* lower bound at the Bonferroni-adjusted level ``alpha / m`` — the
    honest floor for the best-of-``m`` config selected on the same gold set it was
    scored against. With ``n == 0`` there is no information, so ``0.0`` is returned
    (mirroring :func:`wilson_interval`'s uninformative ``[0, 1]``).
    """
    if n == 0:
        return 0.0
    return wilson_interval(successes, n, z=bonferroni_z(alpha, n_comparisons))[0]


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
