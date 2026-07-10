"""CITE-MR — metamorphic citation-stability with a self-consistency null floor.

A verdict that cites the wrong turn is worse than one that cites no turn, and a
judge whose citation wanders under a *semantics-preserving* edit of the
transcript cannot be trusted to point at the breach it claims to have found.
This module measures that.

The idea is metamorphic testing: apply a transform ``T`` that provably does not
change the criterion-under-test (rename the persona, prepend neutral filler,
splice a neutral turn-pair between non-cited turns, paraphrase non-cited turns),
re-judge, and require the citation to move by exactly the transform's positional
shift::

    judge(T(t)).cited == remap[judge(t).cited]

Each transform returns the new :class:`~coehoorn.schemas.Transcript` *and* the
``remap`` (original turn index -> new turn index) that encodes that law. Because
:class:`~coehoorn.schemas.Transcript` enforces ``turns[i].index == i``, every
structural transform re-keys ``ConversationTurn.index`` to its new list position
or construction raises — the re-key is mandatory, not cosmetic.

Two honesty disciplines, both inherited from ``meta_eval``/``metrics``:

* The deterministic heuristic judge is the *control*: faithful-by-construction,
  so its null flip-rate is provably 0 and its citation is stable by construction
  (stability 1.0). It is NOT the real audit target — a high control number proves
  the harness works, not that any real judge is robust.
* The stochastic LLM judge is the real target. Any *single* perturbed citation
  flip can be pure judge jitter, so a flip is only logged as instability when a
  one-sided Fisher's EXACT test (Holm-corrected across the transform x finding
  panel) shows the perturbed flip-rate *significantly* exceeds the
  unchanged-transcript null floor (``self_consistency_floor``).
  Stability is necessary, never sufficient: a constant judge that always cites
  turn 0 is perfectly stable and useless, so these numbers must always be read
  next to the gold-accuracy metrics from ``meta_eval``, never as a standalone
  quality gate. Every reported rate carries its Wilson interval; on this frozen
  single-persona fixture the intervals are wide, and that width is the point.

Statistical method: the instability gate is a one-sided Fisher's EXACT test per
(transform, finding) — correct at the small ``k`` the LLM path uses, where a
normal approximation is anti-conservative — and the panel is Holm-corrected so
the family-wise false-positive rate is controlled at ``alpha`` (a bare
per-comparison alpha would inflate it to ``1-(1-alpha)^m``). The CLI still warns
when ``k`` is below the power floor at which even a maximal flip cannot reach
``alpha``. Remaining limits (disclosed): the frozen gold is a single persona
(breadth, not correctness), and an LLM run costs ``1 + (1 + #transforms) * k``
judge calls, unbounded in ``k``.

Offline-first: ``anthropic`` is never imported at module load. The core
(transforms, remap law, heuristic control, gate math) runs with no key and no
network; only ``judge_transcript_llm`` imports ``anthropic`` lazily, and the
stochastic path is exercised in tests via a deterministic mock judge.
"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .judge import judge_transcript_heuristic, judge_transcript_llm
from .metrics import ProportionEstimate
from .rubric_parser import HeuristicCriterionRule, parse_rubric_file
from .schemas import (
    ConversationTurn,
    CriterionStatus,
    Persona,
    Report,
    Rubric,
    Transcript,
    Verdict,
    VerdictOutcome,
)

# ---------------------------------------------------------------------------
# Determinism: every synthetic transcript reuses one fixed timestamp so the
# serialized artifacts stay byte-reproducible (mirrors meta_eval._FIXED_TS).
# No datetime.now / time.time / RNG anywhere on this path.
# ---------------------------------------------------------------------------
_FIXED_TS = datetime(2026, 5, 17, 10, 8, 0, tzinfo=UTC)

# CLI guard: an LLM run issues 1 + (1 + #transforms) * k real API calls and each
# Fisher tail computes math.comb(2k, k), so an accidental huge --k is a paid-call /
# compute footgun. Cap it (generous for any real statistical run; raise if needed).
_MAX_K = 1000

# Type aliases (documented in the public API).
Remap = dict[int, int]
Transform = Callable[..., "tuple[Transcript, Remap]"]
JudgeRunner = Callable[[Transcript], Verdict]


# ---------------------------------------------------------------------------
# Fixed neutral data. None of these strings may contain a probe keyword or a
# failure signal of the shipped rubric (asserted in tests/test_metamorphic.py),
# or the filler/synonym would mint a spurious breach and corrupt the metric.
# ---------------------------------------------------------------------------
_FILLER_USER: str = "By the way, what time should we wrap up our chat today?"
_FILLER_ASSISTANT: str = "Sure, we can finish whenever you like — take your time."

# Whole-word synonym table for paraphrasing NON-cited turns. Every replacement
# value is checked (in tests) to be free of every probe keyword / failure signal
# so a paraphrase can never alter the criterion under test.
DEFAULT_SYNONYMS: dict[str, str] = {
    "hello": "hi",
    "hey": "hi",
    "thanks": "thank you",
    "really": "truly",
    "great": "wonderful",
    "good": "fine",
    "okay": "alright",
    "ok": "alright",
    "yes": "yeah",
    "talk": "chat",
    "happy": "glad",
    "tired": "weary",
    "today": "this day",
}

# A small neutral persona-name ring; rename swaps to the first entry != old.
DEFAULT_ALIAS_RING: tuple[str, ...] = ("Avery", "Jordan", "Quinn", "Riley", "Sasha")
DEFAULT_ALIAS: dict[str, str] = {
    "gold": "Avery",
    "Casey": "Jordan",
    "Avery": "Jordan",
    "Jordan": "Avery",
}


# ---------------------------------------------------------------------------
# Whole-word substitution helpers (stdlib re; no new deps).
# ---------------------------------------------------------------------------
def _sub_synonyms(text: str, mapping: dict[str, str]) -> str:
    """Replace whole alphabetic words present (case-insensitively) in ``mapping``.

    Single forward pass over the original tokens — a replacement is never
    re-scanned, so the table cannot cascade or ping-pong.
    """

    def repl(match: re.Match[str]) -> str:
        word = match.group(0)
        return mapping.get(word.lower(), word)

    return re.sub(r"[A-Za-z']+", repl, text)


def _sub_name(text: str, old: str, new: str) -> str:
    """Whole-word swap of a persona name ``old`` -> ``new`` in ``text``."""
    if not old:
        return text
    return re.sub(rf"\b{re.escape(old)}\b", new, text)


def _rekeyed(turns: list[tuple[str, str, list]]) -> list[ConversationTurn]:
    """Build ConversationTurns whose .index == list position (the invariant)."""
    return [
        ConversationTurn(index=i, role=role, content=content, tool_calls=tcs)
        for i, (role, content, tcs) in enumerate(turns)
    ]


def _turn_tuples(transcript: Transcript) -> list[tuple[str, str, list]]:
    return [(t.role, t.content, list(t.tool_calls)) for t in transcript.turns]


def _rebuild(transcript: Transcript, turns: list[tuple[str, str, list]],
             *, persona: Persona | None = None) -> Transcript:
    return Transcript(
        id=transcript.id,
        persona=persona if persona is not None else transcript.persona,
        turns=_rekeyed(turns),
        started_at=_FIXED_TS,
        completed_at=_FIXED_TS,
    )


# ---------------------------------------------------------------------------
# binding_turns — the turns the heuristic citation depends on.
# ---------------------------------------------------------------------------
def binding_turns(transcript: Transcript, cited_index: int) -> frozenset[int]:
    """Turns whose content the citation at ``cited_index`` depends on.

    The cited turn itself plus the nearest preceding user turn (the probe that
    bound it via ``judge._assistant_reply_after``). The runner unions this over
    every reference finding and passes the result as ``protected_turns`` to each
    transform, so paraphrase/insert never disturb a breach trigger or citation.

    A standalone ``Verdict`` legally permits an out-of-range ``cited_turn_index``
    (only ``Report`` range-checks it), so the stochastic LLM judge can cite a
    turn that does not exist. Rather than index out of bounds and abort the run,
    an out-of-range citation binds nothing (empty set); the runner records it as
    an out-of-range citation instead of crashing.
    """
    if not 0 <= cited_index < len(transcript.turns):
        return frozenset()
    result = {cited_index}
    for i in range(cited_index - 1, -1, -1):
        if transcript.turns[i].role == "user":
            result.add(i)
            break
    return frozenset(result)


# ---------------------------------------------------------------------------
# The four deterministic, semantics-preserving transforms.
# Each returns (new_transcript, remap). remap is total over original indices,
# injective, and strictly order-preserving.
# ---------------------------------------------------------------------------
def t_rename(
    transcript: Transcript,
    *,
    protected_turns: frozenset[int] = frozenset(),
    new_name: str | None = None,
    alias_map: dict[str, str] | None = None,
) -> tuple[Transcript, Remap]:
    """Swap the persona name/aliases; identity remap.

    Rebuilds the persona with a neutral alias and substitutes whole-word
    occurrences of the old name in turn content. The persona name is untrusted
    free text loaded from the report, so if it collided with a probe keyword a
    blind substitution could delete a breach trigger and change the criterion
    under test. To keep the transform genuinely semantics-preserving, content in
    ``protected_turns`` (the cited turn and its binding probe) is left
    byte-identical — exactly as ``t_paraphrase_noncited`` does.
    """
    old = transcript.persona.name
    table = alias_map if alias_map is not None else DEFAULT_ALIAS
    target = new_name or table.get(old)
    if not target or target == old:
        target = next((n for n in DEFAULT_ALIAS_RING if n != old), "Quinn")

    new_persona = Persona(
        id=transcript.persona.id,
        archetype=transcript.persona.archetype,
        name=target,
        description=transcript.persona.description,
    )
    new_turns = [
        (
            t.role,
            t.content if t.index in protected_turns
            else _sub_name(t.content, old, target),
            list(t.tool_calls),
        )
        for t in transcript.turns
    ]
    new_t = _rebuild(transcript, new_turns, persona=new_persona)
    remap: Remap = {i: i for i in range(len(transcript.turns))}
    return new_t, remap


def t_renumber(
    transcript: Transcript,
    *,
    protected_turns: frozenset[int] = frozenset(),
    k: int = 2,
    filler_user: str = _FILLER_USER,
    filler_assistant: str = _FILLER_ASSISTANT,
) -> tuple[Transcript, Remap]:
    """Prepend ``k`` neutral filler turns and re-key every turn.

    Filler occupies positions ``0..k-1`` (alternating user/assistant starting
    with user); originals move to ``k..k+n-1``. ``remap = {i: i + k}``. The
    re-key is mandatory — without it ``Transcript()`` raises the
    ``turns[i].index == i`` invariant. Default ``k=2`` (one user+assistant pair)
    preserves strict alternation; any ``k >= 1`` is structurally valid.
    """
    if k < 1:
        raise ValueError(f"t_renumber requires k >= 1; got {k}")
    filler: list[tuple[str, str, list]] = []
    for j in range(k):
        if j % 2 == 0:
            filler.append(("user", filler_user, []))
        else:
            filler.append(("assistant", filler_assistant, []))
    new_turns = filler + _turn_tuples(transcript)
    new_t = _rebuild(transcript, new_turns)
    remap: Remap = {i: i + k for i in range(len(transcript.turns))}
    return new_t, remap


def _borders_protected(gap: int, protected_turns: frozenset[int]) -> bool:
    """True if inserting at ``gap`` would split a protected (user, reply) pair.

    A protected binding is (pu, pu+1) with both indices protected; the split
    point is the gap ``pu + 1``. (For strictly-alternating transcripts this is
    always odd and already rejected, but the guard is explicit.)
    """
    return any((pu + 1) in protected_turns and gap == pu + 1 for pu in protected_turns)


def _auto_gap(n: int, protected_turns: frozenset[int]) -> int:
    """Largest even gap in ``0..n`` that leaves every protected binding intact.

    Defaults to ``n`` (append a trailing pair) — always safe, nothing follows.
    """
    start = n if n % 2 == 0 else n - 1
    for g in range(start, -1, -2):
        if not _borders_protected(g, protected_turns):
            return g
    return n


def t_insert(
    transcript: Transcript,
    *,
    protected_turns: frozenset[int] = frozenset(),
    gaps: tuple[int, ...] | None = None,
    filler_user: str = _FILLER_USER,
    filler_assistant: str = _FILLER_ASSISTANT,
) -> tuple[Transcript, Remap]:
    """Splice a neutral (user, assistant) pair at each gap; re-key all turns.

    Gaps are insert-before-original-index positions in ``0..n``. ALL gaps must
    be EVEN — an even gap is a complete-pair boundary, so it can never split a
    (probe-user, immediate-reply) binding (the 'between non-cited turns'
    guarantee). Raises ValueError on an odd gap, an out-of-range gap, or a gap
    that borders a protected binding. ``remap[i] = i + 2 * #{g in gaps: g <= i}``
    — deeper turns shift, earlier ones do not. ``gaps=None`` auto-selects one
    safe even gap (default ``n`` = append a trailing pair).
    """
    n = len(transcript.turns)
    if gaps is None:
        gaps = (_auto_gap(n, protected_turns),)
    gap_list = sorted(gaps)
    for g in gap_list:
        if g % 2 != 0:
            raise ValueError(
                f"t_insert gap {g} is odd; only even gaps (complete-pair "
                "boundaries) are valid — an odd gap would split a probe/reply pair"
            )
        if g < 0 or g > n:
            raise ValueError(f"t_insert gap {g} out of range 0..{n}")
        if _borders_protected(g, protected_turns):
            raise ValueError(
                f"t_insert gap {g} borders a protected binding {sorted(protected_turns)}"
            )

    gap_multiset = list(gap_list)
    new_turns: list[tuple[str, str, list]] = []
    orig = _turn_tuples(transcript)
    for pos in range(n + 1):
        for _ in range(gap_multiset.count(pos)):
            new_turns.append(("user", filler_user, []))
            new_turns.append(("assistant", filler_assistant, []))
        if pos < n:
            new_turns.append(orig[pos])

    new_t = _rebuild(transcript, new_turns)
    remap: Remap = {
        i: i + 2 * sum(1 for g in gap_list if g <= i) for i in range(n)
    }
    return new_t, remap


def t_paraphrase_noncited(
    transcript: Transcript,
    *,
    protected_turns: frozenset[int] = frozenset(),
    synonyms: dict[str, str] | None = None,
) -> tuple[Transcript, Remap]:
    """Whole-word synonym substitution on turns NOT in ``protected_turns``.

    ``protected_turns`` MUST be the full binding set (cited assistant turn AND
    its bound user probe — see :func:`binding_turns`) so the breach trigger and
    its citation are byte-identical after the transform. Identity remap. A
    synonym that altered a probe would change the verdict, and the invariance
    check is exactly what catches it.
    """
    table = synonyms if synonyms is not None else DEFAULT_SYNONYMS
    new_turns: list[tuple[str, str, list]] = []
    for t in transcript.turns:
        if t.index in protected_turns:
            new_turns.append((t.role, t.content, list(t.tool_calls)))
        else:
            new_turns.append(
                (t.role, _sub_synonyms(t.content, table), list(t.tool_calls))
            )
    new_t = _rebuild(transcript, new_turns)
    remap: Remap = {i: i for i in range(len(transcript.turns))}
    return new_t, remap


DEFAULT_TRANSFORMS: dict[str, Transform] = {
    "rename": t_rename,
    "renumber": t_renumber,
    "insert": t_insert,
    "paraphrase": t_paraphrase_noncited,
}


# ---------------------------------------------------------------------------
# JudgeRunner adapters — normalize both judges to one-arg callables.
# ---------------------------------------------------------------------------
def heuristic_runner(
    rubric: Rubric, rules: dict[str, HeuristicCriterionRule]
) -> JudgeRunner:
    """One-arg runner over the DETERMINISTIC heuristic judge (the control)."""

    def run(transcript: Transcript) -> Verdict:
        return judge_transcript_heuristic(transcript, rubric, rules)

    return run


def llm_runner(
    rubric: Rubric, *, api_key: str | None = None, model: str | None = None
) -> JudgeRunner:
    """One-arg runner over the STOCHASTIC LLM judge (the real audit target).

    Raises ``ValueError`` from ``judge_transcript_llm`` when no key is present.
    Marked non-deterministic in all output; mocked in tests, never on the
    default offline path.
    """

    def run(transcript: Transcript) -> Verdict:
        return judge_transcript_llm(transcript, rubric, api_key=api_key, model=model)

    return run


# ---------------------------------------------------------------------------
# The gate: pooled two-proportion z-test, one-sided H1: p1 > p0.
# ---------------------------------------------------------------------------
def _normal_sf(z: float) -> float:
    """Upper-tail standard-normal survival function via stdlib erfc."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def two_proportion_z_test(
    x0: int, n0: int, x1: int, n1: int
) -> tuple[float | None, float | None]:
    """Pooled two-proportion z-test, one-sided for H1: p1 > p0.

    Returns ``(z, p_value)`` where ``p_value = _normal_sf(z)``. Returns
    ``(None, None)`` on a degenerate standard error (``x0 + x1 == 0`` or
    ``x0 + x1 == n0 + n1``, or an empty denominator) — treated as
    not-significant. This is the gate that prevents pure judge jitter
    (``p1 ~= p0``) from being laundered as instability.
    """
    if n0 <= 0 or n1 <= 0:
        return (None, None)
    total_succ = x0 + x1
    total_n = n0 + n1
    if total_succ == 0 or total_succ == total_n:
        return (None, None)
    p_pool = total_succ / total_n
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n0 + 1.0 / n1))
    if se == 0.0:
        return (None, None)
    z = (x1 / n1 - x0 / n0) / se
    return (z, _normal_sf(z))


