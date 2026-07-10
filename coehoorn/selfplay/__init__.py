"""Guide-gated self-play attack conjecturer (the flagship).

A conjecturer GENERATES new adversarial scenarios — personas + probe scripts —
that go *beyond* the fixed archetype probe scripts, each SEED-GROUNDED in a
logged near-miss/breach. A GUIDE scores every generated attack for relatedness
to its seed and for non-degeneracy, and the conjecturer's reward is *multiplied*
by that guide score: the Seed-Grounded-Score (SGS) anti-degeneration fix. A
conjecturer that drifts off its seed, or that emits a degenerate attack to farm
reward, is scored to (near) zero rather than rewarded.

The reward is made ungameable by reusing Coehoorn's existing rigor as the guide:

* the citation-to-turn Pydantic invariant (``schemas``) — a "successful" attack
  must yield a transcript+verdict whose breach cites a turn that actually exists;
* the Judge Mutation Score (``mutants``) — attack-success is only trusted when
  the judge measuring it clears its calibration floor;
* CITE-MR (``metamorphic``) — a claimed breach is only trusted when its citation
  is stable under semantics-preserving transforms, not a one-off flicker.

Offline everything runs on a deterministic stub model + a heuristic judge, which
proves the *plumbing* end-to-end with no credentials. The live, measured
attack-success-rate (live Opus personas, Sonnet judge -> ASR + pass^k) needs
ANTHROPIC_API_KEY; that path is clearly marked and never fabricated by the stub.
"""
from __future__ import annotations

from .conjecturer import (
    ConjecturedAttack,
    Conjecturer,
    ConjecturerModel,
    RawConjecture,
    Seed,
    deterministic_stub_model,
    live_anthropic_model,
    seed_from_breach,
    seed_from_gold_case,
    seeds_from_gold,
)
from .guide import GuideScore, score_attack
from .loop import (
    AttackEvaluation,
    SelfPlayRound,
    citation_invariant_holds,
    citation_stability_gate,
    evaluate_attack,
    judge_trust_gate,
    live_self_play_round,
    run_scripted_conversation,
    run_self_play_round,
)

__all__ = [
    "AttackEvaluation",
    "ConjecturedAttack",
    "Conjecturer",
    "ConjecturerModel",
    "GuideScore",
    "RawConjecture",
    "Seed",
    "SelfPlayRound",
    "citation_invariant_holds",
    "citation_stability_gate",
    "deterministic_stub_model",
    "evaluate_attack",
    "judge_trust_gate",
    "live_anthropic_model",
    "live_self_play_round",
    "run_scripted_conversation",
    "run_self_play_round",
    "score_attack",
    "seed_from_breach",
    "seed_from_gold_case",
    "seeds_from_gold",
]
