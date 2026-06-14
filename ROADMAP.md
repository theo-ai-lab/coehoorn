# Roadmap

Coehoorn is intentionally small. This roadmap is as much about what it will *not*
become as what it will. The guardrail is the same as the rest of the project:
every addition has to earn its place, and the core stays lean (five runtime
dependencies; see [`docs/adr/`](docs/adr/)).

## Shipped (v0.2)

- Schema-enforced cited-evidence verdicts; three-valued (`pass`/`fail`/`abstain`).
- Heuristic (offline, deterministic) and LLM modes behind one wire contract.
- Self-auditing meta-eval (precision/recall/specificity with Wilson intervals,
  balanced accuracy, Cohen's kappa) against a frozen gold set with baselines.
- Citation-integrity suite: a **Judge Mutation Score** (`coehoorn mutation-score`)
  that mutation-tests the gold set against six planted broken judges (honest 4/6,
  load-bearing vs confirmatory split, survivors named), and **metamorphic
  citation-stability / CITE-MR** (`coehoorn metamorphic`) that gates verdict- and
  citation-invariance under semantics-preserving transforms with Fisher's exact +
  Holm. Stdlib-only; the deterministic judge is the by-construction control.
- The self-contained "Siege Survey" HTML report.
- Tool-use attack surface — OWASP Agentic **ASI02** (tool misuse) and **ASI03**
  (privilege/approval bypass).
- CI outputs: `--json`, `--fail-on-breach`, **SARIF + JUnit**, and a GitHub Action.
- Optional extras: an MCP server and an Inspect AI exporter.

## Next

- **Verify the LLM path live.** One bounded run of the Opus/Sonnet path on a public
  benchmark slice (τ-bench-style tool-agent-user tasks), with precision/recall and
  Wilson intervals published in [`MISTAKES.md`](./MISTAKES.md). *(The single
  highest-value open item.)*
- **Inter-annotator agreement on the gold set.** Add a second human labeler and
  report Krippendorff's α, so the gold labels' reliability is itself measured.
- **Wider agentic coverage.** Memory/context-poisoning (ASI06) and inter-agent
  communication (ASI07) checks, extending the tool-policy model.

## Maybe (only if it earns its place)

- A small ensemble/panel judge (multiple prompt strategies, majority verdict).
- Streaming-response handling for token-by-token agents.
- A second built-in agent adapter (beyond HTTP / in-process callable).

## Deliberately out of scope

These are real techniques; they are *not* what this tool is for, and adding them
would fight its thesis:

- **A self-evolving / learning adversary.** Coehoorn is a transparent, reproducible
  harness, not an automated attack-search loop.
- **Formal verification of judge reasoning.** The schema guarantees *cited* evidence,
  not *correct* reasoning — and it says so. Proofs are a different project.
- **Observability-platform telemetry.** Local / no-telemetry / no-callbacks is a
  load-bearing property, not a default.

## How to influence it

Open an issue with a concrete failure mode you wish it caught, or a rubric it judged
wrong. Real adversarial cases (especially ones the heuristic judge gets wrong) are
the most useful contribution — they go straight into the gold set.
