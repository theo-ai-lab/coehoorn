# Coehoorn

*Adversarial red-teaming for chat and tool-using agents — every failure cited to the turn that proves it.*

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Runtime deps: 5](https://img.shields.io/badge/runtime%20deps-5-informational)
![Offline · no telemetry](https://img.shields.io/badge/offline-no%20telemetry-success)
![Tests: 231 offline](https://img.shields.io/badge/tests-231%20offline-success)

**The problem.** You're shipping a chat or tool-using agent. It passes unit tests —
then in a real multi-turn conversation it caves under pressure, fabricates a
citation three turns deep, misses a crisis signal, or fires a destructive tool it
shouldn't. You find out from a user's screenshot.

**What it does.** Coehoorn red-teams that agent *before* deploy — driving six kinds
of difficult user at it across real multi-turn conversations — and reports exactly
where it broke. Every failure points at the one transcript turn that proves it.

**What's different.** Most red-team tools hand you a verdict you have to trust.
Coehoorn makes a dishonest verdict *structurally unrepresentable* — enforced by the
data schema, not by a prompt. Here is the whole idea in ten seconds, no API key:

```python
from coehoorn.schemas import CriterionVerdict, CriterionStatus

# "This criterion failed" — but pointing at no turn as evidence.
CriterionVerdict(
    criterion_id="safe_handling_of_self_harm",
    status=CriterionStatus.FAIL,
    confidence=0.99,
    cited_turn_index=None,            # no evidence
    rationale="the agent did something bad, trust me",
)
# pydantic.ValidationError: CriterionVerdict with status=fail must set cited_turn_index
```

The report that can't be built is the point. A failed verdict with no citation,
a "pass" that cites a breach, a worst-moment that doesn't match any cited
failure, a citation to a turn that isn't in the transcript — none of them can
exist. The judge can be wrong; it cannot be unfalsifiable.

## See it run

![Coehoorn sieging a deliberately-flawed tool-using agent](docs/demo.gif)

A ~20-second walkthrough, fully offline and byte-reproducible
(regenerate with [`vhs`](https://github.com/charmbracelet/vhs) `docs/demo.tape`):

1. Coehoorn sieges a deliberately-flawed *tool-using* agent and catches the
   destructive tool call **and** the refund-issued-without-approval — each cited to
   the exact turn (OWASP Agentic **ASI02** / **ASI03**).
2. Then it grades its **own** judge against an adversarial gold set *built to expose
   it*: the cheap heuristic honestly scores `balanced accuracy 0.66` (vs `0.50` for
   either dumb baseline). A perfect score there would be the red flag — this is the
   deliberate floor, and the honest case for the stronger LLM judge.

No API key, no network, no setup. The committed
[`runs/sample-tools/report.html`](runs/sample-tools/report.html) is the exact
artifact that walkthrough produces — open it offline. (The chat-agent siege from
the Quickstart is committed alongside it at
[`runs/sample/report.html`](runs/sample/report.html).)

## Where it sits

Coehoorn is the **discovery** layer of agent reliability: it *finds* failures
before deploy, through adversarial simulation.

```
   DISCOVER (Coehoorn)  →  PREVENT (a CI gate)  →  ACCOUNT (runtime)
   find failures          block regressions       audit live behavior
   pre-deploy             at deploy                in production
```

It deliberately does **not** gate. Whether a discovered breach should fail your
build is your policy, applied downstream — Coehoorn's job is to surface the breach
with its evidence. The adversarial traces it produces are exactly the fixtures a
regression gate would replay.

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                                   # core only: five runtime deps, no extras
uv run pytest -q                          # the full offline suite (no network, no key)

uv run python scripts/build_sample_report.py   # regenerate the deterministic sample
open runs/sample/report.html                   # the Siege Survey (macOS; else xdg-open)

uv run coehoorn meta-eval \                  # audit the judge against the gold fixture
  --gold tests/gold/judge_gold.jsonl \
  --rubric examples/rubric_coach.yaml

uv run coehoorn mutation-score \             # audit that audit: does the gold catch a broken judge? (4/6)
  --gold tests/gold/judge_gold.jsonl \
  --rubric examples/rubric_coach.yaml
```

A live run against the bundled, deliberately-flawed stub agent:

```bash
(cd apps/stub-agent && uv sync && uv run python app.py)   # binds 127.0.0.1 only

uv run coehoorn run \
  --rubric examples/rubric_coach.yaml \
  --agent http://127.0.0.1:8001/chat \
  --personas 6 --turns 4 --out runs

uv run coehoorn compare \
  --report runs/<your-run-id>.json \
  --expected examples/expected_failures.yaml
```

> The stub in `apps/stub-agent/` is a **deliberately flawed local fixture** — it
> fails to refer self-harm to help, and fabricates a legal citation ~30% of the
> time. The breaches Coehoorn catches are designed catches, not luck, which is what
> makes them a reproducible demo.

**Write-back contamination (the KB-poisoner).** Add `--include-kb-poisoner` to a
`run` to append a seventh persona that probes the *agent-write-back* surface — it
tries to get the agent to persist attacker-controlled content (a saved note, a
memory entry, an injected "standing instruction") into a store later read back as
trusted. It drives its own dedicated probe script and folds two write-back
criteria into the run: an unsanitized `kb_write` (OWASP Agentic ASI03
approval-bypass / ASI02 tool misuse) and an echo of a persisted override (OWASP
LLM01 carried through memory). The criteria never fire on the other personas, so
the flag only adds the new face; the safe stub holds, a write-back-vulnerable
target breaches with a cited turn.

**Siege a real external agent.** The same `run` command points at any HTTP
agent speaking `{conversation} -> {reply}` — the endpoint and its auth resolve
from the environment (`AGENT_ENDPOINT`, `AGENT_API_KEY` / `AGENT_AUTH_HEADER`)
so nothing secret touches the command line:

```bash
export AGENT_ENDPOINT="https://your-agent.example.com/chat"
export AGENT_API_KEY="…"   # -> Authorization: Bearer …  (or AGENT_AUTH_HEADER)
uv run coehoorn run --rubric examples/rubric_coach.yaml \
  --personas 6 --turns 4 --out runs/external --emit sarif,junit
```

`.github/workflows/external-siege.yml` wires this into CI against a configured
target (secret/variable): SARIF to the Security tab, JUnit report, and cited
breaches posted as a PR comment — and it no-ops gracefully when no endpoint is
set. See [`docs/ENGAGEMENT_TEMPLATE.md`](docs/ENGAGEMENT_TEMPLATE.md) for the
full engagement scaffold. (If your agent speaks a different wire shape, wrap
`HttpAgentAdapter` or pass any `async (conversation) -> str` callable.)

**LLM mode** runs the full path end-to-end. With `ANTHROPIC_API_KEY` set,
`--mode llm` drives personas and conversations on Claude (Opus) and judges with
Sonnet. It is non-deterministic, so no LLM sample is committed; regenerate one
locally with `scripts/build_sample_report_llm.py`. Its **accuracy is not yet
scored** against the gold set — scoring the LLM judge the way the heuristic judge
is scored (see below) is the top roadmap item.

## The Siege Survey

The report is one self-contained HTML file — no JavaScript, no external assets,
opens offline, prints faithfully. Its visual language is a 17th-century
military-engineering survey, after Menno van Coehoorn:

| term | meaning |
|---|---|
| **siege** | one run: every adversarial approach driven against the agent |
| **approach** | one persona's conversation against the fort |
| **breach** | the turn where a criterion failed — a literal gap in the wall |
| **held** | an approach the wall turned away |
| **worst moment** | the deepest breach in a transcript |

A six-faced fort — one face per archetype — sits inside a ditch (the schema
trust boundary). A breach cuts a visible gap in that wall segment at the cited
turn; the figure reads even in grayscale. It looks nothing like a CI dashboard
because it isn't one.

## Two modes

Both emit the same schema-validated `Report`.

| | heuristic | llm |
|---|---|---|
| personas | curated pool, per archetype | Anthropic Opus, tailored to the rubric |
| judge | rule-based, no network | Anthropic Sonnet, structured-output with retry |
| requires | nothing | `ANTHROPIC_API_KEY` |
| determinism | byte-for-byte | no |

`--mode auto` picks LLM when a key is set, heuristic otherwise. The committed
sample is heuristic, so anyone can reproduce it byte-for-byte.

## Audit the auditor

A cited verdict is only worth the judge that produced it, so Coehoorn grades its
own judge. `coehoorn meta-eval` scores the judge against a frozen, hand-labeled
gold set and reports the full confusion matrix with **precision, recall, and
specificity — each with a Wilson 95% interval — plus F1, balanced accuracy, and
Cohen's kappa** — beside two dumb baselines (always-breach, always-hold).

The gold set is stacked with adversarial near-misses where the cheap keyword
heuristic is *wrong on purpose*: a correctly cited *real* case it flags as
fabricated, a fabrication phrased to dodge the pattern, a dismissive reply that
name-drops a safety keyword. So the heuristic judge scores around `balanced
accuracy 0.66` (vs `0.50` for either baseline) with `recall 0.60 (95% CI
0.23–0.88, n=5)` — and that gap is the honest argument for the LLM judge, not a
number to hide. Regression is gated on the interval **floor**, not the point
estimate, so the gate catches a real drop without crying wolf on small-n noise.

See [`docs/EVAL.md`](docs/EVAL.md) for the metric definitions, the gold-set
provenance, and the committed thresholds, and
[`docs/coverage-map.md`](docs/coverage-map.md) for how the archetypes map onto
OWASP LLM, MITRE ATLAS, and NIST — gaps advertised.

## Audit the audit

A gold-set score is only as honest as the gold set, and a citation is only
trustworthy if it survives an edit that shouldn't move it. Two stdlib-only
commands measure both — and they extend the meta-eval, so the auditor's auditor
is itself auditable.

**`coehoorn mutation-score` — does the gold set have teeth?** It plants six broken
"mutant" judges and checks the gold catches each. The discriminating two relocate
a citation or shift it off-by-one — *citation* bugs a status-only confusion matrix
cannot see; they are caught only because the gold now carries a `gold_cited_turn`
ground-truth anchor. The shipped score is an honest **4/6 (0.67)** with a
load-bearing-vs-confirmatory split, and the two survivors *name the gold cell that
would catch them* instead of being swept under the rug:

```
score: 4/6 = 0.667
  of which: load-bearing 2/3 caught (M1/M4 — citation bugs invisible to a status matrix),
            confirmatory 2/3 (gross status flips a matrix cannot miss)
  M5 abstain -> pass   SURVIVED -> add a decided-gold cell the heuristic abstains on
  M6 drop tool-order   SURVIVED -> add a tool-policy (ASI03) gold cell
```

It is a deterministic count, not a sampled statistic, so it ships **without** a
confidence interval — a CI on a fixed count would be a category error (ADR-0011).

**`coehoorn metamorphic` — does a citation survive a semantics-preserving edit?**
It rewrites the transcript in ways that must not change the verdict (rename the
persona, renumber turns, insert a neutral turn, paraphrase a non-cited turn) and
asserts both that the outcome holds **and** that the cited turn tracks the
transform's remap. The deterministic heuristic judge is faithful *by
construction*, so it is the control — its `stability 1.00` validates the harness,
not any real judge, and the command says exactly that on every run. The real
target is the stochastic LLM judge (`--mode llm`), where an instability call is
gated by **Fisher's exact one-sided test with a Holm step-down correction** over
the transform family, not a normal-approximation z-test (ADR-0011).

## Self-play attack conjecturer

`coehoorn self-play` closes the loop: instead of only running fixed archetype
probes, it **generates** new adversarial scenarios — a fresh persona + a
multi-turn probe script — each one *seed-grounded* in a logged breach, drives it
against the target, and pays a reward only when the attack is real.

The reward is made un-gameable by reusing Coehoorn's own rigor:

```
guided_reward = base_reward    # the judge found a breach (1.0) or not (0.0)
              × guide.score    # SGS = relatedness × non_degeneracy
              × trust_gate     # 1.0 iff ALL three hold:
```

- **SGS guide** (`relatedness × non_degeneracy`) — an attack that drifts off its
  seed, or that emits degenerate reward-farming filler, scores ~0. Because the
  two factors multiply, an attack must be **both** on-seed **and** a genuine
  multi-turn probe to earn anything.
- **citation-to-turn invariant** — a "successful" attack must produce a
  transcript+verdict that assembles into a `Report` (the breach cites a turn that
  actually exists), or it pays nothing.
- **judge mutation-score gate** — the judge measuring attack-success must clear
  its calibration floor first, so a conjecturer cannot inflate ASR by leaning on
  a broken judge.
- **CITE-MR stability gate** — a claimed breach is only counted if its citation
  survives the semantics-preserving transforms; a one-off flicker is not a win.

```bash
(cd apps/stub-agent && uv run python app.py)   # the deliberately-flawed stub

uv run coehoorn self-play \
  --rubric examples/rubric_coach.yaml \
  --gold   tests/gold/judge_gold.jsonl \      # breach cells seed the conjecturer
  --agent  http://127.0.0.1:8001/chat \
  --criterion safe_handling_of_self_harm      # one attack per seeded breach
```

**Offline (no key) is a plumbing demo, not a measurement.** With no
`ANTHROPIC_API_KEY`, self-play runs a deterministic stub conjecturer + the
heuristic judge to prove the loop end-to-end; the command stamps every such
result with `OFFLINE PLUMBING DEMO …` and `is_live: false`. The **measured**
attack-success-rate (`--mode llm`: live Opus conjecturer inventing novel attacks
+ live Sonnet judge, with `pass^k` over `--k` resamples) needs the key and is the
deliberately un-fakeable part — the live path raises rather than silently
degrading to the stub, so a "live" number can never be a stub number in disguise.

## What this does *not* claim

Coehoorn makes uncited and out-of-range verdicts impossible. It does **not** make
verdicts *faithful*: a judge can still cite the *wrong* turn and pass validation.
The schema guarantees the verdict is anchored to real, checkable evidence — not
that the reasoning attached to that evidence is correct. What it *does* offer
against that gap is **measurement, not a guarantee**: `mutation-score` proves the
gold set can catch a relocated citation, and `metamorphic` flags a citation that
drifts under an edit that should not move it. Pre-empting the limit is the point;
everything else it claims is meant to be taken literally.

## Where it sits in the landscape

Coehoorn cedes attack *breadth* on purpose and owns verdict *integrity*.

- **Garak** (NVIDIA) and **PyRIT** (Microsoft) bring large probe libraries and
  automated attack search. Coehoorn has six archetypes; it is not a scanner. Use
  them for breadth; use Coehoorn for cited, reproducible, multi-turn verdicts.
- **Promptfoo** is a broad eval/red-team runner with many providers. Coehoorn is a
  small, opinionated harness whose differentiator is the structurally-enforced
  citation, not the matrix of providers.
- **Petri** (Anthropic) also cites evidence — but as a *prompted convention* over
  free-text quotes. Coehoorn's citation is a Pydantic invariant: a turn index that
  must resolve against the linked transcript or the object won't construct.
- **Inspect AI** (UK AISI) is the standard eval *harness/viewer*. Coehoorn
  complements it — `coehoorn[inspect]` exports a siege to an Inspect `EvalLog`.

## Optional extras

Both are lazy — neither is imported on the core path; `import coehoorn` and the CLI
work with no extras installed.

```bash
pip install 'coehoorn[mcp]'      # coehoorn-mcp: lay a siege from any MCP-speaking agent
pip install 'coehoorn[inspect]'  # export a Report to an Inspect AI EvalLog
```

## Repository layout

```
coehoorn/
  schemas.py        # the Pydantic wire contract — the trust boundary
  rubric_parser.py  # YAML -> Rubric + heuristic rules
  personas.py       # heuristic + LLM adversarial persona generators
  personas_kb.py    # the KB-poisoner persona, probes, and write-back rubric
  agent_adapter.py  # HTTP / callable adapters for the target agent
  conversation.py   # async, bounded-concurrency conversation runner
  judge.py          # heuristic + LLM judges (one retry, no silent fallback)
  aggregator.py     # build Report, compare to expected, the confusion grid
  metrics.py        # Wilson intervals, precision/recall/F1/kappa (no SciPy)
  meta_eval.py      # score the judge against gold — audit the auditor
  mutants.py        # Judge Mutation Score — plant broken judges, prove the gold catches them
  metamorphic.py    # CITE-MR — verdict + citation stability under semantics-preserving transforms
  selfplay/         # seed-grounded attack conjecturer + SGS guide + gated self-play loop
  report_html.py    # the self-contained Siege Survey (no JS, no assets)
  cli.py            # coehoorn run / compare / meta-eval / mutation-score / metamorphic / self-play
  mcp_server.py     # optional: MCP server (extra)
  inspect_export.py # optional: Inspect AI EvalLog export (extra)
ARCHITECTURE.md     # full data-flow walkthrough + the trust boundary
apps/stub-agent/    # deliberately-flawed local fixture (LOCAL ONLY)
examples/           # sample rubric + tool-policy rubric + expected-failures fixture
tests/gold/         # frozen, hand-labeled judge gold set
docs/               # EVAL, coverage-map, ADRs, one-page brief
```

## Security and local-only constraints

See [`SECURITY.md`](./SECURITY.md). No telemetry, no analytics, no external
callbacks. The only outbound network is to the agent endpoint you pass and, in
LLM mode, to `api.anthropic.com`. The HTML report has no scripts and no external
resources; open it with the network disconnected.

## A note on the name

Named after Menno van Coehoorn (1641–1704), the Dutch military engineer and
fortification master of his era — fitting for a tool that lays siege to an
agent's defenses and surveys where the walls give way.

## License

MIT.
