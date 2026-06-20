"""Cascade telemetry — measure Coehoorn's cheap -> expensive judging tiers.

Coehoorn judges in tiers, cheapest first:

1. a **deterministic rule-based heuristic judge** (the citation + tool-policy
   checks) — model-free, provable, zero network, faithful-by-construction;
2. an **LLM SOP-adherence judge** (Sonnet) — a model-based residual, key-gated;
3. a **frozen human gold set** on top — the deterministic oracle the first two
   are scored against.

For each cheap -> expensive boundary this module emits the suite-wide telemetry
shape ``{alpha, disagreement_rate, lossless_violations}``:

* ``alpha`` — the fraction the cheap/deterministic tier resolved *without
  escalating*. The heuristic judge "escalates" exactly when it ABSTAINS (no
  offline rule, or a probe that drew no reply) — those cells are the ones a
  stronger judge has to decide.
* ``disagreement_rate`` — over the cells BOTH tiers decided, how often they
  differ.
* ``lossless_violations`` — the COUNT of cells the cheap fast path resolved
  (did not escalate) to a verdict the expensive/oracle tier would NOT have
  produced. A lossless fast path resolves only cells it gets right; each wrong
  resolution is a lossless violation. (Here the cheap tier has no
  confidence-based escalation — it decides whenever it has a rule and a reply —
  so every wrong resolution is a lossless violation and the count coincides with
  ``disagreement_rate * n_co_judged``. With a confidence gate the violations
  would be the strict subset that should have escalated; the field is kept
  distinct for that reason and for shape-consistency across the suite.)

The heuristic -> frozen-gold boundary is measured at **zero model spend**: both
tiers are deterministic (rules vs frozen human labels), so the numbers are exact
and pinned in tests. The heuristic -> LLM boundary is real but cannot be measured
offline (it needs a key), so it is emitted with ``measured=False`` and null
rates rather than a fabricated number.

Each boundary also carries its cheap tier's ``regime`` (model-free/provable vs
model-based residual) and the residual ``locus`` it points at (a cited *turn*).
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .meta_eval import GoldCase, heuristic_predictor, load_gold_cases
from .metrics import ProportionEstimate
from .rubric_parser import HeuristicCriterionRule, parse_rubric_file
from .schemas import CriterionStatus, Rubric


class CascadeBoundary(BaseModel):
    """One cheap -> expensive tier boundary's telemetry slice.

    ``alpha``/``disagreement_rate`` are ``None`` when ``measured`` is False (the
    boundary is real but needs a key to evaluate, so a number would be invented).
    ``regime`` labels the *cheap* tier; ``locus`` is the residual it points at.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    cheap_tier: str
    expensive_tier: str
    regime: str
    locus: str
    measured: bool
    n_total: int = Field(ge=0)
    n_resolved: int = Field(ge=0)
    n_escalated: int = Field(ge=0)
    n_co_judged: int = Field(ge=0)
    alpha: float | None = Field(default=None, ge=0, le=1)
    disagreement_rate: float | None = Field(default=None, ge=0, le=1)
    lossless_violations: int = Field(ge=0)
    lossless_resolution_rate: float | None = Field(default=None, ge=0, le=1)
    note: str = ""

    @model_validator(mode="after")
    def _check_counts(self) -> CascadeBoundary:
        if self.n_resolved + self.n_escalated != self.n_total:
            raise ValueError("n_resolved + n_escalated must equal n_total")
        if self.lossless_violations > self.n_co_judged:
            raise ValueError("lossless_violations cannot exceed n_co_judged")
        return self


class CascadeTelemetry(BaseModel):
    """The repo's cascade-telemetry artifact: one slice per cheap->expensive
    boundary, plus the single recruiter-legible measured sentence."""

    model_config = ConfigDict(extra="forbid")

    boundaries: list[CascadeBoundary]
    measured_sentence: str


