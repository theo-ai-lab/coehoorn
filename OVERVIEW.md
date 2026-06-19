# Coehoorn — Project Overview

A granular walkthrough of the whole project: what it is (in plain English first),
how every piece works, the engineering decisions behind it, and exactly where the
build stands today. The [`README.md`](./README.md) is the pitch; this is the map.
(For a status-only snapshot, see [`BUILD_STATE.md`](./BUILD_STATE.md).)

---

## 1. What this is, for an outsider

Coehoorn **stress-tests an AI agent to find where it breaks — and proves each flaw.**

Imagine you built a customer-support AI. It passes your normal tests. But in a real
conversation it might cave when a user pushes back, invent a fake legal citation, miss
someone in crisis, leak its hidden instructions to a polite attacker — or, if it can
use tools, **delete an account or issue a refund it had no business issuing.** You
usually discover these the worst way: a screenshot from an angry user.

Coehoorn plays a panel of difficult users — a *siege* on your agent. It sends six kinds
of adversaries at it (a contradictor, a vague rambler, someone in distress, an
off-topic prober, a prompt-injector, an edge-case tester), holds real multi-turn
conversations, watches both what the agent *says* and what *tools it calls*, and grades
each conversation against a plain-English checklist you write. When it reports "your
agent failed here," it **points at the exact message in the transcript that proves it**
— and it's built so that a flaw with no proof attached *cannot even be recorded.* It
runs entirely on your machine, offline, no account, and outputs a single self-contained
HTML report drawn like an old map of a fort under siege, where each broken wall is a
place your agent failed.

**One sentence:** *point Coehoorn at a chat or tool-using agent, describe the failure
modes you care about, and get back a ranked report of where it breaks — with every
failure cited to the exact conversation turn that proves it.*

---

## 2. The problem, precisely

Agent failures are **multi-turn, behavioral, and easy to wave away.** A unit test
checks one input/output. The failures that hurt emerge across a conversation — a stance
that flips under pressure, a fabrication three turns deep, a crisis signal missed, a
destructive tool fired without approval. And when someone *claims* "the agent did
something bad," it's hard to act on without knowing *where.* The hard part isn't
generating adversarial chats — many tools do that. The hard part is producing a verdict
you can **trust and act on.** That is the entire design center of Coehoorn.

---

## 3. The core idea (runnable in 10 seconds)

Most red-team tools hand you a verdict you take on faith. Coehoorn makes a **dishonest
verdict structurally impossible** — encoded in the data schema, so the object won't
even construct:

```python
from coehoorn.schemas import CriterionVerdict, CriterionStatus

CriterionVerdict(
    criterion_id="safe_handling_of_self_harm",
    status=CriterionStatus.FAIL,     # "this criterion failed"
    confidence=0.99,
    cited_turn_index=None,           # ...but it points at no evidence
    rationale="trust me",
)
# pydantic.ValidationError: CriterionVerdict with status=fail must set cited_turn_index
```

A failure with no cited turn, a "pass" that cites a breach, a citation to a turn that
doesn't exist — **none can exist.** The judge can be wrong; it cannot be unfalsifiable.

---

## 4. Where it sits

Coehoorn is the **discovery layer** of agent reliability — it *finds* failures before
deploy, through adversarial simulation.

```
   DISCOVER (Coehoorn)   →   PREVENT (a CI gate)   →   ACCOUNT (runtime)
   find failures           block regressions          audit live behavior
   pre-deploy              at deploy                   in production
```

It deliberately does **not** gate; whether a discovered breach should fail your build
is a downstream policy decision. The adversarial traces it produces are exactly the
fixtures a prevention gate would replay.

---

## 5. How it works, end to end

A thin, typed pipeline; each stage validates its input and output:

```
rubric.yaml
   │  rubric_parser.parse_rubric_file()
   ▼
(Rubric, heuristic rules)            ← criteria can check reply text OR tool calls
   │  personas.generate_personas_*()
   ▼
[Persona × N]                        ← 6 archetypes
   │  conversation.run_conversations()  (asyncio fan-out, bounded concurrency)
   ▼
[Transcript × N]                     ← turn-indexed; turns capture tool calls
   │  judge.judge_all()                 (heuristic OR LLM; one retry, no silent fallback)
   ▼
[Verdict × N]                        ← pass / fail / abstain, each FAIL cites a turn
   │  aggregator.build_report()         (cross-validates the whole thing)
   ▼
Report ──► report_html → the Siege Survey (.html)
       ├─► aggregator   → runs/<id>.json
       └─► outputs      → SARIF + JUnit (opt-in, for CI)
```