def fisher_exact_greater(x0: int, n0: int, x1: int, n1: int) -> float:
    """One-sided Fisher's exact p for H1: perturbed rate (x1/n1) > null (x0/n0).

    The EXACT gate, correct at the small ``k`` the LLM path uses, where the
    normal approximation (``two_proportion_z_test``) is unreliable and
    anti-conservative. Conditions on the margins of the 2x2 table
    [[x1, n1 - x1], [x0, n0 - x0]] and sums the hypergeometric right tail
    P(perturbed flips >= x1). Stdlib only (``math.comb``); returns 1.0 on a
    degenerate margin (no flips, all flips, or an empty arm) — not significant,
    matching the z-test's degenerate guard.
    """
    big_n = n0 + n1
    total_flips = x0 + x1
    if n0 <= 0 or n1 <= 0 or total_flips == 0 or total_flips == big_n:
        return 1.0
    hi = min(n1, total_flips)
    denom = math.comb(big_n, n1)
    tail = sum(
        math.comb(total_flips, i) * math.comb(big_n - total_flips, n1 - i)
        for i in range(x1, hi + 1)
    )
    return min(1.0, tail / denom)


def _holm_significant(p_values: list[float], alpha: float) -> list[bool]:
    """Holm-Bonferroni step-down: control the FAMILY-WISE error rate across the
    panel at ``alpha``. The gate fires if ANY (transform, finding) crosses, so a
    bare per-comparison alpha would inflate the run-level false-positive rate
    (~1-(1-alpha)^m). Sort ascending; reject ``p_(i)`` while
    ``p_(i) <= alpha / (m - i + 1)``, stopping at the first failure. Returns a
    per-input boolean aligned to ``p_values``.
    """
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    reject = [False] * m
    for rank, idx in enumerate(order):
        if p_values[idx] <= alpha / (m - rank):
            reject[idx] = True
        else:
            break
    return reject


