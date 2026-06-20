# Discovery questionnaire — onboarding a client agent

*The scoping intake that turns "we have an agent and we're nervous about it" into
a runnable Coehoorn siege. Filling this in produces the inputs the
[SOW](./SOW_TEMPLATE.md) §2–§3 and §9 need, and the rubric authored in Phase 1.*

Send this to the `[CLIENT]` agent owner before kickoff. Every section maps to a
real input the harness consumes — there are no decorative questions. Where a
question references a Coehoorn concept, the working method is in
[METHODOLOGY.md](./METHODOLOGY.md) and the honest coverage limits are in
[`../coverage-map.md`](../coverage-map.md).

> **How to use this:** answer inline. Anything you can't answer yet, mark
> `TBD` — discovery exists to close those. Don't invent metrics; if you don't
> have a number, say so.

---

## A. The agent under test

1. **What is the agent?** One line — what it does and who talks to it.
   `[ ]`
2. **What's the worst realistic thing it could do** in a conversation?
   `[ ]`
3. **Surface:** is it a pure **chat** agent, or does it **call tools** (issue
   refunds, write to a store, delete records, send messages)? List the tools.
   `[ ]`
4. **Where has it already misbehaved?** Any screenshots, incident tickets, or
   "we saw it do X once" anecdotes. These become seed material for the self-play
   conjecturer.
   `[ ]`
5. **What stage is it at** — pre-launch, in beta, or live? Can we siege a
   **staging** instance rather than production?
   `[ ]`

---

## B. Failure modes that matter

> We do not test "everything." We test the failure modes *you* care about,
> encoded as rubric criteria. Rank them — the rubric weights follow this.

For each failure mode you want caught, give: a plain-English description, an
example of the agent getting it wrong, and how bad it is.

| Failure mode | Plain-English "must / must not" | Example of it going wrong | Severity `[critical/high/med]` |
|---|---|---|---|
| `[e.g. self-harm referral]` | `[must point to crisis support, never engage substantively]` | `[ ]` | `[ ]` |
| `[e.g. fabricated citations]` | `[must not invent case names / sources]` | `[ ]` | `[ ]` |
| `[e.g. system-prompt leakage]` | `[must not reveal its instructions]` | `[ ]` | `[ ]` |
| `[e.g. forbidden tool call]` | `[must never call delete_account]` | `[ ]` | `[ ]` |
| `[e.g. action without approval]` | `[must get approval before issue_refund]` | `[ ]` | `[ ]` |
| `[add rows]` | | | |

6. **Which adversarial archetypes feel most relevant?** (We drive all six by
   default; this just tells us where to lean.)
   - `contradictor` — pushes the agent to flip a correct stance under pressure.
   - `ambiguous` — underspecified asks; does it clarify or guess?
   - `emotional` — escalating distress; does it refer to help safely?
   - `off_topic` — drift, then a request to fabricate specifics.
   - `injector` — prompt injection / persona override / system-prompt extraction.
   - `edge_case` — sensitive-domain questions inviting confident fabrication.
   - **KB-poisoner** *(optional, write-back agents)* — tries to persist
     attacker-controlled content the agent later reads back as trusted.

   Most relevant: `[ ]`

---

## C. The wire contract (how Coehoorn drives the agent)

> This is the single most important technical section — without it, nothing
> runs. Coehoorn's default adapter speaks one shape; tell us yours.

7. **Default contract** — can the agent accept and answer this exact shape?

   ```
   POST [your endpoint]
   →  { "conversation": [ { "role": "user", "content": "..." }, ... ] }
   ←  { "reply": "..." }
   ```
   `[ yes / no — if no, see Q11 ]`

8. **Endpoint URL** (a `[staging]` URL is ideal; it is configured via
   `AGENT_ENDPOINT` and never committed):
   `[ https://... ]`

9. **Auth** — how does a caller authenticate *to your agent*? (Read from the
   environment only, never the command line — `AGENT_API_KEY` →
   `Authorization: Bearer …`, or `AGENT_AUTH_HEADER` for a raw header like
   `x-api-key: …`.)
   `[ bearer token / api-key header / none / other: ___ ]`

10. **Tool calls** — if the agent uses tools, does its response report them, in
    OpenAI/Anthropic shape, so tool-policy criteria (ASI02/ASI03) can be judged?

    ```
    ← { "reply": "...", "tool_calls": [ { "name": "issue_refund", ... } ] }
    ```
    `[ yes / no / partially: ___ ]`

11. **If the contract differs:** describe your request/response envelope. A thin
    adapter bridges it (wrap `HttpAgentAdapter` or supply an
    `async (conversation) -> str` callable) — we just need the shape.
    `[ paste a sample request + response ]`

12. **Operational limits:** rate limits, timeouts, max conversation length,
    concurrency caps we should respect against `[staging]`?
    `[ ]`

