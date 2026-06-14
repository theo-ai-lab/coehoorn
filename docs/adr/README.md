# Architecture Decision Record

Decisions that shaped Coehoorn, including the ones to *not* do things. Each entry
names the rejected alternative so it can be argued with. Reversibility:
**reversible** (cheap to change later), **costly** (migration / breaking the wire
contract), **one-way** (effectively a rebuild).

---

### ADR-0001 — The trust boundary is a set of Pydantic validators
- **Status:** accepted · **Reversibility:** costly
- **Decision:** Verdict invariants live in `schemas.py` as `model_validator`s, so
  illegal states cannot be constructed: a failed criterion must cite a turn; a
  pass or abstention must not; a `Report` cross-checks that every cited index
  resolves against the linked transcript.
- **Because:** the product's claim is structural integrity of verdicts. Enforcing
  it in the schema means every mode — heuristic, LLM, future — inherits it for
  free, and the guarantee survives a bad prompt.
- **Rejected:** enforce citations by prompt instruction and hope. That is the
  exact failure mode Coehoorn exists to catch.

### ADR-0002 — Three-valued status with an explicit ABSTAIN
- **Status:** accepted · **Reversibility:** costly
- **Decision:** `CriterionStatus` and `VerdictOutcome` are `pass`/`fail`/`abstain`.
  A judgment that cannot be made is an abstention, excluded from precision/recall
  and reported as a coverage rate.
- **Because:** the previous binary collapsed "couldn't decide" into "passed,"
  which silently inflated the pass column and corrupted the false-negative count
  in the very meta-eval that pins CI thresholds. The tri-state makes the illegal
  "failure with no evidence" and the dishonest "abstention as pass" both
  unrepresentable.
- **Rejected:** a `passed: bool` plus an `abstained: bool` flag — which permits
  the illegal combination `passed=False, abstained=True`. An enum makes the bad
  state impossible rather than merely discouraged.

### ADR-0003 — Discovery semantics: any breach fails the transcript
- **Status:** accepted · **Reversibility:** costly
- **Decision:** a transcript's outcome is `fail` if any criterion breached,
  `abstain` if all abstained, else `pass`. The rubric's `weight` and
  `failure_is_critical` rank the worst moment; they do not apply a tolerance.
- **Because:** Coehoorn *discovers* failures; deciding whether a breach should fail
  a build is a downstream gate's policy, not the harness's. Folding a tolerance
  threshold into the outcome would blur the discovery layer into a gate.
- **Rejected:** a weighted pass-threshold at the transcript level. It belongs to a
  consumer that owns the tolerance decision.

### ADR-0004 — No LangGraph; asyncio fan-out
- **Status:** accepted · **Reversibility:** reversible
- **Decision:** the pipeline (parse → personas → conversations → judge →
  aggregate) is a fan-out that `asyncio.gather` with a bounded semaphore handles
  in ~20 lines.
- **Because:** a state-machine framework would add indirection between the test
  reader and the actual control flow without buying anything for a linear
  fan-out. Directly testable with `pytest-asyncio`.
- **Rejected:** LangGraph. Reconsider only if real human-in-the-loop branching or
  durable resumption appears.

### ADR-0005 — No DSPy
- **Status:** accepted · **Reversibility:** reversible
- **Decision:** keep hand-written few-shot prompt builders.
- **Because:** the differentiator is *structural* (the schema enforces citation),
  not prompt quality. DSPy optimizes prompts; it does not move the guarantee, and
  it fights the zero-setup reproducible demo. Measure the judge first
  (`meta_eval`); optimization is a later, separate step that the measurement
  layer would gate.
- **Rejected:** DSPy-optimized persona/judge prompts.

### ADR-0006 — No pydantic-ai
- **Status:** accepted · **Reversibility:** reversible
- **Decision:** raw Anthropic SDK + an explicit JSON-schema prompt + Pydantic
  validate + one retry-with-error-context + hard-fail.
- **Because:** the visible mechanics of "structured output with a real validation
  boundary and no silent fallback" *are* the point. A framework that hides the
  retry/validate loop would hide the thing worth showing.
- **Rejected:** pydantic-ai agents.

### ADR-0007 — No observability SaaS; stdlib-only metrics
- **Status:** accepted · **Reversibility:** reversible
- **Decision:** the validated `Report` JSON plus the self-contained HTML are the
  only trace artifacts. Metrics (Wilson, precision/recall/F1/κ) are implemented
  in stdlib `math`.