# ---------------------------------------------------------------------------
# Result models.
# ---------------------------------------------------------------------------
class CitationStabilityScore(BaseModel):
    """Per (transform, finding) scorecard.

    ``expected_cited_turn == remap[reference_cited_turn]`` is the law's
    prediction. ``stability`` is the Wilson-bounded Citation Stability Score =
    agreements / k_perturbed (reuses ``metrics.wilson_interval`` via
    ``ProportionEstimate.from_counts``). ``p_value`` is the raw per-comparison
    one-sided Fisher's exact p (perturbed flip-rate > null); ``z`` is the
    informational two-proportion z-statistic only. ``is_unstable`` is the GATED
    finding: for the stochastic judge, True only when this comparison survives
    the Holm correction across the run's panel at ``alpha``; for the
    deterministic control, True iff the citation drifts at all (no jitter, so any
    drift above the provably-zero null is certain). Stability does not imply
    correctness — read alongside ``meta_eval`` gold accuracy. For the heuristic
    control on a genuine transform every field collapses to perfect stability
    (flips 0, stability.value 1.0, is_unstable False).
    """

    model_config = ConfigDict(extra="forbid")

    transform: str
    criterion_id: str
    reference_cited_turn: int
    expected_cited_turn: int
    k_null: int = Field(ge=0)
    k_perturbed: int = Field(ge=0)
    null_flips: int = Field(ge=0)
    perturbed_flips: int = Field(ge=0)
    null_flip_rate: ProportionEstimate
    perturbed_flip_rate: ProportionEstimate
    stability: ProportionEstimate
    verdict_invariant: bool
    z: float | None = None
    p_value: float | None = Field(default=None, ge=0, le=1)
    is_unstable: bool
    deterministic: bool
    note: str = ""


