# Methodology — how a Coehoorn engagement works

*Buyer-facing. This is the "how we work" document: the reliability lifecycle we
operate in, the principle that makes our findings trustworthy, what you receive,
and who does what. It describes a process built around the tool in this
repository — nothing here claims a capability the code does not have.*

The companion documents are the [SOW template](./SOW_TEMPLATE.md) (scope,
phases, pricing), the [discovery questionnaire](./DISCOVERY_QUESTIONNAIRE.md)
(scoping intake), and the [ROI model](./ROI_MODEL.md) (cost-benefit inputs and
formula). The per-engagement findings report is scaffolded by
[`../ENGAGEMENT_TEMPLATE.md`](../ENGAGEMENT_TEMPLATE.md).

---

## 1. Where Coehoorn sits — the reliability lifecycle

Agent reliability is three jobs, not one. Coehoorn owns the first and refuses
to pretend it owns the others.

```
   DISCOVER (Coehoorn)  →  PREVENT (a CI gate)  →  ACCOUNT (runtime)
   find failures           block regressions       audit live behavior
   pre-deploy              at deploy                in production
```

| Layer | Job | What it produces |
|---|---|---|
| **Discover** *(our engagement)* | find failures through adversarial simulation | cited breach reports + reusable adversarial traces |
| **Prevent** | block known failures from regressing | a pass/fail CI gate over frozen traces |
| **Account** | audit and explain live behavior | runtime logs, attributions |

These compose in one direction: the adversarial traces we *discover* are exactly
the fixtures a prevention gate replays. Coehoorn deliberately **does not gate** —
whether a discovered breach should fail your build is a policy decision we hand
back to you, not one we make for you (the `run` exit code is `0` unless you opt
into gate semantics with `--fail-on-breach`).

We will say plainly when something is outside the Discover layer. We do not ship
your runtime observability or your production guardrails; we surface, with
evidence, where the agent breaks before it ships.

---

## 2. The core principle — audit the auditor

Most red-team work hands you a verdict you have to trust. The whole point of
this engagement is that you don't have to.

**Cited evidence is a schema invariant, not a convention.** A failure verdict
that names no transcript turn — or that cites a turn which isn't in the
transcript — *cannot be constructed*. It is a Pydantic validation error, not a
prompt we hope the model follows. A "pass" that cites a breach, a worst-moment
that doesn't match any cited failure, an out-of-range citation: none can exist
in a delivered report. (See the ten-second demonstration in the project
[`README.md`](../../README.md) and the trust boundary in
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md).)

**We grade our own judge, and show you the score — including where it is weak.**
A cited verdict is only worth the judge that produced it, so:

- `coehoorn meta-eval` scores the judge against a frozen, hand-labeled gold set
  and reports the full confusion matrix — precision, recall, specificity, each
  with a **Wilson 95% interval**, plus F1, balanced accuracy, and Cohen's κ —
  beside two dumb baselines (always-breach, always-hold).
- The gold set is deliberately stacked with adversarial near-misses, so the
  cheap deterministic judge scores honestly **below 1.0**. That gap is the
  documented argument for the stronger LLM judge, not a number we hide.
