# Coehoorn — finding agent failures before they ship

**One line:** point Coehoorn at a chat or tool-using agent, describe the failure
modes you care about in plain English, and get back a ranked report of where it
breaks — with every failure cited to the exact conversation turn that proves it.

---

## The problem

Chat and tool-using agents fail in *conversation* — they capitulate under
pressure, fabricate a citation three turns in, miss a crisis signal, leak their
system prompt to a polite attacker, or fire a destructive tool without approval.
Unit tests don't see these; you find out in production, from a
screenshot. The failures are multi-turn, behavioral, and easy to wave away
because nobody can point at *where* it went wrong.

## A reliability lifecycle, and where this sits

Agent reliability is three jobs, not one. Coehoorn owns the first.

| Layer | Job | When | What it produces |
|---|---|---|---|
| **Discover** *(Coehoorn)* | find failures through adversarial simulation | pre-deploy | cited breach reports + reusable adversarial traces |
| **Prevent** | block known failures from regressing | at deploy | a pass/fail CI gate over frozen traces |
| **Account** | audit and explain live behavior | in production | runtime logs, attributions |

They compose in one direction: the adversarial traces Coehoorn *discovers* are
exactly the fixtures a prevention gate replays. Coehoorn deliberately does **not**
gate — whether a breach should fail your build is a downstream policy decision.

## What makes the discovery layer trustworthy

Most red-team tools hand you a verdict you have to trust. Coehoorn makes a
dishonest verdict structurally impossible, and proves its own judge is calibrated.

1. **Cited evidence as a schema invariant.** A failure verdict that names no turn
   — or cites a turn that isn't in the transcript — cannot be constructed. It is a
   Pydantic validation error, not a prompt convention. *(Runnable in 10 seconds,
   no setup.)*
2. **It audits its own judge.** Coehoorn scores its judge against a frozen, hand-
   labeled gold set — precision/recall/balanced-accuracy/κ, each with a Wilson
   confidence interval, against dumb baselines. The gold set is stacked with
   adversarial near-misses, so the score is honestly below 1.0; the gap is the
   stated reason to use the stronger judge.
3. **A report you actually read.** One self-contained HTML "siege survey" — a fort
   under attack, breaches drawn as gaps in the wall at the cited turn. No
   dashboard, no server, opens offline.
4. **Reproducible and private.** Heuristic mode is deterministic to the byte and
   needs no API key; nothing leaves the machine — no telemetry, no callbacks.

## Honest scope

Coehoorn covers a narrow, deep slice: multi-turn behavioral failures with cited
evidence. It is **not** a broad scanner — it has six adversarial archetypes, not
a probe library. Its tool-use coverage is itself a thin slice — forbidden-tool
calls and approval/privilege bypass (OWASP Agentic ASI02/ASI03) — and it does not
test training-data extraction, multimodal inputs, or run automated jailbreak
search. The schema
guarantees a verdict is anchored to real evidence; it does not guarantee the
judge's reasoning about that evidence is correct. (Full mapping to OWASP LLM,
MITRE ATLAS, and NIST — gaps advertised — ships with the project.)

## Why it reads as serious work

Eval rigor most projects skip (a self-auditing meta-eval with confidence
intervals and a regression gate on the interval floor — *and* an audit of that
audit: a judge mutation score that proves the gold set catches a relocated
citation, and a metamorphic citation-stability check gated with Fisher's exact +
Holm rather than a normal-approximation z-test); a dependency budget held to five
runtime packages with the rejections written down; an MCP server so other agents
can run a siege, and an Inspect AI exporter so a run opens in the standard eval
viewer. Red-team methodology, agent reliability, and clean product thinking in one
small, finished thing.