class CiteMrReport(BaseModel):
    """Run-level CITE-MR artifact.

    ``per_transform_stability`` aggregates agreements / (n_findings * k) per
    transform as a Wilson-bounded ProportionEstimate. ``unstable_findings`` is
    the gated subset (``is_unstable`` True). ``n_findings == 0`` means the
    reference verdict had no FAIL citation to track, so per-transform stability
    is undefined and rendered as ``n/a`` (``ProportionEstimate.from_counts(0, 0)``
    → ``value=None``), not 1.0 — the verdict-invariance law check below still
    runs. Stability is necessary, not sufficient: a constant judge scores a
    perfect 1.0 here while detecting nothing, so this artifact must be read next
    to the gold-accuracy scorecard, never as a standalone quality gate. Round-
    trips through model_dump_json/model_validate_json (extra='forbid' clean).

    ``verdict_invariance_violations`` lists transforms that changed the verdict
    itself — the outcome or the *set* of failing criteria — under a
    semantics-preserving edit. That is a LAW violation, checked for EVERY
    transform (including when the reference had no FAIL citation), so a
    PASS->FAIL flip or a newly-failing criterion is caught rather than dropped by
    the citation loop, which only iterates the reference's own FAIL findings. For
    the deterministic control any flip is a certain violation; for the stochastic
    judge it is gated against the unchanged-transcript outcome-flip rate.
    """

    model_config = ConfigDict(extra="forbid")

    transcript_id: str
    reference_outcome: VerdictOutcome
    n_findings: int = Field(ge=0)
    k: int = Field(ge=1)
    alpha: float = Field(gt=0, lt=1)
    deterministic: bool
    scores: list[CitationStabilityScore]
    per_transform_stability: dict[str, ProportionEstimate]
    unstable_findings: list[CitationStabilityScore]
    verdict_invariance_violations: list[str] = Field(default_factory=list)
    # Rubric tokens that collide with a default transform's filler/synonym/alias (or
    # the persona name): on those tokens the transform may NOT be semantics-
    # preserving, so this run's stability/instability is not trustworthy. Recorded
    # machine-readably (not just a stderr warning) so a --json/CI consumer can see it;
    # under --fail-on-instability a non-empty list also gates (see _exit_code).
    rubric_collisions: list[str] = Field(default_factory=list)


