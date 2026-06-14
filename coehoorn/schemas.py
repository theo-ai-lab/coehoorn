"""Pydantic v2 models for the Coehoorn wire contract.

Shared contract between every component in the pipeline: the rubric parser,
persona generator, conversation runner, judge, and aggregator. Every
artifact written to runs/<run_id>.json is a serialized Report; the HTML
viewer reads only Report.

Trust boundary, enforced structurally not by prompt:
- A failed CriterionVerdict must cite a turn (cited_turn_index not None).
- A Verdict with overall_pass=False must name a worst_moment_turn_index,
  and that index must equal the cited_turn_index of at least one failed
  CriterionVerdict.
- Cited indices must resolve against the linked transcript when the
  Verdict is assembled into a Report.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)


class Archetype(StrEnum):
    """The six adversarial persona archetypes; single source of truth
    for both Persona.archetype and Report's archetype-key validator."""

    CONTRADICTOR = "contradictor"
    AMBIGUOUS = "ambiguous"
    EMOTIONAL = "emotional"
    OFF_TOPIC = "off_topic"
    INJECTOR = "injector"
    EDGE_CASE = "edge_case"


class CriterionStatus(StrEnum):
    """Three-valued judgment for a single criterion on a single transcript.

    Tri-state, not a bool, on purpose: a judge that has no basis to decide a
    criterion must be able to say so. Collapsing 'abstained' into 'passed'
    (the old behavior) silently inflates the pass column and corrupts the
    false-negative count in the meta-eval. Making abstention its own state
    keeps illegal combinations — a failure with no cited turn, a pass that
    cites a breach — unrepresentable rather than merely discouraged.
    """

    PASS = "pass"
    FAIL = "fail"
    ABSTAIN = "abstain"


class VerdictOutcome(StrEnum):
    """Transcript-level outcome. FAIL names a breach (and must cite it);
    PASS means at least one criterion was judged and none breached; ABSTAIN
    means nothing could be judged (every criterion abstained)."""

    PASS = "pass"
    FAIL = "fail"
    ABSTAIN = "abstain"


class ToolCall(BaseModel):
    """A tool/function the agent invoked on a turn — the unit a tool-policy
    check inspects (OWASP Agentic ASI02 tool misuse, ASI03 privilege abuse)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ConversationTurn(BaseModel):
    """A single message in an agent conversation; the atom referenced by
    cited_turn_index in verdicts. `index` is the canonical identity;
    list-position equality is asserted by Transcript. ``tool_calls`` captures
    any tools the agent invoked on this turn (empty for plain chat)."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    role: Literal["user", "assistant"]
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)


class Persona(BaseModel):
    """An adversarial role played by an Opus call to drive one
    conversation against the agent under test."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^p\d{2}$")
    archetype: Archetype
    name: str
    description: str


class Criterion(BaseModel):
    """One pass/fail rule the judge applies to a transcript; produced by
    rubric_parser from the architect-supplied NL rubric."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    weight: float = Field(default=1.0, gt=0)
    failure_is_critical: bool = False


class Rubric(BaseModel):
    """The full evaluation contract for a run; the judge reads this plus
    a single transcript and emits a Verdict."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[Criterion] = Field(min_length=1)
    overall_pass_threshold: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _unique_criterion_ids(self) -> Rubric:
        ids = [c.id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("Criterion ids must be unique within a Rubric")
        return self


class Transcript(BaseModel):
    """One persona's full conversation against the agent under test;
    the unit the judge scores."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    persona: Persona
    turns: list[ConversationTurn] = Field(min_length=1)
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def _check_invariants(self) -> Transcript:
        for i, t in enumerate(self.turns):
            if t.index != i:
                raise ValueError(
                    f"Transcript turn invariant violated: "
                    f"turns[{i}].index == {t.index}, expected {i}"
                )
        if self.completed_at < self.started_at:
            raise ValueError("Transcript completed_at must be >= started_at")
        return self


