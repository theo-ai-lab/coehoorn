"""Export a Coehoorn Report as an Inspect AI eval log (optional extra).

    pip install 'coehoorn[inspect]'

Coehoorn discovers adversarial failures; Inspect AI (UK AISI) is the standard
harness for viewing and comparing eval results. This bridge turns a finished
Report into an ``EvalLog`` so a siege can be opened in ``inspect view`` next to
any other eval, with the cited worst-moment turn preserved in ``Score.metadata``
so a reviewer lands directly on the evidence.

``inspect_ai`` is imported lazily, so the core package never depends on it. The
export is built against inspect-ai 0.3.x; if the installed version moved a
field, construction fails LOUDLY naming the version seam rather than emitting a
malformed log.
"""
from __future__ import annotations

from pathlib import Path

from .schemas import CriterionStatus, Report, VerdictOutcome

_VERSION_HINT = (
    "Coehoorn's Inspect export targets inspect-ai 0.3.x; the installed version "
    "looks like it changed the EvalLog/EvalSample/Score schema."
)

# Inspect's score convention: C correct, I incorrect, N no-answer. A held wall
# is the agent answering correctly; a breach is incorrect; an abstention is no
# answer from the judge.
_VALUE_BY_OUTCOME = {
    VerdictOutcome.PASS: "C",
    VerdictOutcome.FAIL: "I",
    VerdictOutcome.ABSTAIN: "N",
}


def _require_inspect():
    try:
        from inspect_ai.log import (
            EvalConfig,
            EvalDataset,
            EvalLog,
            EvalSample,
            EvalSpec,
        )
        from inspect_ai.scorer import Score
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "The Inspect export requires the optional extra: "
            "pip install 'coehoorn[inspect]'"
        ) from e
    return EvalConfig, EvalDataset, EvalLog, EvalSample, EvalSpec, Score


def report_to_eval_log(report: Report):
    """Build an ``inspect_ai.log.EvalLog`` from a Coehoorn Report."""
    EvalConfig, EvalDataset, EvalLog, EvalSample, EvalSpec, Score = _require_inspect()
    by_tid = {v.transcript_id: v for v in report.verdicts}
    try:
        samples = []
        for t in report.transcripts:
            v = by_tid[t.id]
            convo = "\n".join(
                f"[{turn.role} · turn {turn.index}] {turn.content}" for turn in t.turns
            )
            breaches = [
                {"criterion": cv.criterion_id, "turn": cv.cited_turn_index}
                for cv in v.criterion_verdicts
                if cv.status is CriterionStatus.FAIL
            ]
            explanation = (
                "; ".join(f"{b['criterion']} breached at turn {b['turn']}" for b in breaches)
                or "all criteria held"
            )
            score = Score(
                value=_VALUE_BY_OUTCOME[v.outcome],
                answer=t.turns[-1].content if t.turns else "",
                explanation=explanation,
                metadata={
                    "archetype": t.persona.archetype.value,
                    "worst_moment_turn": v.worst_moment_turn_index,
                    "breaches": breaches,
                },
            )
            samples.append(
                EvalSample(
                    id=t.persona.id,
                    epoch=1,
                    input=convo,
                    target="hold every criterion",
                    scores={"coehoorn_judge": score},
                    metadata={
                        "persona": t.persona.name,
                        "archetype": t.persona.archetype.value,
                    },
                )
            )
        spec = EvalSpec(
            created=report.created_at.isoformat(),
            task="coehoorn-siege",
            dataset=EvalDataset(name="coehoorn", samples=len(samples)),
            model="coehoorn/heuristic",
            config=EvalConfig(),
        )
        return EvalLog(eval=spec, samples=samples, status="success")
    except Exception as e:  # pydantic/inspect schema drift -> fail loud
        raise RuntimeError(f"{_VERSION_HINT} Underlying error: {e!r}") from e


def write_eval_log_file(report: Report, path: str | Path) -> Path:
    """Write the Report to ``path`` as an Inspect ``.eval`` log."""
    from inspect_ai.log import write_eval_log

    write_eval_log(report_to_eval_log(report), str(path))
    return Path(path)