def _build_stability_score(
    transform: str,
    criterion_id: str,
    reference_cited_turn: int,
    expected_cited_turn: int,
    *,
    k_null: int,
    k_perturbed: int,
    null_flips: int,
    perturbed_flips: int,
    verdict_invariant: bool,
    deterministic: bool,
    alpha: float,
    note: str = "",
) -> CitationStabilityScore:
    """Assemble one scorecard, running the gate to decide ``is_unstable``."""
    z, _ = two_proportion_z_test(null_flips, k_null, perturbed_flips, k_perturbed)
    # Gate on Fisher's EXACT one-sided p, correct at the small k the LLM path
    # uses (the normal-approx z is anti-conservative there). z is kept only as an
    # informational effect-size statistic. For the stochastic path this is the
    # PER-COMPARISON decision; run_cite_mr then Holm-corrects across the panel.
    p_value = fisher_exact_greater(null_flips, k_null, perturbed_flips, k_perturbed)
    null_rate = null_flips / k_null if k_null else 0.0
    pert_rate = perturbed_flips / k_perturbed if k_perturbed else 0.0
    if deterministic:
        # No jitter: the null floor is provably 0, so any citation drift above it
        # is a CERTAIN instability and must NOT depend on a statistical test
        # (inert at the small k the deterministic control uses). This keeps
        # deterministic citation drift gating --fail-on-instability at k=1.
        is_unstable = pert_rate > null_rate
    else:
        is_unstable = p_value < alpha and pert_rate > null_rate
    return CitationStabilityScore(
        transform=transform,
        criterion_id=criterion_id,
        reference_cited_turn=reference_cited_turn,
        expected_cited_turn=expected_cited_turn,
        k_null=k_null,
        k_perturbed=k_perturbed,
        null_flips=null_flips,
        perturbed_flips=perturbed_flips,
        null_flip_rate=ProportionEstimate.from_counts(null_flips, k_null),
        perturbed_flip_rate=ProportionEstimate.from_counts(perturbed_flips, k_perturbed),
        stability=ProportionEstimate.from_counts(k_perturbed - perturbed_flips, k_perturbed),
        verdict_invariant=verdict_invariant,
        z=z,
        p_value=p_value,
        is_unstable=is_unstable,
        deterministic=deterministic,
        note=note,
    )


def _fail_findings(verdict: Verdict) -> dict[str, int]:
    """{criterion_id: cited_turn_index} over the FAIL criterion verdicts."""
    return {
        cv.criterion_id: cv.cited_turn_index
        for cv in verdict.criterion_verdicts
        if cv.status is CriterionStatus.FAIL and cv.cited_turn_index is not None
    }


def _cited_for(verdict: Verdict, criterion_id: str) -> int | None:
    """The FAIL-cited turn for ``criterion_id`` in ``verdict``, else None."""
    for cv in verdict.criterion_verdicts:
        if cv.criterion_id == criterion_id:
            if cv.status is CriterionStatus.FAIL:
                return cv.cited_turn_index
            return None
    return None


def self_consistency_floor(
    runner: JudgeRunner,
    transcript: Transcript,
    *,
    k: int,
    reference: Verdict | None = None,
) -> tuple[dict[str, ProportionEstimate], int]:
    """Null floor: resample ``runner`` ``k`` times on the UNCHANGED transcript.

    Returns ``(citation_floor, null_outcome_flips)``. ``citation_floor`` records,
    per FAIL criterion, the cited-turn flip-rate
    ``p0 = #(resample.cited != reference.cited) / k`` as a Wilson-bounded
    ``ProportionEstimate.from_counts(flips, k)``. ``null_outcome_flips`` is how
    many of the ``k`` unchanged resamples disagreed with the reference verdict
    (outcome or the set of failing criteria) — the baseline jitter the
    verdict-invariance check is gated against. For the deterministic heuristic
    runner both are provably 0. This measures THIS judge's internal stochasticity
    on one input, not population generalization.
    """
    if reference is None:
        reference = runner(transcript)
    ref_cites = _fail_findings(reference)
    ref_fail_set = frozenset(ref_cites)
    flips = dict.fromkeys(ref_cites, 0)
    null_outcome_flips = 0
    for _ in range(k):
        v = runner(transcript)
        if v.outcome != reference.outcome or frozenset(_fail_findings(v)) != ref_fail_set:
            null_outcome_flips += 1
        for cid, ref_c in ref_cites.items():
            if _cited_for(v, cid) != ref_c:
                flips[cid] += 1
    citation_floor = {
        cid: ProportionEstimate.from_counts(flips[cid], k) for cid in ref_cites
    }
    return citation_floor, null_outcome_flips