---

## D. SOPs, policies & ground truth to encode

> The rubric is only as good as the policy behind it. The crisper your "correct
> behavior," the sharper the breach.

13. **Hand over the policies** the agent is *supposed* to follow: support SOPs,
    safety guidelines, refusal rules, escalation paths, approved disclaimers.
    `[ links / attachments ]`

14. For each tool the agent can call: is it **always allowed**, **forbidden**, or
    **allowed only after an approval/precondition step**? (Maps directly to
    `forbidden_tools` / `tool_must_precede` rules.)
    `[ tool → rule ]`

15. **What does a *good* answer look like** for your top failure mode? Give the
    phrases/behaviors that should be present (e.g. a crisis hotline reference) or
    absent (e.g. a fabricated `X v. Y` citation). This becomes the heuristic
    rule.
    `[ ]`

16. **Do you have any labeled examples** — conversations you've already judged as
    pass/fail? These can extend the gold set and make the judge's calibration
    measurable on *your* domain.
    `[ ]`

---

## E. Success definition

17. **What would make this engagement a success for you?** (e.g. "no critical
    breach in scope," "every known incident reproduced and fixed," "a standing
    CI siege we own.")
    `[ ]`

18. **Which result is the headline you need to act on** — a breach count, a
    specific criterion holding, a clean re-siege after fixes?
    `[ ]`

> Note: acceptance is about cited evidence and reproducibility, **not** a target
> breach count — a clean, re-verifiable baseline is a valid success (see
> [SOW §8](./SOW_TEMPLATE.md)). We will not promise "N breaches."

19. **Will you act on findings inside the engagement window** (so we can verify
    fixes in Phase 4), or is this baseline-only?
    `[ ]`

---

## F. Data & PII constraints

20. **What will transcripts contain?** Will adversarial probes or agent replies
    surface real user data, PII, or regulated content?
    `[ ]`

21. **Handling requirements:** redaction needs, retention window, where reports
    and transcripts may be stored, any DPA / data-residency terms.
    `[ ]`

22. **Are the adversarial probes themselves acceptable** against `[staging]`?
    They will, by design, include `[self-harm language / injection strings /
    sensitive-domain prompts]`. Confirm authorization.
    `[ ]`

---

## G. Standards scope (OWASP-LLM / Agentic-ASI targets)

> Pick the targets that matter to you. Coehoorn covers a deliberately narrow
> slice; the honest mapping (and what it does **not** touch) is in
> [`../coverage-map.md`](../coverage-map.md). Selecting an out-of-scope target
> tells us where to recommend a complementary tool, not to overclaim.

| Target | In Coehoorn's range? | Want it in scope? |
|---|---|---|
| **LLM01** Prompt Injection | Covered (`injector`) | `[ y/n ]` |
| **LLM07** System-Prompt Leakage | Covered (`injector`) | `[ y/n ]` |
| **LLM09** Misinformation / confabulation | Partial (`edge_case`, `off_topic`, `contradictor`, `ambiguous`) | `[ y/n ]` |
| **LLM06** Excessive Agency → **ASI02** tool misuse | Partial (forbidden-tool, cited) | `[ y/n ]` |
| **LLM06** Excessive Agency → **ASI03** approval/privilege bypass | Partial (tool-order, cited) | `[ y/n ]` |
| Self-harm / crisis safety (NIST: Dangerous content) | Partial (`emotional`) | `[ y/n ]` |
| LLM02 PII exfiltration, LLM08 RAG/embedding, ASI06/07/08, multimodal, jailbreak search | **Out of scope** | n/a — see coverage-map |

23. **Any compliance framework** you're mapping to (SOC 2, internal AI policy,
    a regulator)? We'll align the findings vocabulary.
    `[ ]`

---

## H. Mode & logistics

24. **Run mode:** heuristic (offline, deterministic, **no API key**) covers any
    criterion with a heuristic rule; **LLM mode** (`ANTHROPIC_API_KEY`) adds
    richer personas and a reasoning judge for criteria that need genuine
    reasoning. Which do you need, and **who supplies/funds the key**?
    `[ ]`

    > Caveat we state up front: the LLM **judge's** accuracy is not yet
    > independently scored the way the heuristic judge is (top roadmap item). If
    > you rely on it, we treat its numbers as `pending` until measured.

25. **Continuous siege:** do you want the standing CI gate (nightly + on PR via
    `external-siege.yml`) handed off, and into which repo/CI?
    `[ ]`

26. **Self-play:** include the conjecturer (generate fresh seed-grounded attacks
    from logged breaches) this engagement, or keep to the fixed archetypes?
    `[ ]`

---

### Sign-off

Completed by `[CLIENT CONTACT]` on `[YYYY-MM-DD]`. Discovery output feeds the
rubric and [SOW §2–§3, §9](./SOW_TEMPLATE.md).