def gold_cascade_boundary(
    cases: list[GoldCase],
    rubric: Rubric,
    rules: dict[str, HeuristicCriterionRule],
) -> CascadeBoundary:
    """Measure the heuristic (cheap, deterministic) -> frozen-gold (oracle)
    boundary over the gold set. Zero model spend: both tiers are deterministic.

    The cheap tier escalates exactly on an ABSTAIN; a cell is co-judged when both
    the cheap tier decided it AND the gold gives a decided label. Disagreement and
    lossless violations are measured over the co-judged cells.
    """
    n_total = len(cases)
    n_resolved = 0  # cheap tier decided (did not abstain/escalate)
    n_co_judged = 0  # both cheap tier and gold decided
    violations = 0  # resolved cells the gold oracle would overturn
    lossless_resolved = 0  # resolved AND matches the gold oracle
    for case in cases:
        pred = heuristic_predictor(case, rubric, rules)
        cheap_decided = pred is not CriterionStatus.ABSTAIN
        gold_decided = case.gold is not CriterionStatus.ABSTAIN
        if cheap_decided:
            n_resolved += 1
        if cheap_decided and gold_decided:
            n_co_judged += 1
            if pred is case.gold:
                lossless_resolved += 1
            else:
                violations += 1
    n_escalated = n_total - n_resolved
    return CascadeBoundary(
        name="heuristic-judge -> frozen-gold-oracle",
        cheap_tier="deterministic rule-based heuristic judge (citation + tool-policy checks)",
        expensive_tier="frozen human gold labels",
        regime="model-free / provable (deterministic rules, faithful-by-construction citation)",
        locus="turn",
        measured=True,
        n_total=n_total,
        n_resolved=n_resolved,
        n_escalated=n_escalated,
        n_co_judged=n_co_judged,
        alpha=n_resolved / n_total if n_total else None,
        disagreement_rate=violations / n_co_judged if n_co_judged else None,
        lossless_violations=violations,
        lossless_resolution_rate=lossless_resolved / n_total if n_total else None,
        note=(
            "Zero model spend: cheap = deterministic rules, oracle = frozen human "
            "gold. The gold is deliberately stacked with adversarial near-misses, "
            "so the disagreement is the honest ceiling on the cheap tier — the "
            "argument for the expensive LLM judge, not a hidden cost."
        ),
    )


def _llm_boundary() -> CascadeBoundary:
    """The heuristic (cheap) -> LLM SOP-adherence judge (expensive) boundary.

    Real, but unmeasurable offline: scoring the disagreement needs a key. Emitted
    with ``measured=False`` and null rates rather than a fabricated number — the
    same honesty the self-play live path uses.
    """
    return CascadeBoundary(
        name="heuristic-judge -> LLM SOP-adherence judge",
        cheap_tier="deterministic rule-based heuristic judge",
        expensive_tier="LLM SOP-adherence judge (Sonnet)",
        regime="cheap tier is model-free/provable; expensive tier is a model-based residual",
        locus="turn",
        measured=False,
        n_total=0,
        n_resolved=0,
        n_escalated=0,
        n_co_judged=0,
        alpha=None,
        disagreement_rate=None,
        lossless_violations=0,
        lossless_resolution_rate=None,
        note=(
            "Not measured offline: the disagreement between the deterministic "
            "heuristic and the stochastic LLM judge needs ANTHROPIC_API_KEY to "
            "score. Reported as null rather than invented (no fake fallback)."
        ),
    )


def _measured_sentence(b: CascadeBoundary) -> str:
    alpha_pct = round((b.alpha or 0.0) * 100)
    escalate_pct = round((b.n_escalated / b.n_total) * 100) if b.n_total else 0
    disagree_pct = round((b.disagreement_rate or 0.0) * 100)
    lossless_pct = round((b.lossless_resolution_rate or 0.0) * 100)
    return (
        f"On the frozen gold set, Coehoorn's deterministic fast path (the rule-based "
        f"heuristic judge) resolves {alpha_pct}% of cells without escalating and "
        f"{lossless_pct}% losslessly; the expensive LLM judge is needed only for the "
        f"{escalate_pct}% it abstains on, and on the cells it does resolve it "
        f"disagrees with the human gold {disagree_pct}% of the time "
        f"({b.lossless_violations} measured lossless-violations — the deliberate "
        f"near-misses the stronger judge exists to catch, not a hidden cost)."
    )


def gold_cascade_telemetry(
    cases: list[GoldCase],
    rubric: Rubric,
    rules: dict[str, HeuristicCriterionRule],
) -> CascadeTelemetry:
    """Assemble the repo's cascade telemetry from the gold set (offline, exact)."""
    measured = gold_cascade_boundary(cases, rubric, rules)
    return CascadeTelemetry(
        boundaries=[measured, _llm_boundary()],
        measured_sentence=_measured_sentence(measured),
    )


def load_and_measure(
    gold_path: str | Path, rubric_path: str | Path
) -> CascadeTelemetry:
    """Convenience loader: parse the rubric + gold and emit the telemetry."""
    rubric, rules = parse_rubric_file(rubric_path)
    cases = load_gold_cases(gold_path)
    return gold_cascade_telemetry(cases, rubric, rules)


__all__ = [
    "CascadeBoundary",
    "CascadeTelemetry",
    "gold_cascade_boundary",
    "gold_cascade_telemetry",
    "load_and_measure",
    "wilson_disagreement_estimate",
]


def wilson_disagreement_estimate(b: CascadeBoundary) -> ProportionEstimate:
    """Wilson interval for a boundary's disagreement rate (its honest small-n
    uncertainty). Returns the uninformative estimate when nothing was co-judged."""
    return ProportionEstimate.from_counts(b.lossless_violations, b.n_co_judged)
