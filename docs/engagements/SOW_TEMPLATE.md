# Statement of Work — Coehoorn agent-reliability siege

*Fill-in-the-blanks SOW for a single engagement. Every `[BRACKETED]` token is a
client specific to replace; delete the guidance blockquotes before sending. The
**pricing model is illustrative** — the ranges are a planning aid, not a quote.*

The working method behind this SOW is in [METHODOLOGY.md](./METHODOLOGY.md); the
scoping intake that fills §2–§3 is the
[discovery questionnaire](./DISCOVERY_QUESTIONNAIRE.md); the business case is the
[ROI model](./ROI_MODEL.md); the findings deliverable produced in Phase 3 is
[`../ENGAGEMENT_TEMPLATE.md`](../ENGAGEMENT_TEMPLATE.md).

---

## 1. Parties & summary

| field | value |
|---|---|
| Client | `[CLIENT]` |
| Engagement | Adversarial reliability siege of `[AGENT NAME]` |
| Provider | `[PROVIDER]` |
| Effective date | `[YYYY-MM-DD]` |
| Primary contacts | `[CLIENT CONTACT]` / `[PROVIDER CONTACT]` |
| Tool of record | Coehoorn `[version + git sha]` — adversarial red-team harness for chat and tool-using agents |

**In one line:** point Coehoorn at `[AGENT NAME]`, find where it breaks under
adversarial multi-turn pressure — every breach cited to the transcript turn that
proves it — verify the fixes against the same evidence, and hand back a standing
CI siege the `[CLIENT]` team owns.

---

## 2. Objectives

> Pull these from the discovery questionnaire (§"success definition" and
> "failure modes that matter"). Keep them few and testable.

1. Establish a **baseline** of cited breaches for `[AGENT NAME]` against a
   `[CLIENT]`-approved rubric.
2. Prioritize breaches by `[severity / criterion weight / business impact]` and
   recommend a concrete fix per breach class.
3. **Verify** that fixes close the cited breaches by re-running the same rubric.
4. **Hand off** a continuous siege wired into `[CLIENT]`'s CI, plus the rubric
   and runbooks, so the team owns the loop.

---

## 3. Scope

### In scope

- The target agent `[AGENT NAME]`, reachable at the `[CLIENT]`-supplied endpoint
  speaking the wire contract `POST {conversation:[{role,content}...]} -> {reply}`
  (optionally `{..., tool_calls:[{name,...}]}` for tool-policy criteria).
- Up to **`[6]` adversarial archetypes** — `contradictor`, `ambiguous`,
  `emotional`, `off_topic`, `injector`, `edge_case` — across `[4]`-turn
  conversations, optionally the **KB-poisoner** write-back persona.
- Failure modes encoded in the rubric: `[e.g. self-harm safety referral,
  fabricated citations, prompt-injection / system-prompt leakage, forbidden-tool
  calls (ASI02), approval-bypass (ASI03)]`.
- Optional **self-play conjecturer** (`coehoorn self-play`) to generate fresh
  seed-grounded attacks from logged breaches — `[include / exclude]`.
- Mode: `[heuristic (offline, deterministic, no key) | llm (Anthropic personas +
  judge, requires ANTHROPIC_API_KEY)]`.

### Out of scope (explicit)

> Coehoorn covers a narrow, deep slice. Listing the exclusions is the point — see
> [`../coverage-map.md`](../coverage-map.md) for the full gaps-advertised mapping.

- Training-data / memorization extraction; model-weight or infrastructure
  attacks; supply-chain.
- Multimodal (image/audio/video) adversarial inputs — text chat only.
- Automated jailbreak search (GCG/TAP/suffix-style optimization).
- Agentic surfaces beyond ASI02/ASI03: indirect injection via tool outputs,
  memory/context poisoning (ASI06), inter-agent comms (ASI07), multi-agent
  cascades (ASI08).
- Output-handling sinks (XSS/SSRF/code-exec), DoS / cost exhaustion, bias /
  toxicity-at-scale, CBRN.
- Production runtime guardrails and observability — that is the **Account** layer
  downstream of this engagement (see [METHODOLOGY.md §1](./METHODOLOGY.md)).
- Fixing the agent's code — `[CLIENT]` implements fixes; we verify them.

---

## 4. Phases, activities & deliverables

> The five phases mirror [METHODOLOGY.md §3](./METHODOLOGY.md). Durations are
> placeholders to be set during scoping.

| Phase | Activities | Deliverable | Indicative window |
|---|---|---|---|
| **1. Discovery** | Run the discovery questionnaire; author + sign off the rubric YAML; wire & smoke-test the endpoint contract. | Signed-off rubric, target-scope memo, wired endpoint. | `[~1 week]` |
| **2. Baseline siege** | Run the archetypes (and optional self-play / KB-poisoner) against the agent; produce the first Siege Survey. | Baseline Siege Survey (HTML) + `--json` + SARIF + JUnit. | `[~1 week]` |
| **3. Cited findings** | Write up every breach against its cited turn; rank; map to OWASP/ASI; recommend a fix per breach class. | Findings report ([`../ENGAGEMENT_TEMPLATE.md`](../ENGAGEMENT_TEMPLATE.md)), every row citing a turn. | `[~1 week]` |
| **4. Remediation verification** | After `[CLIENT]` fixes, re-run the identical rubric; produce a before/after delta. | Re-siege report + breach delta. | `[~1–2 weeks, gated on fixes]` |
| **5. Continuous-siege handoff** | Wire `external-siege.yml` into `[CLIENT]` CI (on demand + on PR); hand over rubric, conjecturer config, runbooks. | Configured CI siege, owned rubric, handoff runbook. | `[~1 week]` |

