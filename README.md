# Coehoorn

*Adversarial red-teaming for chat and tool-using agents — every failure cited to the turn that proves it.*

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Runtime deps: 5](https://img.shields.io/badge/runtime%20deps-5-informational)
![Offline · no telemetry](https://img.shields.io/badge/offline-no%20telemetry-success)
![Tests: 357 offline](https://img.shields.io/badge/tests-357%20offline-success)

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

## The MCP tool-poisoning attack pack

Tool poisoning is the loudest agent-security story of the moment, and no OSS
red-team harness ships a *runnable, reproducible* tool-poisoning fixture. Coehoorn
does — and it is the one architecture that can localize the attack in *time*,
because every breach is cited to the turn.

`coehoorn mcp-siege` drives a deliberately-vulnerable agent through three
MCP-tool-poisoning archetypes against an **offline loopback MCP fixture** — a
deterministic in-process model of MCP's newline-delimited-JSON stdio transport,
with no subprocess, no socket, and no dependency on the `mcp` package, so the pack
runs keyless and byte-for-byte reproducibly:

```bash
uv run coehoorn mcp-siege                 # all three archetypes, hero first
open runs/sample-mcp/rug-pull/report.html # the committed hero survey (macOS; else xdg-open)
```

| archetype | the attack | OWASP Agentic 2026 |
|---|---|---|
| **rug-pull** (hero) | a benign tool whose *description mutates malicious mid-session* — the flip happens at a specific turn | **ASI04** Supply Chain Compromise · **ASI01** Goal Hijack · **ASI02** Tool Misuse |
| tool-description poisoning | malicious instructions embedded in a tool's `description` field from the first listing | ASI04 · ASI01 |
| cross-server shadowing | a second (malicious) server registers a look-alike tool that intercepts a legitimate one | **ASI07** Insecure Inter-Agent Communication · ASI04 · **ASI03** Privilege Abuse |

**The rug-pull is the demonstration competitors structurally cannot make.** The
same `get_order_status` tool is clean when the agent first lists it (turn 1) and,
after the server silently mutates its own manifest, carries an exfiltration
directive from turn 3 on. Coehoorn cites the breach to **turn 3** — pinning the
exact turn the tool turned — while turn 1 shows the identical tool benign. A
verdict that only reports "the agent called a forbidden tool" cannot say *when*
the tool flipped; the schema-enforced citation invariant can:

```
runs/sample-mcp/rug-pull/report.html
  turn 1  assistant  get_order_status                        ← same tool, clean
  turn 3  assistant  get_order_status, export_account_data   ← breach · worst moment (cited)
```

The victim agent is *deterministically vulnerable* — it treats tool descriptions
as trusted instructions and obeys imperative directives embedded in them — so the
catch is a designed catch, not luck, which is what makes it a reproducible demo.
The live seam (a real LLM choosing tool calls from a poisoned manifest) is
documented but not built offline: the deterministic loopback is the artifact, and
the live path raises rather than being faked by the stub. The rubric that judges
the pack is [`examples/rubric_mcp.yaml`](examples/rubric_mcp.yaml); the three
committed reports live under [`runs/sample-mcp/`](runs/sample-mcp/) and are
regenerated by `scripts/build_mcp_sample.py`. The full covered / partial /
not-covered mapping against the OWASP Top 10 for Agentic Applications (2026) is
in [`docs/coverage-map.md`](docs/coverage-map.md) §5.

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

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). Install from
source — the working path today (no `coehoorn` package is on PyPI yet; the
first publish is pending):

```bash
git clone https://github.com/theo-ai-lab/coehoorn
cd coehoorn
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
`run` to append a seventh persona probing the *agent-write-back* surface — it
tries to get the agent to persist attacker-controlled content (a saved note, a
memory entry, an injected "standing instruction") into a store later read back as
trusted. It folds in two write-back criteria — an unsanitized `kb_write` (OWASP
Agentic ASI03 approval-bypass / ASI02 tool misuse) and an echo of a persisted
override (OWASP LLM01 through memory) — that fire on no other persona: the safe
stub holds, a write-back-vulnerable target breaches with a cited turn.

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
set. (If your agent speaks a different wire shape, wrap `HttpAgentAdapter` or pass
any `async (conversation) -> str` callable.)

**LLM mode** runs the full path end-to-end. With `ANTHROPIC_API_KEY` set,
`--mode llm` drives personas and conversations on Claude (Opus) and judges with
Sonnet. It is non-deterministic, so no LLM sample is committed; regenerate one
locally with `scripts/build_sample_report_llm.py`. Its **accuracy is not yet
scored** against the gold set — scoring the LLM judge the way the heuristic judge
is (see **Rigor** below and [`docs/RIGOR.md`](docs/RIGOR.md)) is the top roadmap
item.

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

## Rigor: auditing the auditor

A cited verdict is only worth the judge behind it, so Coehoorn measures that
judge — and then audits the measurements. Full detail, with every command and
its committed output, lives in [`docs/RIGOR.md`](docs/RIGOR.md); the headline of
each:

- **`meta-eval`** — the heuristic judge scores `balanced accuracy 0.66` on a
  frozen adversarial gold set (vs `0.50` for either dumb baseline), every rate
  carrying a Wilson 95% interval and gated on the interval floor.
- **`mutation-score`** — an honest **4/6** at catching planted broken judges; the
  two survivors name the gold cell that would catch them.
- **`metamorphic`** — a citation must survive a semantics-preserving edit, gated
  by Fisher's exact test with a Holm correction on the stochastic judge.
- **`overfit-audit`** — a Wilson bound tuned on the gold set is optimistic, so it
  reports the recall floor Bonferroni-corrected for the search, plus a self-play
  generalization gap that flags the overfit signature.
- **`distill-floor`** — distills the LLM judge's residual into a holdout-gated
  deterministic rule, trust-gated on correlation-corrected *effective* jury votes.
- **`selective-risk`** — certifies the judge's error on unseen sieges with a
  distribution-free Hoeffding bound that tightens at `O(1/sqrt(N))`.
- **`self-play`** — generates new seed-grounded attacks and pays a reward only
  when the breach cites a real turn and survives the stability gate.

See [`docs/EVAL.md`](docs/EVAL.md) for the metric definitions and gold-set
provenance, and [`docs/coverage-map.md`](docs/coverage-map.md) for how the
archetypes map onto OWASP LLM, OWASP Agentic, MITRE ATLAS, and NIST — gaps
advertised.

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
- **Plimsoll** (same org — this is dogfooding, not an external endorsement) is a
  span-level trace/policy gate for tool-using agents. `coehoorn/trace_export.py`
  converts a siege into Plimsoll's native traces (committed under
  [`runs/sample-tools/traces/`](runs/sample-tools/traces/)), so a second,
  independent analyzer re-derives the verdict from the raw run record: on the
  flawed demo agent, Plimsoll's policy
  ([`examples/plimsoll_policy_tools.json`](examples/plimsoll_policy_tools.json))
  flags the same forbidden `delete_account` call and approval-less refund the
  judge cites. `.github/workflows/trace-gate.yml` runs the agreement check
  (manual-only until Plimsoll ships on PyPI).

## Optional extras

Both are lazy — neither is imported on the core path; `import coehoorn` and the CLI
work with no extras installed.

```bash
# from a checkout — the working path today
uv sync --extra mcp              # coehoorn-mcp: lay a siege from any MCP-speaking agent
uv sync --extra inspect          # export a Report to an Inspect AI EvalLog

# from PyPI (PyPI publish pending — these commands work once v0.2.0 ships)
pip install 'coehoorn[mcp]'
pip install 'coehoorn[inspect]'
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
  overfit.py        # Judge-overfit audit — multiplicity-corrected Wilson bound + generalization gap + sample-k saturation
  cascade.py        # cheap->expensive tier telemetry {alpha, disagreement_rate, lossless_violations} at zero model spend
  distill.py        # distill a judge jury's high-consensus residual into a holdout-gated deterministic rule (effective votes)
  selective_risk.py # distribution-free conformal selective-risk certificate on unseen conjectured sieges (Hoeffding + convergence)
  mcp_redteam.py    # MCP tool-poisoning attack pack — offline loopback fixture + rug-pull / description-poisoning / cross-server-shadowing scenarios
  selfplay/         # seed-grounded attack conjecturer + SGS guide + gated self-play loop
  report_html.py    # the self-contained Siege Survey (no JS, no assets)
  cli.py            # coehoorn run / compare / meta-eval / mutation-score / metamorphic / overfit-audit / distill-floor / selective-risk / self-play / mcp-siege
  trace_export.py   # export a siege as Plimsoll traces (plain JSON, no dependency)
  mcp_server.py     # optional: MCP server (extra)
  inspect_export.py # optional: Inspect AI EvalLog export (extra)
ARCHITECTURE.md     # full data-flow walkthrough + the trust boundary
apps/stub-agent/    # deliberately-flawed local fixture (LOCAL ONLY)
examples/           # sample rubric + tool-policy rubric + expected-failures fixture
tests/gold/         # frozen, hand-labeled judge gold set
docs/               # RIGOR (auditing the auditor), EVAL, coverage-map, ADRs, one-page brief
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