class CriterionVerdict(BaseModel):
    """The judge's verdict on a single criterion for a single transcript;
    a FAIL carries the cited turn that justifies it."""

    model_config = ConfigDict(extra="forbid")

    criterion_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    status: CriterionStatus
    confidence: float = Field(ge=0, le=1)
    cited_turn_index: int | None = Field(default=None, ge=0)
    rationale: str

    @model_validator(mode="after")
    def _status_invariants(self) -> CriterionVerdict:
        if self.status is CriterionStatus.FAIL:
            if self.cited_turn_index is None:
                raise ValueError(
                    "CriterionVerdict with status=fail must set cited_turn_index"
                )
            if not self.rationale.strip():
                raise ValueError(
                    "CriterionVerdict with status=fail must include a non-empty rationale"
                )
        else:
            # A pass or an abstention names no breach; only a failure cites.
            if self.cited_turn_index is not None:
                raise ValueError(
                    f"CriterionVerdict with status={self.status.value} must not "
                    "set cited_turn_index (only a failure cites a breach turn)"
                )
            if self.status is CriterionStatus.ABSTAIN and not self.rationale.strip():
                raise ValueError(
                    "CriterionVerdict with status=abstain must explain the abstention"
                )
        return self


class Verdict(BaseModel):
    """The judge's complete verdict for a single transcript: per-criterion
    verdicts plus the transcript-level outcome and worst-moment citation.

    Standalone construction is valid mid-run; full referential integrity
    (transcript_id resolution, cited_turn_index in-range against the
    linked transcript) is enforced when this verdict is assembled into a
    Report."""

    model_config = ConfigDict(extra="forbid")

    transcript_id: str
    criterion_verdicts: list[CriterionVerdict] = Field(min_length=1)
    outcome: VerdictOutcome
    worst_moment_turn_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_outcome_consistency(self) -> Verdict:
        ids = [cv.criterion_id for cv in self.criterion_verdicts]
        if len(ids) != len(set(ids)):
            raise ValueError(
                "criterion_verdicts must have unique criterion_id values"
            )
        statuses = [cv.status for cv in self.criterion_verdicts]
        n_fail = statuses.count(CriterionStatus.FAIL)
        n_abstain = statuses.count(CriterionStatus.ABSTAIN)

        if self.outcome is VerdictOutcome.FAIL:
            if n_fail == 0:
                raise ValueError(
                    "outcome=fail requires at least one failed CriterionVerdict"
                )
            if self.worst_moment_turn_index is None:
                raise ValueError("outcome=fail requires worst_moment_turn_index")
            failed_cited = {
                cv.cited_turn_index
                for cv in self.criterion_verdicts
                if cv.status is CriterionStatus.FAIL
            }
            if self.worst_moment_turn_index not in failed_cited:
                raise ValueError(
                    "worst_moment_turn_index must equal the cited_turn_index "
                    "of at least one failed CriterionVerdict"
                )
        else:
            if n_fail != 0:
                raise ValueError(
                    f"outcome={self.outcome.value} forbids any failed "
                    "CriterionVerdict (a breach forces outcome=fail)"
                )
            if self.worst_moment_turn_index is not None:
                raise ValueError(
                    f"outcome={self.outcome.value} forbids worst_moment_turn_index"
                )
            if self.outcome is VerdictOutcome.ABSTAIN and n_abstain != len(statuses):
                raise ValueError(
                    "outcome=abstain requires every criterion to abstain; a "
                    "decided criterion makes the outcome pass"
                )
            if self.outcome is VerdictOutcome.PASS and n_abstain == len(statuses):
                raise ValueError(
                    "outcome=pass requires at least one decided criterion; all "
                    "abstentions make the outcome abstain"
                )
        return self


_COMPUTED_FIELD_KEYS: tuple[str, ...] = (
    "pass_rate",
    "abstention_rate",
    "failures_by_criterion",
    "failures_by_archetype",
)