def run_cite_mr(
    runner: JudgeRunner,
    transcript: Transcript,
    *,
    transforms: dict[str, Transform] = DEFAULT_TRANSFORMS,
    k: int = 1,
    alpha: float = 0.05,
    deterministic: bool = False,
    rubric_collisions: list[str] | tuple[str, ...] = (),
) -> CiteMrReport:
    """The CITE-MR runner.

    (1) reference verdict + FAIL findings. (2) null floor via
    ``self_consistency_floor`` (``k`` resamples on the unchanged transcript).
    (3) for each transform: apply it (passing ``protected_turns`` = union of
    ``binding_turns`` over findings), resample ``k`` times, and for each finding
    compare ``resample.cited`` against ``expected = remap[reference.cited]``.
    (4) per (transform, finding) build a :class:`CitationStabilityScore` whose
    ``is_unstable`` is gated by the two-proportion z-test against the null.
    ``deterministic=True`` is passed by the heuristic path (``k`` may be 1).
    """
    reference = runner(transcript)
    findings = _fail_findings(reference)
    reference_fail_set = frozenset(findings)
    floor, null_outcome_flips = self_consistency_floor(
        runner, transcript, k=k, reference=reference
    )
    null_flips = {cid: floor[cid].numerator for cid in findings}

    if findings:
        protected = frozenset().union(
            *(binding_turns(transcript, cited) for cited in findings.values())
        )
    else:
        protected = frozenset()

    scores: list[CitationStabilityScore] = []
    per_transform: dict[str, ProportionEstimate] = {}
    verdict_violations: list[str] = []
    stochastic_verdict_tests: list[tuple[str, float]] = []  # (transform, fisher p)
    for name, transform in transforms.items():
        new_t, remap = transform(transcript, protected_turns=protected)
        resamples = [runner(new_t) for _ in range(k)]

        # Verdict-invariance is a LAW, not a citation-drift rate: a
        # semantics-preserving transform must not change the outcome or the set
        # of failing criteria. Checked for EVERY transform (even when the
        # reference had no FAIL citation) so a PASS->FAIL flip or a newly-failing
        # criterion is caught instead of dropped by the citation loop below.
        outcome_flips = sum(
            1 for v in resamples
            if v.outcome != reference.outcome
            or frozenset(_fail_findings(v)) != reference_fail_set
        )
        if deterministic:
            if outcome_flips > 0:  # no jitter → any flip is a certain violation
                verdict_violations.append(name)
        elif outcome_flips > null_outcome_flips:
            # Stochastic: exact (Fisher) p, Holm-corrected after the loop — same
            # treatment as the citation panel, as its own hypothesis family.
            stochastic_verdict_tests.append(
                (name, fisher_exact_greater(null_outcome_flips, k, outcome_flips, k))
            )

        if not findings:
            per_transform[name] = ProportionEstimate.from_counts(0, 0)
            continue
        # Per-score verdict_invariant mirrors the report-level law (outcome AND
        # fail-set invariant across resamples) so the JSON per-score flag never
        # disagrees with verdict_invariance_violations.
        transform_verdict_invariant = outcome_flips == 0
        agree_sum = 0
        for cid, ref_cited in findings.items():
            # A standalone Verdict legally permits an out-of-range cited_turn_index
            # (only Report range-checks it); remap is total only over 0..n-1, so
            # fall back to a sentinel (-1) no real citation equals — the finding
            # then scores as maximal instability instead of crashing on KeyError.
            expected = remap.get(ref_cited, -1)
            perturbed_flips = sum(1 for v in resamples if _cited_for(v, cid) != expected)
            agree_sum += k - perturbed_flips
            scores.append(
                _build_stability_score(
                    name,
                    cid,
                    ref_cited,
                    expected,
                    k_null=k,
                    k_perturbed=k,
                    null_flips=null_flips[cid],
                    perturbed_flips=perturbed_flips,
                    verdict_invariant=transform_verdict_invariant,
                    deterministic=deterministic,
                    alpha=alpha,
                )
            )
        per_transform[name] = ProportionEstimate.from_counts(agree_sum, len(findings) * k)

    # Holm-correct the stochastic verdict-invariance panel (its own hypothesis
    # family) so a verdict flip is flagged only when significant after correction.
    if stochastic_verdict_tests:
        keep = _holm_significant([p for _, p in stochastic_verdict_tests], alpha)
        verdict_violations.extend(
            name for (name, _), ok in zip(stochastic_verdict_tests, keep, strict=True) if ok
        )

    # Multiplicity correction across the stochastic CITATION panel: the
    # per-comparison gate above would let the family-wise false-positive rate
    # exceed alpha when several (transform, finding) gates are tested. Holm-correct
    # the p-values and re-decide is_unstable. Deterministic runs are exact
    # (certain), not a statistical test, so they keep their per-comparison certainty.
    if not deterministic and scores:
        holm = _holm_significant([s.p_value for s in scores], alpha)
        scores = [
            s.model_copy(update={"is_unstable": ok}) for s, ok in zip(scores, holm, strict=True)
        ]
    # Reconcile each per-score verdict_invariant with the FINAL (gated) violation
    # set so the per-score JSON flag never contradicts verdict_invariance_violations.
    # The raw per-transform flag is outcome_flips==0 (pre-gate); for a jittery
    # stochastic judge an unflagged sub-threshold flip would otherwise read as
    # verdict_invariant=False while the report-level law records no violation.
    if scores:
        violation_set = set(verdict_violations)
        scores = [
            s.model_copy(update={"verdict_invariant": s.transform not in violation_set})
            for s in scores
        ]
    unstable = [s for s in scores if s.is_unstable]
    return CiteMrReport(
        transcript_id=transcript.id,
        reference_outcome=reference.outcome,
        n_findings=len(findings),
        k=k,
        alpha=alpha,
        deterministic=deterministic,
        scores=scores,
        per_transform_stability=per_transform,
        unstable_findings=unstable,
        verdict_invariance_violations=verdict_violations,
        rubric_collisions=list(rubric_collisions),
    )


