"""Audit the auditor — score Coehoorn's judge against a frozen gold set.

A verdict is only worth its cited evidence if the judge that produced it is
calibrated. This module runs a judge over hand-labeled gold cases and reports
the confusion matrix and derived metrics (precision/recall/balanced-accuracy/
kappa, each with its Wilson interval) next to two dumb baselines — predict-
always-breach and predict-always-hold. A judge that cannot clearly beat both
baselines has not earned trust.

The gold set deliberately includes adversarial near-misses — a correctly
cited *real* case the keyword heuristic flags as fabricated, a fabricated
citation phrased to dodge the pattern — so the heuristic judge scores well
below 1.0. That gap is the honest argument for the LLM judge, not a defect to
hide.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .judge import judge_transcript_heuristic
from .metrics import DetectionMetrics
from .rubric_parser import HeuristicCriterionRule
from .schemas import (
    Archetype,
    ConversationTurn,
    Criterion,
    CriterionStatus,
    Persona,
    Rubric,
    Transcript,
    Verdict,
)

_FIXED_TS = datetime(2026, 5, 17, 10, 8, 0, tzinfo=timezone.utc)
_GOLD_PERSONA = Persona(
    id="p00", archetype=Archetype.EDGE_CASE, name="gold", description="gold fixture case"
)


class GoldCase(BaseModel):
    """One hand-labeled (transcript, criterion) cell with the true status."""

    model_config = ConfigDict(extra="forbid")

    id: str
    criterion_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    turns: list[tuple[str, str]] = Field(min_length=1)
    gold: CriterionStatus
    note: str = ""
    # Ground-truth breach turn index for a gold=fail cell, when known. Optional
    # and defaulting to None so cells that omit it still parse under
    # extra="forbid" (that config forbids *unknown* keys, not a *missing optional*
    # one). The frozen fixture sets it on the gold=fail cells the heuristic can
    # catch, anchoring the citation-faithfulness check (Feature #2 mutation score)
    # to ground truth; where it is absent the check falls back to the
    # faithful-by-construction heuristic baseline's cited turn.
    # evaluate_gold deliberately ignores it, so the committed confusion-matrix
    # tests stay byte-stable.
    gold_cited_turn: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_gold_cited_turn(self) -> GoldCase:
        """A ground-truth citation is meaningful only on a real breach, and must
        point at a turn that exists and carries the agent's reply. Reject a bad
        anchor at load time rather than let it silently skew faithfulness."""
        if self.gold_cited_turn is None:
            return self
        if self.gold is not CriterionStatus.FAIL:
            raise ValueError(
                "gold_cited_turn may only be set on a gold=fail cell "
                "(only a breach has a true cited turn)"
            )
        if self.gold_cited_turn >= len(self.turns):
            raise ValueError(
                f"gold_cited_turn {self.gold_cited_turn} is out of range for a "
                f"{len(self.turns)}-turn case"
            )
        role = self.turns[self.gold_cited_turn][0]
        if role != "assistant":
            raise ValueError(
                f"gold_cited_turn {self.gold_cited_turn} points at a {role!r} turn; "
                "a breach is cited on the assistant's reply, not the user's probe"
            )
        return self


# A judge-under-test maps a gold case (plus the rubric/rules it is scored
# against) to a predicted status for that case's criterion.
Predictor = Callable[
    [GoldCase, Rubric, dict[str, HeuristicCriterionRule]], CriterionStatus
]

# A verdict-level judge-under-test returns the *full* Verdict instead of only a
# status. This is the seam the mutation score needs: the plain Predictor above
# discards the cited turn, so citation bugs (relocate / off-by-one) are invisible
# to it. Each gold case is scored against a one-criterion rubric, so the returned
# Verdict always carries exactly one CriterionVerdict.
VerdictPredictor = Callable[
    [GoldCase, Rubric, dict[str, HeuristicCriterionRule]], Verdict
]


class GoldEvalResult(BaseModel):
    """The judge's scorecard against the gold set."""

    model_config = ConfigDict(extra="forbid")

    n_scored: int = Field(ge=0)
    n_abstained: int = Field(ge=0)
    metrics: DetectionMetrics
    baseline_always_breach: DetectionMetrics
    baseline_always_hold: DetectionMetrics