- `coehoorn mutation-score` audits *that* audit: it plants broken "mutant"
  judges and checks the gold set catches each, so we can show the gold has
  teeth (and name the cells where it doesn't yet).
- `coehoorn metamorphic` (CITE-MR) checks that a citation survives a
  semantics-preserving edit — rename the persona, renumber turns, insert a
  neutral turn — so a finding can't rest on a citation that flickers.

The honest limit, stated up front: the schema guarantees a verdict is *anchored*
to real evidence; it does not guarantee the judge's *reasoning* about that
evidence is correct. What we offer against that gap is measurement, not a
promise — see §6.

---

## 3. The five phases

The phases below are the spine of every engagement and map one-to-one onto the
SOW. Each produces a concrete artifact you keep.

| # | Phase | What happens | You receive |
|---|---|---|---|
| 1 | **Discovery** | Scope the agent: failure modes that matter, the wire contract, SOPs/policies to encode, success definition, data/PII constraints, OWASP-LLM/ASI targets. Driven by the [discovery questionnaire](./DISCOVERY_QUESTIONNAIRE.md). | A signed-off **rubric** (`*.yaml`), a target-scope memo, and a wired endpoint contract. |
| 2 | **Baseline siege** | Point Coehoorn at the agent and run the adversarial archetypes across multi-turn conversations. Establishes where the walls stand today. | The first **Siege Survey** (self-contained HTML), plus `--json`, SARIF, and JUnit. |
| 3 | **Cited findings** | Every breach written up against the exact transcript turn that proves it, ranked, mapped to OWASP/ASI, with a recommended fix per breach class. | The per-engagement findings report ([`../ENGAGEMENT_TEMPLATE.md`](../ENGAGEMENT_TEMPLATE.md)), each row citing a turn. |
| 4 | **Remediation verification** | After your team fixes, re-run the *same* rubric and confirm the cited breach disappears (or the SARIF result count drops). The fix is verified against the same evidence that found it. | A before/after delta and a re-siege report. |
| 5 | **Continuous-siege handoff** | Wire the siege into your CI as a standing gate (on demand + on PR), and hand over the rubric, the conjecturer config, and runbooks so your team owns it. | A configured `external-siege.yml`, owned rubric, and a handoff runbook. |

Phases 2 and 4 use the identical command and rubric — that symmetry is what
makes "the breach is gone" a checkable claim rather than an assurance.

---

## 4. How a finding is made non-hand-wavy

A delivered breach is not "the agent seems unsafe." It is a row that carries:

- the **archetype / persona** that drove the conversation (`emotional`,
  `injector`, `contradictor`, `ambiguous`, `off_topic`, `edge_case`, plus the
  optional KB-poisoner write-back persona);
- the **criterion** it broke (from your signed-off rubric);
- the **cited turn index** — the single transcript turn that proves it; and
- the **rationale** the judge recorded for that verdict.

The same SARIF the finding cites is what your team already consumes in the
Security tab; the same JUnit is what your test report renders. We are not asking
you to trust a new dashboard — we surface the breach where you already look.

For tool-using agents, a breach can also be a **tool-policy** violation cited to
the turn: a forbidden-tool call (OWASP Agentic **ASI02**, tool misuse) or a
privileged action taken without prior approval (**ASI03**), judged from the
agent's reported `tool_calls`, not its prose.

---

## 5. Roles & RACI

Two-party model: **us** (the engagement team operating Coehoorn) and **you**
(the client team that owns the agent). Adjust names in the SOW.

| Activity | Us | You |
|---|---|---|
| Define failure modes & success criteria | **C** | **A/R** |
| Author the rubric YAML | **R** | **A** (sign-off) |
| Provide the endpoint, auth, and wire-contract details | **C** | **R** |
| Run the baseline & re-sieges | **A/R** | **C** |
| Triage and prioritize cited breaches | **R** | **A** |
| Implement fixes in the agent | **C** | **A/R** |
| Wire the continuous-siege CI | **R** | **A** |
| Own the rubric & siege after handoff | **C** | **A/R** |
| Supply/scope any LLM-mode API key & approve its cost | **C** | **A/R** |

*R = Responsible, A = Accountable, C = Consulted.* The agent's source code and
production fixes stay with you; we operate the harness against your endpoint and
hand back evidence, rubrics, and CI wiring.

---

## 6. What we will not claim

Stated up front so the rest can be taken literally:

- **We do not certify the agent "safe."** We surface cited breaches against a
  scoped rubric. Absence of a breach in scope is not proof of safety.
- **We do not guarantee judge reasoning is correct** — only that every verdict
  is anchored to checkable evidence, and that we *measure* the judge's
  calibration (meta-eval) and its citation stability (CITE-MR) rather than
  asserting them.
- **We cover a narrow, deep slice**, not the whole attack surface. Six
  adversarial archetypes; tool-use limited to ASI02/ASI03; no training-data
  extraction, multimodal inputs, or automated jailbreak search. The full,
  gaps-advertised mapping to OWASP LLM, MITRE ATLAS, and NIST is in
  [`../coverage-map.md`](../coverage-map.md).
- **The LLM-judge path's accuracy is not yet independently scored** the way the
  heuristic judge is. Where an engagement relies on it, we say so and treat its
  numbers as `pending` until measured (it is the top open item in
  [`../../ROADMAP.md`](../../ROADMAP.md)).
- **Numbers in any deliverable are real only once a real endpoint and key are
  supplied.** We do not paste fabricated results into a report; an empty table
  is more honest than an invented one.

---

## 7. What you walk away owning

- A **rubric** that encodes your failure modes in plain English — yours to
  version and extend.
- A library of **adversarial traces** (the breaches we found), which are exactly
  the fixtures a regression gate replays.
- A **continuous siege** wired into your CI, no-op-safe when no endpoint is set.
- The **judge-calibration evidence** (meta-eval / mutation-score / CITE-MR
  outputs) so a future reviewer can re-audit the auditor.
- Reproducibility: heuristic mode is deterministic to the byte and needs no API
  key, so any finding can be re-run on your own infrastructure with nothing
  leaving the machine.
