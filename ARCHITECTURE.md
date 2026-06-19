# Architecture

Coehoorn is a thin pipeline. Each stage takes a typed input, produces a typed
output, and is independently testable. The whole thing fits in one head.

```
            rubric.yaml
                │
                ▼                                       ┌──────────────────┐
       rubric_parser.parse_rubric_file()                │ schemas.py       │
                │                                       │   Pydantic v2    │
                ▼                                       │   wire contract  │
   (Rubric, {criterion_id: HeuristicCriterionRule})     │   extra="forbid" │
                │                                       │   illegal states │
                ▼                                       │   unrepresentable│
       personas.generate_personas_*()                   └──────────────────┘
                │
                ▼
              [Persona, …]
                │
                ▼
       conversation.run_conversations(...)          (asyncio.gather, bounded
                │                                     semaphore; no framework)
                ▼
              [Transcript, …]
                │
                ▼
       judge.judge_all(...)                          (per transcript; LLM mode
                │                                     retries once on validation
                ▼                                     failure, then hard-fails)
              [Verdict, …]   ── pass / fail / abstain
                │
                ▼
       aggregator.build_report(...)                  (Report validates 1:1
                │                                     transcript↔verdict, full
                ▼                                     criterion coverage, every
              Report                                  cited index in range)
              │   │   │
              │   │   └─► report_html.write_report_html(...) ─► the Siege Survey (.html)
              │   └─────► aggregator.write_report_json(...)  ─► runs/<id>.json
              │
              ▼
       aggregator.compare_to_expected(...)  ─►  metrics.metrics_from_comparison(...)
       (full persona×criterion confusion grid)       (precision/recall/F1/κ + CIs)

       meta_eval.evaluate_gold(...)  ─►  audit the judge against a frozen gold set
                │
                ├─► mutants.run_mutation_score(...)  ─►  plant broken judges, prove the gold catches each
                └─► metamorphic.run_cite_mr(...)     ─►  semantics-preserving transforms; verdict + citation must hold
```

## Components