- **Because:** local / no-telemetry / no external callbacks is a load-bearing
  property, not a default. Braintrust/Langfuse would contradict it, and pulling
  SciPy for a handful of closed-form statistics is unjustified.
- **Rejected:** Braintrust, Langfuse, SciPy.

### ADR-0008 — Render the report in pure Python; drop Jinja2
- **Status:** accepted · **Reversibility:** reversible
- **Decision:** `report_html.py` builds the document (including computed SVG
  geometry) with f-strings and strict `html.escape`, removing the Jinja2
  dependency.
- **Because:** the fort geometry is computed, not templated, so a template engine
  added a dependency for the static parts while fighting the dynamic ones.
  Dropping it took the runtime dependency count from six to five.
- **Rejected:** keep Jinja2. Trade-off: escaping is now the author's
  responsibility — handled by escaping every dynamic insertion (the report embeds
  untrusted agent replies).

### ADR-0009 — Wilson intervals, and gate on the lower bound
- **Status:** accepted · **Reversibility:** reversible
- **Decision:** every reported proportion carries a Wilson 95% interval; the CI
  regression gate tests the interval *floor*, not the point estimate.
- **Because:** with a small, partly-stochastic gold set, a point-estimate gate
  flakes. Gating on the lower bound is both robust and the honest-reporting
  discipline applied to the project's own CI.
- **Rejected:** bare point-estimate thresholds.

### ADR-0010 — MCP and Inspect as lazy optional extras
- **Status:** accepted · **Reversibility:** reversible
- **Decision:** `coehoorn[mcp]` (an MCP server) and `coehoorn[inspect]` (Inspect AI
  `EvalLog` export) are optional dependencies, imported lazily; the core path
  imports neither. A clean-interpreter test asserts the core never pulls them in;
  the exporter fails loud naming the version seam rather than emitting a malformed
  log.
- **Because:** they are real integration signals (callable-by-agents; the on-ramp
  to a standard eval viewer) but must not tax the 99% offline path or its
  dependency surface.
- **Rejected:** making either a core dependency.

### ADR-0011 — Citation-integrity suite: mutation score + metamorphic stability, gated with the right statistics
- **Status:** accepted · **Reversibility:** reversible
- **Decision:** measure the one property the schema cannot guarantee —
  *faithfulness* of a citation — with two stdlib-only commands that extend the
  meta-eval. (1) `coehoorn mutation-score` plants six broken "mutant" judges and
  scores how many the gold catches; the two discriminating mutants corrupt only
  the cited turn, caught via a new optional `gold_cited_turn` ground-truth anchor
  on the gold cells. (2) `coehoorn metamorphic` (CITE-MR) applies
  semantics-preserving transcript transforms and asserts both verdict-invariance
  and that the citation tracks each transform's remap. The deterministic judge is
  the by-construction control; the stochastic LLM judge is the real target.
- **Because:** the README states plainly that the schema anchors a verdict to
  real evidence but does not certify the *reasoning* — a judge can cite the wrong
  turn and pass validation. A status-only confusion matrix is structurally blind
  to citation bugs, so the meta-eval alone cannot detect that failure. The
  mutation score proves the gold set can actually catch a relocated citation
  (load-bearing M1/M4), and CITE-MR proves a citation does not drift under edits
  that should not move it. Faithfulness becomes *measured*, with the residual gap
  named (survivors M5/M6 point at the missing gold cells), rather than asserted
  away.
- **Rejected:**
  - A **Wilson/binomial confidence interval on the mutation score.** The score is
    a deterministic count over a fixed mutant set on a frozen gold — not a sample
    from a population. An interval would imply a sampling process that does not
    exist and manufacture false precision, the exact failure the project calls
    out. The score ships as a bare `caught/planted` with a load-bearing-vs-
    confirmatory decomposition instead.
  - A **normal-approximation two-proportion z-test** for the metamorphic
    instability gate. At a handful of resamples per transform the z-test is
    anti-conservative and over-flags. The gate is a **one-sided Fisher's exact
    test** with a **Holm step-down** correction across the four-transform family
    (FWER control); the z-statistic is retained as informational only.
  - **Enforcing faithfulness in the schema.** A turn index can be validated as
    in-range, but "is this the *right* turn" is a judgment, not a constructible
    invariant. It is measured and reported, not pretended into a guarantee.
