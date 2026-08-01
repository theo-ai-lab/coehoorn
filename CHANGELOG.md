# Changelog

All notable changes to Coehoorn are recorded here. Versions follow
[semantic versioning](https://semver.org/).

## [0.2.0] — unreleased

> Version-bumped in `pyproject.toml` on 2026-07-04; the `v0.2.0` tag and the
> first PyPI publish are **pending**. Pushing the tag runs
> `.github/workflows/release.yml` (OIDC trusted publishing + a clean-env
> install smoke of the published wheel).

### Added
- **Engagements (`coehoorn engage`, `coehoorn/engagement.py`, `docs/engagements/`).**
  A URL flag is not an engagement. An engagement is a committed definition — a
  named target, a prose rules-of-engagement document, the exact probe scripts
  that will be sent, an explicit `authorized:` flag, and a scope allowlist
  **enforced in code before any socket is opened**. The runner is
  target-agnostic: it drives the existing `HttpAgentAdapter` at a URL resolved
  from `--target` / the engagement / `AGENT_ENDPOINT`, judges with the existing
  offline judge, redacts through the existing `RedactionPolicy`, and writes a
  third artifact beside the report and the HTML — `<run_id>.engagement.json`,
  carrying the scope rules applied, the redacted target, every approach that
  never landed, and every finding cited to a turn that resolves.

  The scope is an allowlist because a runner that dials an operator-supplied
  URL is SSRF surface. Hosts match exactly (no wildcards, so a subdomain needs
  its own line), and loopback/private/link-local/reserved/multicast/unspecified
  addresses — including IPv4-mapped IPv6 forms of them — are refused *even when
  the operator allowlisted the host*, unless the engagement carries a written
  `allow_private_addresses: true`. DNS is resolved and every returned address
  is checked, so a name that resolves inward is refused too; a resolution
  failure is a refusal, not a shrug. Each refusal names the rule
  (`engagement.authorized`, `scope.allowed_hosts`,
  `scope.allow_private_addresses`, …), exits 2, and passes the refused URL
  through the redaction boundary so a pasted credential is not echoed into a CI
  log. The URL the check *returns* is the representation every clause was
  decided on — dot segments removed — and it is what the runner dials: an
  adversarial sweep of the first cut found two parse differentials where the
  check decided on `urlsplit`'s view and handed the operator's raw string to
  the transport (`/chat/../../admin` satisfied a `/chat` prefix and routes to
  `/admin`; a URL carrying `\n` was judged in the sanitised form `urlsplit`
  produces and dialled in the raw one). Control characters are now refused
  rather than silently stripped, and dot segments — including percent-encoded
  ones — are resolved before the prefix clause. **Not** defended against: a DNS
  rebind between the check and the connect, which would need an address-pinned
  transport.

  What this does and does not demonstrate is stated in the README and in the
  engagement docs: the spine is proven end to end over a real socket against
  `apps/approval-stub` (a rehearsal target this repo wrote, with a **planted,
  documented** weakness — `uv run python scripts/rehearse_engagement.py`), and
  the first real target is **defined, scoped and deliberately unauthorized**.
  No third-party agent has been sieged.
- **Redaction as a boundary (`coehoorn/redact.py`, `--redact off|standard|strict`).**
  A siege transcript is someone else's user data, and it reaches five
  persistence paths (`report.json`, the self-contained HTML, SARIF, JUnit,
  stdout). The policy is applied once, to the `Transcript`, *before* it is
  judged or assembled — so every emitter is clean by construction rather than
  by five separate promises. `standard` covers credentials, email, US SSNs and
  Luhn-valid card numbers; `strict` adds phone, IPv4 and hex digests; a rubric
  may declare its own `redaction: patterns:` block (which applies even at
  `off`, being a stated requirement rather than a default). URL credentials —
  `user:pass@host` userinfo and credential-bearing query parameters — are
  stripped by the same `text` rule every persisted string goes through, so the
  `agent_endpoint`, a transcript quoting a URL, and the wire error that quotes
  the request URL are all cleaned identically; the host and path survive,
  because which agent was besieged is the record. There is deliberately
  **no Shannon-entropy fallback**: entropy fires on base64 and JSON, which is
  most of a tool-calling transcript. A per-emitter leak matrix and a
  `--redact off` control test keep the boundary honest.
- **Per-approach error outcomes (`coehoorn/errors.py`).** An approach that
  fails on the wire is classified — `retryable` (429/503/timeout, honouring
  `Retry-After` in both wire forms), `caller_fault` (401/404/400) or `system` —
  and carried in the report as an `ApproachError`. `Retry-After` is recorded
  only on `retryable`: targets do send it on a 403 (GitHub's secondary rate
  limit, Cloudflare), but "come back in 60s" is false advice for a wrong
  credential, and the record refuses the pair outright. A report carrying one is
  `partial`, and says so in the HTML header, the `--json` summary and the human
  log. A wire failure can never be folded into the pass column: the schema
  refuses to record one approach as both a transcript and an error.

- **MCP tool-poisoning attack pack (`coehoorn mcp-siege`).** A runnable,
  offline, byte-reproducible tool-poisoning fixture — three archetypes, hero
  first: **rug-pull** (a benign tool whose description mutates malicious
  mid-session; the flip is cited to its exact turn — the temporal localization a
  status-only verdict cannot make), **tool-description poisoning** (malicious
  instructions embedded in a tool's `description` field), and **cross-server
  shadowing** (a look-alike tool from a second server intercepts a legitimate
  one). Drives a deterministically-vulnerable agent through an in-process
  **loopback MCP fixture** — a model of MCP's newline-delimited-JSON stdio
  transport with no subprocess, no socket, and no `mcp` dependency — so the pack
  runs keyless. Maps to OWASP Agentic 2026 **ASI04** (Supply Chain), **ASI01**
  (Goal Hijack), **ASI02** (Tool Misuse), **ASI07** (Insecure Inter-Agent
  Communication), and **ASI03** (Privilege Abuse); see `docs/coverage-map.md` §5.
  Ships committed sample reports (`runs/sample-mcp/`) and a rubric
  (`examples/rubric_mcp.yaml`). The live LLM-victim path is a documented seam,
  not faked by the stub.
- **Pinned OWASP Agentic taxonomy alignment.** The ASI01–ASI10 references across
  the docs and rubrics are pinned to the OWASP Top 10 for Agentic Applications
  (2026) edition and covered by a drift-detecting test (`tests/test_taxonomy.py`),
  so a future OWASP revision fails the suite loudly instead of leaving stale ids
  or titles in the coverage map.
- **Plimsoll trace export (same-org dogfooding).** `coehoorn/trace_export.py`
  converts a finished siege into [Plimsoll](https://github.com/theo-ai-lab/plimsoll)'s
  native trace format — plain JSON, stdlib-only, no new dependency — so a
  second, span-level policy gate maintained in the same org can independently
  re-derive the verdict from the raw run record. Ships the committed export of
  the tool-siege sample (`runs/sample-tools/traces/`, byte-repro gated), a
  policy mirroring `rubric_tools.yaml` (`examples/plimsoll_policy_tools.json`),
  a differential test (the planted breaches must fail the gate; a compliant
  twin must pass it — skipped when plimsoll isn't installed), and a manual-only
  agreement workflow (`.github/workflows/trace-gate.yml`) to be activated once
  Plimsoll ships on PyPI. Span timing in exported traces is synthetic-ordinal
  (turn order, not latency) and labeled as such in the trace metadata.
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
- **Self-play attack conjecturer (`coehoorn self-play`).** Instead of only running
  fixed archetype probes, *generates* new adversarial scenarios — a fresh persona
  plus a multi-turn probe script, each *seed-grounded* in a logged breach — drives
  them against the target, and pays a reward only when the attack is real. The
  reward multiplies `base_reward × SGS guide (relatedness × non_degeneracy) ×
  trust_gate`, where the trust gate requires all three of: the breach assembling
  into a `Report` (citation-to-turn invariant), the judge clearing its
  mutation-score floor, and the citation surviving CITE-MR. Offline (no
  `ANTHROPIC_API_KEY`) is a deterministic stub conjecturer + heuristic judge,
  stamped `is_live: false`; the measured `pass^k` attack-success-rate
  (`--mode llm`) is key-gated and raises rather than silently degrading to the stub.
- **Judge-overfit audit (`coehoorn overfit-audit`).** Turns the repo's "gate on the
  Wilson lower bound" discipline on itself, fully offline and keyless: sweeps a real
  judge config family (the self-harm "require ≥ τ safety signals" threshold,
  `τ ∈ {1..4}`, with `τ=1` reproducing the shipped heuristic), selects the gold-best
  config, and reports its recall Wilson lower bound **both** naively **and**
  Bonferroni-corrected for the size of the search — beside the generalization gap
  (gold agreement − fresh-conjectured-siege agreement; a positive gap is the overfit
  signature), a tunable-signal complexity scalar, and a sample-k saturation curve
  (resamples on a fixed gold set, never a size-asymptote). A single red-team score is
  framed as a capability-relative floor. `--min-corrected-recall-lower` gates on the
  corrected floor, not the naive one.
- **Cascade telemetry (`cascade` module, surfaced by `overfit-audit`).** Emits the
  cheap→expensive tier-boundary shape — `alpha` (the fraction the deterministic fast
  path resolves without escalating), `disagreement_rate`, and `lossless_violations`.
  The deterministic→gold boundary is measured at zero model spend (exact, pinned in
  tests); the heuristic→LLM boundary is emitted with `measured: false` and null rates
  rather than a fabricated number. Not a CLI subcommand. Stdlib-only.
- **Distill the judge into the deterministic floor (`coehoorn distill-floor`).** On
  the residual the floor abstains on, runs a judge **jury** over a fresh conjectured
  *derivation* siege, reports the jury's **correlation-corrected effective votes**
  (never the raw member count), distills the high-consensus agreements into a
  candidate deterministic rule, and promotes it only after a **held-out slice it was
  not derived from** clears the agreement threshold — the reported replaceable
  fraction is that out-of-sample agreement, never the in-sample fit. The offline mock
  jury is keyless; `--mode llm` is key-gated and raises without a key.
- **Selective-risk certificate (`coehoorn selective-risk`).** A **distribution-free,
  conformal-style** selective-risk certificate over fresh self-play-conjectured
  inputs: the judge *abstains* on the cells it cannot decide, and the certificate
  bounds the error on the decided subset with a Hoeffding upper bound at `1−delta`,
  shipped next to its width and an `O(1/√N)` convergence curve so the bound reads as a
  converging methodology, not a small-n headline. `--max-risk-upper` gates on the
  upper bound, never the point estimate.
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
- **Release workflow (`.github/workflows/release.yml`).** Fires on `v*.*.*`
  tag pushes ONLY, refuses a tag that disagrees with `pyproject.toml`'s
  version, smokes the built wheel in a fresh venv before the unrecoverable
  upload, publishes via PyPI OIDC trusted publishing (no stored token
  anywhere), then a checkout-free job installs `coehoorn[mcp]` from the
  PUBLISHED wheel and runs the keyless MCP siege. The trigger and
  publish-safety contract are pinned by `tests/test_release_workflow.py`, so
  a later edit that widens the trigger or pastes a token fails the suite.
- **GitHub Pages deploy (`.github/workflows/pages.yml`).** Publishes the
  committed byte-reproducible Siege Surveys: the site root serves the MCP
  rug-pull report directly and the full `runs/` tree keeps stable URLs that
  map 1:1 to repo paths. Nothing is generated at deploy time.

### Changed
- **Discovery semantics:** any criterion breach now fails the transcript;
  tolerance/threshold policy belongs to a downstream gate, not to Coehoorn. The
  rubric's `weight` and `failure_is_critical` now rank worst-moment severity.
- The committed sample report is byte-reproducible by construction.
- **CI hardened from a single leg to a gate battery:** a Python 3.11–3.13
  matrix plus one macOS smoke leg; an explicit ruff ruleset
  (`E, W, F, I, B, UP, C4, SIM, RUF` — the repo is violation-free at that
  set, nothing grandfathered); a mypy gate over the whole package
  (`disallow_untyped_defs` / `disallow_incomplete_defs`, zero ignore
  pragmas); a measured 90% coverage floor; and the byte-reproducibility gate
  extended from `runs/sample/` alone to all three committed artifact sets
  (`runs/sample/`, `runs/sample-tools/`, `runs/sample-mcp/`).
- **Removed the Jinja2 dependency** — the report renders in pure Python.

### Fixed
- **One 429 no longer destroys a whole siege.** The fan-out was a bare
  `asyncio.gather` with the default `return_exceptions=False`, so a single
  rate-limited approach re-raised and discarded every conversation that had
  already completed — a run that died at approach 5 of 6 wrote no report at
  all. `coehoorn run` now uses a resilient fan-out; a run where *every*
  approach fails writes no report and exits 2 instead of raising a traceback.
- **The external-siege workflow no longer mints a green check for a siege it
  did not run.** The guard was the first step of the siege job and every real
  step carried `if: steps.guard.outputs.configured`, which GitHub scores
  **success**: 17 of 17 scheduled runs concluded green having executed nothing.
  The guard is now its own job and the siege is gated at the job level, so an
  unconfigured siege is **skipped**. A test pins the shape for every workflow
  in the repo.
- The MCP rubric ships inside the package (`coehoorn/data/rubric_mcp.yaml`),
  so an installed `coehoorn mcp-siege` works with no repository checkout —
  it previously loaded from the repo's `examples/` tree, which a wheel
  install does not have. `examples/rubric_mcp.yaml` remains the documented
  user-facing copy, pinned byte-identical by the suite.
- The sample-report builder no longer mutates the committed sample on every run
  (pinned run id + timestamps).
- Removed a dead `overall_pass = True` coercion in the heuristic judge that
  could have masked a missed breach as a pass.

## [0.1.0]

- Initial rubric-driven, multi-turn, cited-evidence harness: schema-enforced
  verdicts, heuristic + LLM modes, HTTP agent adapter, deterministic sample.