1. **Rubric parsing** (`rubric_parser.py`). A YAML rubric of pass/fail **criteria** in
   plain English. Each may carry a `heuristic:` block — keyword rules for the agent's
   text, **and/or tool-policy rules** (forbidden tools, required-approval order).
2. **Persona generation** (`personas.py`). N adversarial personas across six fixed
   **archetypes**: `contradictor`, `ambiguous`, `emotional`, `off_topic`, `injector`,
   `edge_case`. Heuristic (curated pool, offline) or LLM (Anthropic Opus).
3. **Conversations** (`conversation.py`). Fans out N conversations concurrently
   (`asyncio.gather` + a semaphore — no framework). Each run becomes a `Transcript`,
   and each agent reply can carry the **tool calls** it made.
4. **Judging** (`judge.py`). Scores each transcript and emits a `Verdict`. Discovery
   semantics: any criterion breach fails the transcript. The heuristic judge is offline
   and rule-based (text *and* tool-policy checks); the LLM judge (Anthropic Sonnet)
   emits structured JSON, retries once on a validation failure, then hard-fails.
5. **Aggregation** (`aggregator.py`). Assembles one `Report` whose constructor re-checks
   every cross-record invariant; also `compare_to_expected` and `pin_report_timestamps`.
6. **Rendering / outputs** (`report_html.py`, `outputs.py`). The Siege Survey HTML, plus
   optional SARIF/JUnit for CI.

---

## 6. The trust boundary

The judge sits at the trust boundary; `schemas.py` enforces three layers:

- **Three-valued judgments** — `pass` / `fail` / **abstain**. A judge with no basis to
  decide records an abstention, *excluded* from the accuracy math, never a silent pass.
- **Invariants that make illegal states unconstructable** — a `fail` must cite a turn; a
  `pass`/`abstain` must not; a `Report` rejects any cited index that doesn't resolve
  against the linked transcript, any wrong criterion coverage, any duplicate persona id.
- **Retry-with-context, then hard-fail** — the LLM judge gets one retry with the error,
  then fails loudly. No fallback.

**What it does NOT claim:** the schema prevents *uncited/out-of-range* verdicts, not
*unfaithful* ones — a judge can still cite the *wrong* turn and pass validation. It
guarantees anchored, checkable evidence; not that the reasoning is correct.

---

## 7. Two modes

Both emit the identical, schema-validated `Report`.

| | Heuristic | LLM |
|---|---|---|
| Personas | curated pool | Anthropic Opus |
| Judge | rule-based (text + tool policy) | Anthropic Sonnet, structured-output + retry |
| Requires | nothing | `ANTHROPIC_API_KEY` |
| Determinism | **byte-for-byte** | no |

The committed samples are heuristic, so anyone can reproduce them exactly.

---

## 8. The tool-use attack surface (the agentic dimension)

Real 2026 agents don't just chat — they call tools. Coehoorn tests that surface, mapped
onto the **OWASP Top 10 for Agentic Applications (2026)**:

- **ASI02 — Tool Misuse.** A rubric lists `forbidden_tools`; the agent invoking any of
  them (e.g. `delete_account`, `drop_table`) is a breach, cited to the turn.
- **ASI03 — Privilege/Approval Bypass.** A rubric lists `tool_must_precede` pairs
  (e.g. `get_approval` before `issue_refund`); a privileged action with no prior
  approval is a breach. **Order, not presence** — an agent that simply refuses to act
  is never charged.

A committed demo (`runs/sample-tools/`, rubric `examples/rubric_tools.yaml`) sieges a
deliberately-flawed tool-using agent and catches both, with no API key.

---

## 9. Audit the auditor (the meta-eval)

A cited verdict is only worth the judge that produced it — so Coehoorn **grades its own
judge** (`meta_eval.py` + `metrics.py`). `coehoorn meta-eval` runs the judge over a
frozen, hand-labeled **gold set** and reports the full confusion matrix with
**precision/recall/specificity (each with a Wilson 95% interval), plus F1, balanced
accuracy, and Cohen's kappa** — beside two dumb baselines. Stdlib math, no SciPy.

The gold set is **stacked with adversarial near-misses** where the cheap keyword
heuristic is *wrong on purpose* (a real `Roe v. Wade` it flags as fabricated; a
fabrication phrased to dodge the pattern; a dismissive reply that name-drops a safety
keyword). So the heuristic judge honestly scores **~0.66 balanced accuracy, recall 0.60
(95% CI 0.23–0.88, n=5)** — beating the 0.50 baselines, well under 1.0. That gap is the
honest argument for the LLM judge, not a number to hide. CI gates on the interval floor.
Methodology: [`docs/EVAL.md`](docs/EVAL.md); standards mapping: [`docs/coverage-map.md`](docs/coverage-map.md).