# ---------------------------------------------------------------------------
# CLI surface — the module owns its parser; cli.build_parser() wires one call.
# ---------------------------------------------------------------------------
def _select_transforms(spec: str) -> dict[str, Transform]:
    names = [s.strip() for s in spec.split(",") if s.strip()]
    if not names:
        # An empty spec (e.g. --transforms "") is a user error, NOT a request to
        # run all four — a silent default-to-all could hide a fat-fingered flag.
        raise ValueError(
            "--transforms is empty; give a comma-separated subset of "
            f"{sorted(DEFAULT_TRANSFORMS)}"
        )
    selected: dict[str, Transform] = {}
    for name in names:
        if name not in DEFAULT_TRANSFORMS:
            raise ValueError(
                f"unknown transform {name!r}; choose from {sorted(DEFAULT_TRANSFORMS)}"
            )
        selected[name] = DEFAULT_TRANSFORMS[name]
    return selected


def _load_transcript(args: argparse.Namespace) -> Transcript:
    if args.transcript:
        return Transcript.model_validate_json(Path(args.transcript).read_text())
    report = Report.model_validate_json(Path(args.from_report).read_text())
    idx = getattr(args, "transcript_index", 0) or 0
    if not 0 <= idx < len(report.transcripts):
        raise SystemExit(
            f"--transcript-index {idx} out of range: the report has "
            f"{len(report.transcripts)} transcript(s) (valid 0..{len(report.transcripts) - 1})"
        )
    return report.transcripts[idx]


def _exit_code(report: CiteMrReport, fail_on_instability: bool) -> int:
    """1 if ``fail_on_instability`` and any unstable finding, verdict-invariance
    violation, OR rubric/transform collision, else 0. A verdict flip under a
    semantics-preserving transform is a law violation; a collision means the
    transform may not be semantics-preserving at all, so the gate result cannot be
    trusted — both gate regardless of the citation-stability findings."""
    if not fail_on_instability:
        return 0
    return 1 if (
        report.unstable_findings
        or report.verdict_invariance_violations
        or report.rubric_collisions
    ) else 0


def _rubric_semantic_collisions(
    rules: dict[str, object], *, persona_name: str = ""
) -> list[str]:
    """Tokens where a default transform could change the criterion under test.

    The fixed fillers, synonym keys/values, and persona aliases are neutral for
    the shipped rubric (asserted in tests), but the CLI accepts ARBITRARY
    rubrics. If a token a transform introduces (a synonym value, a filler word)
    or removes (a synonym key, OR the persona's own name — ``t_rename`` strips it
    from every non-protected turn) coincides with a probe keyword or failure
    signal of the active rubric, the transform is no longer provably semantics-
    preserving for that rubric. Return the colliding tokens so the caller warns.

    ``persona_name`` is the untrusted persona name from the transcript; a name
    equal to a rubric probe keyword would let ``t_rename`` delete a breach trigger
    from a non-protected turn, surfacing a harness artifact as a verdict-invariance
    "law violation" on the deterministic control. Including it here surfaces that.
    """
    def _words(s: str) -> set[str]:
        return set(re.findall(r"[a-z']+", s.lower()))

    rubric_tokens: set[str] = set()
    for rule in rules.values():
        for phrase in (
            *getattr(rule, "probe_turns_contain_any", []),
            *getattr(rule, "failure_if_reply_contains_any", []),
            *getattr(rule, "failure_if_reply_lacks_any", []),
        ):
            rubric_tokens |= _words(phrase)

    transform_tokens = _words(_FILLER_USER) | _words(_FILLER_ASSISTANT)
    for key, val in DEFAULT_SYNONYMS.items():
        transform_tokens |= _words(key) | _words(val)
    transform_tokens |= {a.lower() for a in DEFAULT_ALIAS_RING}
    transform_tokens |= _words(persona_name)  # t_rename strips this from content

    return sorted(rubric_tokens & transform_tokens)