def load_gold_cases(path: str | Path) -> list[GoldCase]:
    """Load a JSONL gold file (one :class:`GoldCase` per non-empty line).

    Rejects a duplicate case ``id`` (a silent duplicate would double-count a cell
    in the confusion matrix / citation denominators / mutation score — the same
    join-key discipline ``Report`` enforces on transcripts). A malformed line is
    re-raised with its 1-based line number so the offending cell is locatable,
    instead of a bare pydantic traceback with no position.
    """
    cases: list[GoldCase] = []
    seen_ids: set[str] = set()
    for lineno, raw in enumerate(Path(path).read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = GoldCase.model_validate_json(line)
        except ValidationError as exc:
            raise ValueError(f"{path}:{lineno}: invalid gold case: {exc}") from exc
        if case.id in seen_ids:
            raise ValueError(
                f"{path}:{lineno}: duplicate gold case id {case.id!r} "
                "(gold ids must be unique; a duplicate would double-count its cell)"
            )
        seen_ids.add(case.id)
        cases.append(case)
    return cases


def _case_to_transcript(case: GoldCase) -> Transcript:
    turns = [
        ConversationTurn(index=i, role=role, content=content)
        for i, (role, content) in enumerate(case.turns)
    ]
    return Transcript(
        id=f"gold-{case.id}",
        persona=_GOLD_PERSONA,
        turns=turns,
        started_at=_FIXED_TS,
        completed_at=_FIXED_TS,
    )


def heuristic_verdict_predictor(
    case: GoldCase, rubric: Rubric, rules: dict[str, HeuristicCriterionRule]
) -> Verdict:
    """Predict the case's full Verdict with the offline heuristic judge.

    This is the honest baseline VerdictPredictor and the clean control for the
    mutation score: the heuristic judge is deterministic and per-criterion
    stateless, so its citation is faithful-by-construction. Each gold case is
    scored against a one-criterion rubric, so the returned Verdict always has
    exactly one CriterionVerdict.

    A criterion absent from the rubric (or lacking a rule) yields ABSTAIN,
    exactly as the heuristic judge behaves in a live run.
    """
    criterion = next(
        (c for c in rubric.criteria if c.id == case.criterion_id),
        Criterion(id=case.criterion_id, description="(gold-only criterion)"),
    )
    one_criterion = Rubric(criteria=[criterion], overall_pass_threshold=1.0)
    scoped_rules = (
        {case.criterion_id: rules[case.criterion_id]}
        if case.criterion_id in rules
        else {}
    )
    return judge_transcript_heuristic(
        _case_to_transcript(case), one_criterion, scoped_rules
    )


def heuristic_predictor(
    case: GoldCase, rubric: Rubric, rules: dict[str, HeuristicCriterionRule]
) -> CriterionStatus:
    """Predict the case's criterion status with the offline heuristic judge.

    A criterion absent from the rubric (or lacking a rule) yields ABSTAIN,
    exactly as the heuristic judge behaves in a live run. Thin delegate to
    :func:`heuristic_verdict_predictor` — the status is the verdict's single
    criterion status, preserving this function's original contract exactly.
    """
    return heuristic_verdict_predictor(
        case, rubric, rules
    ).criterion_verdicts[0].status


def evaluate_gold(
    cases: list[GoldCase],
    rubric: Rubric,
    rules: dict[str, HeuristicCriterionRule],
    predictor: Predictor = heuristic_predictor,
) -> GoldEvalResult:
    """Score ``predictor`` over ``cases``. The positive class is *breach*.

    A cell where the gold label or the prediction is ABSTAIN is excluded from
    the matrix and counted under ``n_abstained`` — an abstention is a declined
    judgment, not a wrong one.
    """
    tp = fp = fn = tn = abstained = 0
    for case in cases:
        prediction = predictor(case, rubric, rules)
        if (
            case.gold is CriterionStatus.ABSTAIN
            or prediction is CriterionStatus.ABSTAIN
        ):
            abstained += 1
            continue
        gold_breach = case.gold is CriterionStatus.FAIL
        pred_breach = prediction is CriterionStatus.FAIL
        if gold_breach and pred_breach:
            tp += 1
        elif gold_breach and not pred_breach:
            fn += 1
        elif not gold_breach and pred_breach:
            fp += 1
        else:
            tn += 1

    n_pos = tp + fn  # gold breaches in the scored set
    n_neg = fp + tn  # gold holds in the scored set
    return GoldEvalResult(
        n_scored=tp + fp + fn + tn,
        n_abstained=abstained,
        metrics=DetectionMetrics.from_counts(tp=tp, fp=fp, fn=fn, tn=tn),
        # Always-breach: every scored cell predicted FAIL.
        baseline_always_breach=DetectionMetrics.from_counts(
            tp=n_pos, fp=n_neg, fn=0, tn=0
        ),
        # Always-hold: every scored cell predicted PASS.
        baseline_always_hold=DetectionMetrics.from_counts(
            tp=0, fp=0, fn=n_pos, tn=n_neg
        ),
    )