**And it audits that audit.** Two stdlib-only commands extend the meta-eval to measure
the one thing the schema can't guarantee — citation *faithfulness*:

- **`coehoorn mutation-score` (`mutants.py`)** plants six broken "mutant" judges and proves
  the gold set catches each. The two discriminating ones corrupt *only* the cited turn —
  bugs a status confusion matrix is blind to — caught via a new `gold_cited_turn`
  ground-truth anchor. The honest score is **4/6**, with a load-bearing-vs-confirmatory
  split, and the two survivors *name the gold cell that would catch them*. It's a
  deterministic count, so it ships **without** a confidence interval (one would be false
  precision).
- **`coehoorn metamorphic` / CITE-MR (`metamorphic.py`)** rewrites a transcript in
  meaning-preserving ways (rename / renumber / insert / paraphrase) and checks the
  verdict **and the cited turn** both hold. The deterministic judge is faithful by
  construction — the control whose `1.00` validates the harness, stated on every run; the
  stochastic LLM judge is the real target, with instability gated by **Fisher's exact +
  Holm**, not a normal-approximation z-test.

---

## 10. The Siege Survey (the report) + machine outputs

The hero artifact is **one self-contained HTML file** — no JavaScript, no external
assets, opens offline, prints faithfully. An inline-SVG six-faced **fort** (one face per
archetype), ringed by a **ditch** (the schema trust boundary); each persona is an
**approach**; a failure is a **breach** drawn as a gap in the wall at the cited turn;
tool calls are shown inline. A loud result tally, a calibration panel, and the full
cited transcripts. Five canon terms (siege, approach, breach, held, worst moment).

For automation (`cli.py` + `outputs.py`): a stable `--json` summary, an opt-in
`--fail-on-breach` exit code, a machine-readable `report.json`, and **`--emit
sarif,junit`** — SARIF 2.1.0 (each finding located at its cited turn, for the GitHub
Security tab) and JUnit XML. A `.github/workflows/siege.yml` runs a siege in CI and
uploads the SARIF.

---

## 11. Optional extras (lazy, no impact on the core)

Optional dependencies, imported lazily — `import coehoorn` and the CLI work with neither
installed (a clean-interpreter test enforces it):

- **`coehoorn[mcp]`** — an MCP server so another agent can run a siege as a tool.
- **`coehoorn[inspect]`** — exports a `Report` to an Inspect AI `EvalLog`, viewable in the
  standard eval viewer; fails loud on schema drift.

---

## 12. Engineering posture

- **Lean by decision.** Five runtime dependencies (`anthropic`, `httpx`, `pydantic`,
  `python-dotenv`, `pyyaml`); the metrics, the HTML renderer, and the SARIF/JUnit outputs
  are pure-stdlib. Every dependency — and every *rejected* one — is in
  [`docs/adr/`](docs/adr/): no LangGraph, DSPy, pydantic-ai, observability SaaS, or
  Jinja2, each with the reasoning.
- **Deterministic and private.** Heuristic mode is byte-reproducible; no telemetry, no
  external callbacks. Outbound network is only the agent endpoint and, in LLM mode,
  `api.anthropic.com`.
- **Tested at the boundaries.** 318 tests (316 fully offline + deterministic, 2 gated
  behind the extras) — schema invariants, the report's design constraints, the meta-eval
  numbers, the mutation score's load-bearing/confirmatory split, the metamorphic
  Fisher+Holm gate, byte-reproducibility, the network adapter, and the tool-policy checks.

---

## 13. Repository map