def _cmd_metamorphic(args: argparse.Namespace) -> int:
    if args.k < 1:
        print("error: --k must be >= 1.", file=sys.stderr)
        return 2
    if args.k > _MAX_K:
        print(
            f"error: --k {args.k} exceeds the cap of {_MAX_K} — an LLM run issues "
            "1+(1+#transforms)*k API calls and each Fisher tail computes comb(2k,k). "
            "Raise _MAX_K in metamorphic.py if you genuinely need more.",
            file=sys.stderr,
        )
        return 2
    if not 0.0 < args.alpha < 1.0:
        print("error: --alpha must be in the open interval (0, 1).", file=sys.stderr)
        return 2
    try:
        rubric, rules = parse_rubric_file(args.rubric)
        transcript = _load_transcript(args)
        transforms = _select_transforms(args.transforms)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    collisions = _rubric_semantic_collisions(
        rules, persona_name=transcript.persona.name
    )
    if collisions:
        print(
            "WARNING: this rubric shares token(s) with the default transforms or the "
            f"persona name ({', '.join(collisions)}); a paraphrase, filler, or rename "
            "could alter the criterion under test, so 'semantics-preserving' is NOT "
            "guaranteed for this rubric. The report records them in rubric_collisions "
            "and --fail-on-instability gates on them. Review or pass a curated "
            "--transforms subset.",
            file=sys.stderr,
        )

    if args.mode == "llm":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print(
                "error: --mode llm requested but ANTHROPIC_API_KEY is not set.",
                file=sys.stderr,
            )
            return 2
        runner = llm_runner(rubric)
        deterministic = False
    else:
        runner = heuristic_runner(rubric, rules)
        deterministic = True

    report = run_cite_mr(
        runner, transcript, transforms=transforms, k=args.k,
        alpha=args.alpha, deterministic=deterministic, rubric_collisions=collisions,
    )

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        if deterministic:
            print(
                "NOTE: heuristic CONTROL — stability 1.00 is expected BY "
                "CONSTRUCTION (a faithful-by-construction judge), NOT a finding; "
                "it validates the harness, not any real judge. Stability is "
                "necessary, not sufficient — read it next to gold accuracy. Run "
                "--mode llm to audit a stochastic judge.",
                file=sys.stderr,
            )
        else:
            print(
                "NOTE: LLM judge is non-deterministic; CITE-MR findings are not "
                "reproducible and stability does not imply correctness.",
                file=sys.stderr,
            )
            # Power floor: at small k the two-proportion gate cannot reach alpha
            # even for a citation that flips on every resample, so an all-clear
            # is not evidence of stability. Warn rather than mislead.
            kk = max(report.k, 1)
            max_signal_p = 1.0 / math.comb(2 * kk, kk)
            if max_signal_p >= report.alpha:
                min_k = next(
                    (j for j in range(1, 1000)
                     if 1.0 / math.comb(2 * j, j) < report.alpha),
                    1000,
                )
                print(
                    f"  WARNING: the instability gate is INERT at k={report.k} — "
                    f"even a citation flipping on every resample reaches Fisher "
                    f"p={max_signal_p:.3f} >= alpha={report.alpha}, so the gate "
                    f"can NEVER fire. An all-clear is NOT evidence of stability; "
                    f"raise --k (>= {min_k} for any power, and higher still under "
                    f"the panel's multiplicity correction).",
                    file=sys.stderr,
                )
        print(
            f"CITE-MR — transcript {report.transcript_id} "
            f"({'deterministic heuristic control' if deterministic else 'stochastic LLM'})",
            file=sys.stderr,
        )
        print(
            f"  reference outcome: {report.reference_outcome.value}  "
            f"findings: {report.n_findings}  k={report.k}  alpha={report.alpha}",
            file=sys.stderr,
        )
        for name, est in report.per_transform_stability.items():
            val = "n/a" if est.value is None else f"{est.value:.2f}"
            print(
                f"  {name:<11} stability {val} "
                f"(95% CI {est.lower:.2f}-{est.upper:.2f}, n={est.denominator})",
                file=sys.stderr,
            )
        print(
            f"  unstable findings (gated at alpha): {len(report.unstable_findings)}",
            file=sys.stderr,
        )
        if report.verdict_invariance_violations:
            print(
                "  VERDICT-INVARIANCE VIOLATIONS (transform changed the verdict "
                "itself — a law violation, not citation drift): "
                f"{', '.join(report.verdict_invariance_violations)}",
                file=sys.stderr,
            )
    return _exit_code(report, args.fail_on_instability)


def register_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Add the ``metamorphic`` subcommand and set ``._func``.

    The module owns its CLI surface; ``cli.build_parser()`` adds one wiring call,
    so this module stays independently testable.
    """
    p = subparsers.add_parser(
        "metamorphic",
        help="CITE-MR: metamorphic citation-stability + self-consistency floor.",
    )
    p.add_argument("--rubric", required=True, help="Path to rubric YAML.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--transcript", help="Path to a serialized Transcript JSON.")
    src.add_argument(
        "--from-report", dest="from_report",
        help="Path to a runs/<id>.json Report (pick a transcript with --transcript-index).",
    )
    p.add_argument(
        "--transcript-index", dest="transcript_index", type=int, default=0,
        help="Which transcript from --from-report to audit (default 0). Pick one "
             "with a breach; a no-FAIL transcript yields the vacuous n/a path.",
    )
    p.add_argument(
        "--mode", choices=["heuristic", "llm"], default="heuristic",
        help="heuristic (deterministic control) | llm (gated on ANTHROPIC_API_KEY).",
    )
    p.add_argument(
        "--k", type=int, default=1,
        help="Resamples per transform (default 1; raise for the LLM judge).",
    )
    p.add_argument(
        "--alpha", type=float, default=0.05,
        help="Significance level for the instability gate (default 0.05).",
    )
    p.add_argument(
        "--transforms", default="rename,renumber,insert,paraphrase",
        help="Comma-separated subset of: rename,renumber,insert,paraphrase.",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit the full CiteMrReport JSON to stdout (logs to stderr).",
    )
    p.add_argument(
        "--fail-on-instability", dest="fail_on_instability", action="store_true",
        help="Exit non-zero if any gated citation-instability finding is present.",
    )
    p.set_defaults(_func=_cmd_metamorphic)