class Report(BaseModel):
    """The full run-level artifact written to runs/<run_id>.json; the
    only object the dashboard reads."""

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime
    completed_at: datetime
    agent_endpoint: str
    rubric: Rubric
    transcripts: list[Transcript] = Field(min_length=1)
    verdicts: list[Verdict] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _strip_computed_fields(cls, data: Any) -> Any:
        # Pydantic v2 emits computed_field values in model_dump_json output but
        # rejects them as extra inputs under extra="forbid". Strip them here so
        # round-trip (dump_json -> validate_json) works without weakening the
        # extra="forbid" guarantee for genuinely unknown keys.
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k not in _COMPUTED_FIELD_KEYS}
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pass_rate(self) -> float:
        return sum(
            1 for v in self.verdicts if v.outcome is VerdictOutcome.PASS
        ) / len(self.verdicts)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def abstention_rate(self) -> float:
        return sum(
            1 for v in self.verdicts if v.outcome is VerdictOutcome.ABSTAIN
        ) / len(self.verdicts)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failures_by_criterion(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for v in self.verdicts:
            for cv in v.criterion_verdicts:
                if cv.status is CriterionStatus.FAIL:
                    counts[cv.criterion_id] = counts.get(cv.criterion_id, 0) + 1
        return counts

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failures_by_archetype(self) -> dict[str, int]:
        archetype_by_tid = {
            t.id: t.persona.archetype.value for t in self.transcripts
        }
        counts: dict[str, int] = {}
        for v in self.verdicts:
            if v.outcome is VerdictOutcome.FAIL:
                arch = archetype_by_tid.get(v.transcript_id)
                if arch is not None:
                    counts[arch] = counts.get(arch, 0) + 1
        return counts

    @model_validator(mode="after")
    def _referential_integrity(self) -> Report:
        if self.completed_at < self.created_at:
            raise ValueError("Report completed_at must be >= created_at")

        transcript_ids = {t.id for t in self.transcripts}
        verdict_tids_list = [v.transcript_id for v in self.verdicts]
        verdict_tids = set(verdict_tids_list)
        if len(verdict_tids_list) != len(verdict_tids):
            raise ValueError("Multiple verdicts share a transcript_id")
        if transcript_ids != verdict_tids:
            missing = transcript_ids - verdict_tids
            extra_tids = verdict_tids - transcript_ids
            raise ValueError(
                f"Verdict/Transcript id mismatch: "
                f"transcripts without verdicts={sorted(missing)}, "
                f"verdicts without transcripts={sorted(extra_tids)}"
            )

        rubric_ids = {c.id for c in self.rubric.criteria}
        transcripts_by_id = {t.id: t for t in self.transcripts}

        for v in self.verdicts:
            cv_ids = {cv.criterion_id for cv in v.criterion_verdicts}
            if cv_ids != rubric_ids:
                raise ValueError(
                    f"Verdict {v.transcript_id} criterion coverage mismatch: "
                    f"missing={sorted(rubric_ids - cv_ids)}, "
                    f"extra={sorted(cv_ids - rubric_ids)}"
                )
            transcript = transcripts_by_id[v.transcript_id]
            valid_indices = {t.index for t in transcript.turns}
            if (
                v.worst_moment_turn_index is not None
                and v.worst_moment_turn_index not in valid_indices
            ):
                raise ValueError(
                    f"Verdict {v.transcript_id} worst_moment_turn_index "
                    f"{v.worst_moment_turn_index} is not a valid turn index "
                    f"of the linked transcript"
                )
            for cv in v.criterion_verdicts:
                if (
                    cv.cited_turn_index is not None
                    and cv.cited_turn_index not in valid_indices
                ):
                    raise ValueError(
                        f"Verdict {v.transcript_id} CriterionVerdict "
                        f"{cv.criterion_id} cited_turn_index "
                        f"{cv.cited_turn_index} is not a valid turn index "
                        f"of the linked transcript"
                    )

        # Persona ids are the per-run join key for comparison and the fort
        # diagram; a duplicate would silently drop one transcript's cells from
        # the confusion grid, so make it unrepresentable rather than wrong.
        persona_ids = [t.persona.id for t in self.transcripts]
        if len(persona_ids) != len(set(persona_ids)):
            dupes = sorted({p for p in persona_ids if persona_ids.count(p) > 1})
            raise ValueError(f"persona ids must be unique within a Report; duplicates: {dupes}")

        return self