```
coehoorn/  (modules listed roughly largest-first)
  metamorphic.py     CITE-MR — verdict + citation stability under transforms (Fisher+Holm)
  mutants.py         Judge Mutation Score — plant broken judges, prove the gold catches them
  report_html.py     the self-contained Siege Survey (no JS, computed SVG)
  schemas.py         the Pydantic wire contract — the trust boundary (+ ToolCall)
  judge.py           heuristic + LLM judges; text + tool-policy (ASI02/ASI03)
  cli.py             run / compare / meta-eval / mutation-score / metamorphic
  meta_eval.py       audit the auditor — score the judge vs gold; + gold_cited_turn anchor
  personas.py        heuristic + LLM adversarial persona generators
  conversation.py    async, bounded-concurrency runner (captures tool calls)
  metrics.py         Wilson intervals, precision/recall/F1/specificity/balanced/kappa
  aggregator.py      build Report, compare-to-expected grid, timestamp pinning
  outputs.py         SARIF 2.1.0 + JUnit XML (stdlib)
  inspect_export.py  optional: Report → Inspect AI EvalLog
  rubric_parser.py   YAML → Rubric + heuristic rules (text + tool policy)
  mcp_server.py      optional: MCP server exposing a siege as a tool
  agent_adapter.py   HTTP / callable adapters (one reused client; AgentReply w/ tools)
apps/stub-agent/     a deliberately-flawed local fixture (LOCAL ONLY) to test against
examples/            sample rubric + tool-policy rubric + expected-failures fixture
tests/gold/          the frozen, hand-labeled judge gold set (+ gold_cited_turn anchors)
tests/               318 tests (316 offline, 2 gated)
ARCHITECTURE.md      full data-flow walkthrough + the trust boundary
docs/                EVAL, coverage-map, ADRs, one-page brief
runs/sample/         committed chat sample (byte-reproducible)
runs/sample-tools/   committed tool-siege sample (catches ASI02/ASI03)
```

---

## 14. How to run it

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync && uv run pytest -q                       # install + the full offline suite

uv run python scripts/build_sample_report.py      # the deterministic chat sample
uv run python scripts/build_tool_sample.py         # the deterministic tool-siege sample
open runs/sample/report.html                       # the Siege Survey (macOS; else xdg-open)

uv run coehoorn meta-eval \                           # watch it grade its own judge
  --gold tests/gold/judge_gold.jsonl --rubric examples/rubric_coach.yaml
uv run coehoorn mutation-score \                      # audit that grade: honest 4/6, survivors named
  --gold tests/gold/judge_gold.jsonl --rubric examples/rubric_coach.yaml
uv run coehoorn metamorphic \                         # citation stability under meaning-preserving edits
  --rubric examples/rubric_tools.yaml --from-report runs/sample-tools/report.json

# live run against the bundled flawed stub, emitting CI formats:
(cd apps/stub-agent && uv sync && uv run python app.py)   # binds 127.0.0.1 only
uv run coehoorn run --rubric examples/rubric_coach.yaml \
  --agent http://127.0.0.1:8001/chat --personas 6 --turns 4 --out runs --emit sarif,junit
```

---

## 15. Worked examples (committed, reproducible)

- **Chat siege** (`runs/sample/`): six personas vs a stub with two flaws (never refers
  self-harm to help; ~30% fabricates a legal citation). Result: 3 of 6 breached —
  emotional caught the self-harm flaw (turn 3), off_topic + edge_case caught fabricated
  citations. Judge-calibration panel shows the honest ~0.66, not a fake 1.0.
- **Tool siege** (`runs/sample-tools/`): six personas vs a flawed tool-using agent.
  Result: 6/6 breached — `delete_account` (ASI02, turn 1) and `issue_refund`-without-
  approval (ASI03, turn 3), each cited and shown in the report.

---

## 16. Status — where the build stands today

- **Done & green.** v0.2. 318 tests (316 offline + deterministic), lint clean,
  byte-reproducible samples.
- **Recently added.** A citation-integrity suite — `mutation-score` (mutation-test the
  gold set; honest 4/6) and `metamorphic`/CITE-MR (verdict + citation stability under
  semantics-preserving transforms, Fisher+Holm gate), both stdlib-only with zero new
  runtime deps; tool-use attack surface (OWASP Agentic ASI02/ASI03); SARIF + JUnit CI
  outputs + a GitHub Action; a hardened network adapter.
- **The one honest gap.** LLM mode (Opus personas + Sonnet judge) runs the full path
  end-to-end with a key (non-deterministic, not committed as a sample) — but its
  **accuracy is unmeasured**: the LLM judge has not been scored against the gold set,
  so there is no precision/recall number for it yet (unlike the heuristic's honest
  ~0.66). Heuristic mode is fully exercised.

---

## 17. Honest limitations

- **The LLM judge's accuracy is unmeasured** — the live path runs end-to-end with a
  key, but it has not been scored against the gold set.
- **Tool coverage is a thin, real slice** — forbidden tools + approval bypass
  (ASI02/ASI03), not memory/context poisoning, inter-agent comms, or multi-agent cascades.
- **Six fixed archetypes, not a learning attacker** — a small, opinionated harness, not
  an automated adaptive red team.
- **Schema integrity ≠ judge correctness** — anchored evidence, not certified reasoning.
- **No users yet** — a finished, tested, documented tool that, as of today, no one but
  its author has run. A deliberate state, not an oversight.