**Standing deliverables across all phases:** judge-calibration evidence
(`meta-eval`, `mutation-score`, `metamorphic` outputs) so the auditor is itself
auditable; all reports self-contained and offline-openable.

---

## 5. Timeline

> A typical engagement is `[~5–6 weeks]` of provider effort, with Phase 4 paced
> by `[CLIENT]`'s fix cadence. Replace with the agreed schedule.

```
Wk 1     Wk 2        Wk 3       Wk 4–5            Wk 6
Discovery Baseline   Cited      Remediation       Continuous-siege
          siege      findings   verification      handoff
```

---

## 6. Assumptions

- `[CLIENT]` provides a reachable `[staging / non-production]` endpoint for the
  agent, plus any auth (bearer token or raw header) needed to drive it.
- For LLM mode, `[CLIENT]` supplies (or authorizes the cost of) an
  `ANTHROPIC_API_KEY`; this is distinct from any auth Coehoorn uses to reach the
  target. Heuristic mode needs no key.
- `[CLIENT]` nominates an owner to triage findings and a path to implement fixes
  within the engagement window.
- The agent speaks the documented wire contract, or `[CLIENT]` accepts a thin
  adapter (wrap `HttpAgentAdapter` / supply an `async (conversation) -> str`
  callable) to bridge a bespoke shape.
- Test traffic against `[CLIENT]`'s endpoint is `[CLIENT]`-authorized; adversarial
  probes will include `[self-harm language / injection strings / etc.]` by design.

---

## 7. Exclusions & constraints

- No telemetry, analytics, or external callbacks are introduced; the only
  outbound network is to `[CLIENT]`'s endpoint and, in LLM mode,
  `api.anthropic.com`. (See [`../../SECURITY.md`](../../SECURITY.md).)
- We do not store or exfiltrate `[CLIENT]` data beyond the transcripts needed to
  cite breaches; retention and handling per §9.
- Findings reflect the agent and rubric **as tested on `[date/sha]`**; they are
  not a standing certification.
- Effort beyond the agreed phases (new rubrics, new agents, scope expansion) is a
  `[change order]`.

---

## 8. Acceptance criteria

The engagement is accepted when **all** hold:

1. A **baseline Siege Survey** is delivered in which every breach row cites a
   real transcript turn (guaranteed by the schema — an uncited breach cannot be
   delivered).
2. The accompanying **SARIF and JUnit** validate and load in `[CLIENT]`'s
   Security tab / test reporter.
3. **Judge-calibration evidence** is attached: a `meta-eval` report with Wilson
   intervals against baselines, and a `mutation-score` result.
4. For every breach class `[CLIENT]` elects to fix, a **re-siege** shows the
   cited breach closed (or the SARIF result count reduced), re-run with the same
   rubric.
5. The **continuous-siege CI** runs green against the configured target (and
   no-ops cleanly when no endpoint is set) on `[CLIENT]`'s infrastructure.
6. `[CLIENT]` can **reproduce** any heuristic-mode finding byte-for-byte from the
   handed-over rubric and command.

> Acceptance is about *evidence and reproducibility*, not a breach count. We do
> not commit to "find N breaches" — a clean baseline that the client can
> re-verify is a valid, accepted outcome.

---

## 9. Data handling & PII

> Complete from the discovery questionnaire's data/PII section.

- Transcripts may contain `[describe expected content / PII class]`; handling:
  `[redaction / retention window / storage location]`.
- Reports are self-contained HTML with no external assets and open offline;
  `[CLIENT]` controls distribution.
- `[Any client-specific data-processing terms / DPA reference]`.

---

## 10. Pricing model — ILLUSTRATIVE

> **These figures are illustrative planning ranges, not a quote and not a past
> client result.** Replace with a negotiated fee. Numbers are placeholders.

Three structures, pick one:

| Model | When it fits | Illustrative range |
|---|---|---|
| **Fixed-fee, scoped** | Well-defined agent + rubric, the five phases as written. | `[$X]`–`[$Y]` for the full engagement |
| **Time & materials** | Evolving scope or multiple agents. | `[$Z]` / provider-day, est. `[N]` days |
| **Retainer (continuous siege)** | Ongoing, post-handoff: standing siege + monthly findings review. | `[$R]` / month |

**Illustrative cost drivers** (what moves the number, not a price list):

- Number of agents / endpoints and rubric complexity (criteria count, tool-use).
- Heuristic vs LLM mode — LLM mode adds **API token cost**, billed `[at cost /
  estimated $K]`, separate from provider fees and dependent on personas × turns ×
  resamples.
- Whether self-play conjecturing is included (adds compute + analysis).
- Depth of remediation verification (number of fix cycles).
- Handoff scope (CI wiring + enablement / training).

> Every dollar figure above is a `[PLACEHOLDER]`. See the
> [ROI model](./ROI_MODEL.md) for how to frame value against `[CLIENT]`-supplied
> cost inputs — that document also carries only client-supplied or
> clearly-labelled illustrative numbers.

---

## 11. Signatures

| | Client | Provider |
|---|---|---|
| Name | `[ ]` | `[ ]` |
| Title | `[ ]` | `[ ]` |
| Date | `[ ]` | `[ ]` |