| file | role |
|---|---|
| `schemas.py` | The Pydantic wire contract. `CriterionStatus` and `VerdictOutcome` are tri-state (`pass`/`fail`/`abstain`). Validators make illegal verdicts unconstructable. All models `extra="forbid"`. |
| `rubric_parser.py` | YAML → `(Rubric, {criterion_id: HeuristicCriterionRule})`. Heuristic rules live outside `Criterion` so the schema stays pure. |
| `personas.py` | `generate_personas_heuristic` (curated pool) and `generate_personas_llm` (Anthropic Opus). |
| `agent_adapter.py` | `HttpAgentAdapter` and `CallableAdapter`, both implementing the `AgentCall` protocol. |
| `conversation.py` | `run_conversations(...)` — fans out N personas with `asyncio.gather` + a bounded semaphore. Deterministic transcript ids (`t-<persona-id>`). |
| `judge.py` | `judge_transcript_heuristic` (rule-based, offline) and `judge_transcript_llm` (Sonnet, retry-once, hard-fail). Discovery semantics: any breach → `fail`; `weight`/`failure_is_critical` rank the worst moment. |
| `aggregator.py` | `build_report`, JSON IO, `pin_report_timestamps` (for byte-stable canonical artifacts), and `compare_to_expected` (the full confusion grid, abstentions excluded). |
| `metrics.py` | Wilson intervals, precision/recall/specificity/F1/balanced-accuracy/Cohen's κ. Stdlib only. |
| `meta_eval.py` | Audit the auditor: score a judge against a frozen gold set, with always-breach / always-hold baselines. Carries the optional `gold_cited_turn` ground-truth anchor and the verdict-level `VerdictPredictor` seam the mutation score scores against. |
| `mutants.py` | **Mutation-test the meta-eval.** Plant six broken "mutant" judges (relocate / off-by-one citation, force-pass, polarity flip, abstain→pass, drop tool-order) and score how many the gold set catches. A citation faithfulness check (against `gold_cited_turn`) catches the citation mutants a status-only confusion matrix is blind to. Honest decomposition: load-bearing vs confirmatory; survivors name the missing gold cell. |
| `metamorphic.py` | **CITE-MR — metamorphic citation-stability.** Apply semantics-preserving transcript transforms (rename / renumber / insert / paraphrase, each returning a remap) and assert verdict-invariance *and* that the citation tracks the remap. Fisher's exact one-sided test + Holm step-down gate the instability call; the deterministic heuristic judge is the faithful-by-construction control. Stdlib-only. |
| `overfit.py` | **Judge-overfit audit (`overfit-audit`).** Multiplicity-corrected (Bonferroni) Wilson lower bound for a gold-selected judge config, a generalization gap measured against fresh conjecturer-generated held-out sieges, and a sample-k saturation curve (resamples only, never a gold-set-size asymptote). Offline and keyless. |
| `cascade.py` | **Cheap→expensive tier telemetry.** Emits `{alpha, disagreement_rate, lossless_violations}` per judging boundary; the deterministic→gold boundary is measured at zero model spend, the heuristic→LLM boundary is emitted `measured=false` rather than fabricated. |
| `distill.py` | **Distill the jury into the floor (`distill-floor`).** Run a judge jury over a conjectured residual, report correlation-corrected *effective* votes, mine a candidate deterministic rule, and holdout-gate it on a separate slice before promotion; report the out-of-sample replaceable fraction. The live LLM jury is key-gated. |
| `selective_risk.py` | **Selective-risk certificate (`selective-risk`).** Distribution-free (Hoeffding) conformal upper bound on the judge's error over unseen conjectured sieges, beside the asymptotic Wilson upper bound, with an exact width-vs-N convergence curve. Key-gated for the live jury. |
| `report_html.py` | The self-contained Siege Survey. No JS, no assets, computed inline SVG, strict escaping. Pure Python (no template engine). |
| `cli.py` | `coehoorn run` / `compare` / `meta-eval` / `mutation-score` / `metamorphic` / `overfit-audit` / `distill-floor` / `selective-risk` / `self-play`. argparse; `--json`, opt-in gates `--fail-on-breach` / `--min-score` / `--fail-on-instability` / `--min-corrected-recall-lower` / `--min-replaceable-fraction` / `--max-risk-upper`. The extension subcommands self-register via `register_subparser`. |
| `mcp_server.py` | *Optional extra.* MCP server exposing a siege as a tool. Lazily imported. |
| `inspect_export.py` | *Optional extra.* Report → Inspect AI `EvalLog`. Lazily imported, fail-loud on schema drift. |

## The trust boundary

The judge sits at the trust boundary: it reads a transcript and emits a verdict
that flows into a Report. Three layers keep a bad verdict from propagating:

1. **Schema invariants.** A `fail` criterion must cite a turn; a `pass`/`abstain`
   must not. A `fail` verdict needs a `worst_moment_turn_index` equal to one of
   its cited failed turns; a `pass`/`abstain` forbids it. A `Report` rejects any
   cited index that doesn't resolve against the linked transcript, and any
   verdict whose criterion coverage doesn't match the rubric exactly. These are
   raised at construction; a malformed verdict cannot exist.
2. **Retry with parse-error context.** On the first validation failure of an LLM
   judge call, the parser error is fed back once. No silent fallback, no default
   verdict.
3. **Explicit abstention.** A criterion the judge cannot decide is `abstain`, not
   a guessed pass. The meta-eval excludes abstentions from precision/recall and
   reports the rate separately.

What the boundary does **not** guarantee: *faithfulness*. A judge can cite the
wrong turn and still pass validation. The schema anchors a verdict to real,
in-range evidence; it does not certify the reasoning attached to it. This limit
is stated, unprompted, in the README.

