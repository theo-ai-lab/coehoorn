# Changelog

All notable changes to Coehoorn are recorded here. Versions follow
[semantic versioning](https://semver.org/).

## [0.2.0] — unreleased

### Added
- **Tool-use attack surface (OWASP Agentic ASI02 / ASI03).** Transcripts now
  capture the agent's tool calls; a rubric can declare `forbidden_tools` (tool
  misuse) and `tool_must_precede` approval/order pairs (privilege bypass), and
  the heuristic judge cites the exact turn — order, not presence, so an agent
  that simply refuses is never charged. Ships a committed tool-siege sample
  (`runs/sample-tools/`) and an example rubric (`examples/rubric_tools.yaml`).
- **SARIF + JUnit output** (`coehoorn run --emit sarif,junit`) plus a GitHub
  Action that uploads breaches to the Security tab — drop-in CI/security
  integration; each finding is located at its cited turn. Stdlib-only.
- **Judge meta-eval ("audit the auditor").** `coehoorn meta-eval` scores the
  judge against a frozen, hand-labeled gold fixture and reports a full
  confusion matrix with precision / recall / specificity / balanced accuracy /
  Cohen's kappa — each proportion paired with a Wilson 95% interval — next to
  always-breach and always-hold baselines. The gold set includes adversarial
  near-misses where the keyword heuristic is wrong on purpose.
- **Judge Mutation Score (`coehoorn mutation-score`).** Mutation-tests the
  meta-eval itself: plants six broken "mutant" judges (relocate-citation,
  off-by-one citation, force-pass, polarity flip, abstain→pass, drop tool-order)
  and reports how many the gold set catches. A citation-faithfulness check —
  anchored to a new optional `gold_cited_turn` ground-truth field on the gold
  cells — catches the two *citation* mutants that a status-only confusion matrix
  is structurally blind to. Reports an honest **4/6** with a load-bearing /
  confirmatory split, and each survivor names the missing gold cell. The score is
  a deterministic count, not a sampled statistic, so it carries no confidence
  interval by design (see ADR-0011). `--min-score` gates it from CI. Stdlib-only.
- **Metamorphic citation-stability — CITE-MR (`coehoorn metamorphic`).** Applies
  semantics-preserving transcript transforms (rename persona, renumber turns,
  insert a neutral turn, paraphrase a non-cited turn) and asserts both that the
  verdict is invariant *and* that the cited turn tracks each transform's remap.
  The deterministic heuristic judge is faithful by construction, so it is the
  control (its 1.00 stability validates the harness, stated on every run); the
  stochastic LLM judge (`--mode llm`) is the real audit target, where instability
  is gated by **Fisher's exact one-sided test with a Holm step-down correction**
  across the transform family — not a normal-approximation z-test (see ADR-0011).
  `--fail-on-instability` gates it from CI. Stdlib-only.
- **`metrics` module.** Wilson score intervals, precision/recall/F1, balanced
  accuracy, and Cohen's kappa — dependency-free (no SciPy).
- **Explicit `ABSTAIN` state.** `CriterionStatus` and `VerdictOutcome` are now
  three-valued (`pass` / `fail` / `abstain`); a judgment that cannot be made is
  recorded as an abstention and excluded from precision/recall rather than
  silently counted as a pass.
- **Confusion matrix in `compare`.** Adds true negatives and an abstention
  count over the full persona × criterion grid; `compare` and the HTML report
  now lead with the matrix and the per-rate intervals.
- **The "Siege Survey" HTML report** — a self-contained, no-JS,
  archetype-keyed fort diagram (inline SVG), with breaches drawn as wall gaps.
  Its calibration panel shows the judge's **honest gold score** (balanced
  accuracy ≈0.66, with always-breach/always-hold baselines and Wilson
  intervals), not a self-fulfilling 1.00 against its own expected fixture.
- **CLI ergonomics:** `coehoorn run --json` (stable summary to stdout, logs to
  stderr) and opt-in `--fail-on-breach` for gate-style CI use.
- **Optional extras (lazy):** `coehoorn[mcp]` exposes a siege as an MCP tool;
  `coehoorn[inspect]` exports a run to an Inspect AI `EvalLog`. Neither is
  imported on the core path.

### Changed
- **Discovery semantics:** any criterion breach now fails the transcript;
  tolerance/threshold policy belongs to a downstream gate, not to Coehoorn. The
  rubric's `weight` and `failure_is_critical` now rank worst-moment severity.
- The committed sample report is byte-reproducible by construction.
- **Removed the Jinja2 dependency** — the report renders in pure Python.

### Fixed
- The sample-report builder no longer mutates the committed sample on every run
  (pinned run id + timestamps).
- Removed a dead `overall_pass = True` coercion in the heuristic judge that
  could have masked a missed breach as a pass.

## [0.1.0]

- Initial rubric-driven, multi-turn, cited-evidence harness: schema-enforced
  verdicts, heuristic + LLM modes, HTTP agent adapter, deterministic sample.