## Meta-eval: Coehoorn judges its own judge

`meta_eval.py` runs the judge over a hand-labeled gold set and builds the same
confusion matrix the product reports for agents — applied to the judge itself —
beside always-breach / always-hold baselines. The gold set carries adversarial
near-misses where the keyword heuristic is wrong on purpose, so the scorecard is
honestly below 1.0; the gap is the argument for the LLM judge. CI gates on the
Wilson interval floor. See [`docs/EVAL.md`](docs/EVAL.md).

## Citation integrity: measuring the faithfulness the schema can't guarantee

The trust boundary above is explicit that it does **not** certify *faithfulness*
— a judge can cite the wrong turn and still pass validation. Two commands close
the loop by *measuring* that gap instead of asserting it away. Both extend the
meta-eval; both are stdlib-only and deterministic in their default control mode.

- **`coehoorn mutation-score` (`mutants.py`) — does the gold set actually have
  teeth?** It plants six broken judges and checks the gold catches each. The
  load-bearing two (M1 relocate-citation, M4 off-by-one) are *citation* bugs the
  status confusion matrix is structurally blind to; they are caught only because
  the gold now carries a `gold_cited_turn` anchor and the score checks citation
  faithfulness against it. The shipped score is an honest **4/6** — survivors M5
  (abstain→pass) and M6 (drop tool-order) *name the missing gold cell* rather than
  being hidden. The score is a deterministic count, not a sampled statistic, so it
  carries no confidence interval — claiming one would be a category error
  (ADR-0011).
- **`coehoorn metamorphic` (`metamorphic.py`) — is a citation stable under
  semantics-preserving edits?** It rewrites the transcript in ways that must not
  change the verdict (rename the persona, renumber turns, insert a neutral turn,
  paraphrase a non-cited turn) and asserts both that the outcome holds and that
  the cited turn tracks the transform's remap. The deterministic heuristic judge
  is faithful **by construction**, so its 1.00 stability validates the *harness*,
  not any real judge — the command says so on every run. The real target is the
  stochastic LLM judge (`--mode llm`), where instability is gated by Fisher's
  exact one-sided test with a Holm step-down correction across the transform
  family, not a normal-approximation z-test (ADR-0011).

## Stack choices (and what was rejected)

The framework rejections are load-bearing and recorded with reasoning in
[`docs/adr/`](docs/adr/): no LangGraph (asyncio fan-out, ADR-0004), no DSPy
(the guarantee is structural, ADR-0005), no pydantic-ai (its retry would hide
the mechanism we want visible, ADR-0006), no observability SaaS (local/no-telemetry posture,
ADR-0007), no Jinja2 (the report is computed, not templated, ADR-0008), and a
Fisher's-exact / Holm gate rather than a normal-approximation z-test or a
binomial CI on a deterministic count for the citation-integrity suite (ADR-0011).

## Extending it

- **New agent adapter:** implement `async __call__(self, conversation: list[dict])
  -> str`. See `HttpAgentAdapter` / `CallableAdapter`.
- **New archetype:** add to `Archetype` in `schemas.py`, add probes in
  `conversation.py`, add curated personas in `personas.py`. The fort diagram is
  keyed to the archetype set, so it stays correct automatically.
- **New judge mode:** a function `(transcript, rubric, …) -> Verdict` satisfying
  the schema. The validators run unchanged on its output.

## A note on the siege vocabulary

The report's *chrome* uses five glossed terms — **siege, approach, breach, held,
worst moment**. The wider fortification lexicon is intentionally kept out of the
UI and lives only here, for readers who want the metaphor in full: the *ditch*
is the schema trust boundary; an *approach* (siege-engineering: a *sap*) is one
persona's advance; the *glacis* is the rubric's outer slope of expectations; a
*breach* is a gap in a *wall segment* (a criterion). The restraint is deliberate:
distinctiveness comes from the first five terms; the rest would be costume.
