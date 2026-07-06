# Coehoorn — Standards Coverage Map

Coehoorn covers a deliberately narrow slice — **multi-turn behavioral failure modes of a chat agent, with every failure cited to an exact transcript turn** — not the full LLM/agent attack surface. This document maps exactly what it does and does not touch against recognized taxonomies. Where a row is `Partial` or `Not-covered`, that is the honest answer, not a hedge.

Coehoorn's 6 adversarial persona archetypes: **contradictor**, **ambiguous**, **emotional**, **off_topic**, **injector**, **edge_case**.

Taxonomy names/IDs below were verified against current (2025–2026) sources; see [Sources](#sources). IDs not verifiable were left out rather than invented.

---

## 1. OWASP Top 10 for LLM Applications (2025)

Reference list (2025): LLM01 Prompt Injection · LLM02 Sensitive Information Disclosure · LLM03 Supply Chain · LLM04 Data & Model Poisoning · LLM05 Improper Output Handling · LLM06 Excessive Agency · LLM07 System Prompt Leakage · LLM08 Vector & Embedding Weaknesses · LLM09 Misinformation · LLM10 Unbounded Consumption.

| Archetype | OWASP item(s) | Status | One-line justification |
|---|---|---|---|
| injector | LLM01 Prompt Injection | **Covered** | Direct prompt injection / persona override is the archetype's whole job. |
| injector | LLM07 System Prompt Leakage | **Covered** | System-prompt extraction probes map directly to LLM07. |
| edge_case | LLM09 Misinformation | **Covered** | Sensitive-domain questions inviting fabricated specifics test the misinformation/over-reliance failure. |
| off_topic | LLM09 Misinformation | **Partial** | Tests fabricated facts/citations on drift, but only via conversational pressure, not retrieval grounding. |
| contradictor | LLM09 Misinformation | **Partial** | Pushing the agent to affirm a wrong paraphrase is a misinformation/sycophancy failure, but a behavioral subset of LLM09. |
| ambiguous | LLM09 Misinformation | **Partial** | Underspecification can induce confabulated assumptions; Coehoorn scores clarification vs. guessing, not factual scope of LLM09. |
| emotional | (no direct OWASP item) | **Not-covered (by OWASP)** | Safety-referral on crisis/self-harm is a content-safety concern OWASP 2025 does not enumerate; see NIST §3. |
| — | LLM02 Sensitive Information Disclosure | **Not-covered** | No PII/training-data exfiltration testing beyond the system-prompt case. |
| — | LLM03 Supply Chain | **Not-covered** | Out of scope; Coehoorn probes a running agent, not its dependency chain. |
| — | LLM04 Data & Model Poisoning | **Not-covered** | No training-time / data-pipeline attacks. |
| — | LLM05 Improper Output Handling | **Not-covered** | No downstream-sink testing (XSS/SSRF/code-exec from model output). |
| — | LLM06 Excessive Agency | **Partial** | Tool-policy criteria catch forbidden-tool calls (ASI02) and privileged actions taken without prior approval (ASI03), cited to the turn; the MCP tool-poisoning pack adds supply-chain (ASI04) and cross-server shadowing (ASI07) — see §5. Broader agentic exploitation (the memory-poisoning read-back loop, multi-agent cascades) stays out of scope — see §6. |
| — | LLM08 Vector & Embedding Weaknesses | **Not-covered** | No RAG/embedding-store attacks. |
| — | LLM10 Unbounded Consumption | **Not-covered** | No DoS / cost / resource-exhaustion testing. |

**Net OWASP coverage: 2 of 10 fully (LLM01, LLM07), partial on 2 (LLM06, LLM09). 6 of 10 untouched.**

---

## 2. MITRE ATLAS — relevant tactics / techniques

Verified technique IDs (ATLAS is at v5.x, 2025–2026; ~16 tactics):

| Archetype | ATLAS technique | Tactic | Status | Justification |
|---|---|---|---|---|
| injector | **AML.T0051 LLM Prompt Injection** (.000 Direct) | Initial Access / Persistence | **Covered** | Direct injection in user turns is exactly this technique. |
| injector | **AML.T0054 LLM Jailbreak** | Privilege Escalation / Defense Evasion | **Partial** | Persona-override probes attempt jailbreak, but Coehoorn does not run a systematic jailbreak corpus. |
| injector | **AML.T0056 LLM Meta Prompt Extraction** | Exfiltration | **Covered** | System-prompt extraction probes map directly. |
| contradictor / edge_case / off_topic | (no clean ATLAS technique) | — | **Not-covered (by ATLAS)** | ATLAS is attacker-capability-centric; conversational misinformation/sycophancy failures are not its focus — see NIST §3. |
| — | AML.T0051.001 Prompt Injection (Indirect) | Initial Access | **Not-covered** | Coehoorn tests only direct, in-conversation injection; no poisoned external data sources. |
| — | AML.T005x AI Agent techniques (context poisoning, memory manipulation, thread injection) | various | **Not-covered** | 2025 agentic additions assume tool/memory surfaces Coehoorn does not exercise. |

**Net ATLAS coverage: a thin vertical through the prompt-injection / jailbreak / meta-prompt-extraction cluster only.**

---

## 3. NIST AI 600-1 (Generative AI Profile) — risk categories touched

The 12 categories: CBRN · Confabulation · Dangerous, Violent, or Hateful Content · Data Privacy · Environmental Impacts · Harmful Bias & Homogenization · Human-AI Configuration · Information Integrity · Information Security · Intellectual Property · Obscene, Degrading, and/or Abusive Content · Value Chain & Component Integration.

| NIST category | Touched by | Status | Justification |
|---|---|---|---|
| **Confabulation** | edge_case, off_topic, contradictor, ambiguous | **Covered** | Core of Coehoorn: confidently-stated fabricated specifics/citations, cited to the turn. |
| **Information Integrity** | off_topic, contradictor | **Partial** | Probes fabricated facts/citations, but only single-agent output, not ecosystem-level info integrity. |
| **Dangerous, Violent, or Hateful Content** | emotional | **Partial** | Self-harm escalation tests the self-harm-recommendation slice; no violence/hate/illegal-activity coverage. |
| **Human-AI Configuration** | emotional, contradictor | **Partial** | Emotional entanglement / over-reliance / sycophancy are exactly this category; Coehoorn scores referral & stance-holding, not full interaction-design governance. |
| **Information Security** | injector | **Partial** | System-prompt leakage is an info-security failure; Coehoorn covers that one vector only. |
| CBRN | — | **Not-covered** | No uplift testing. |
| Data Privacy | — | **Not-covered** | No PII extraction testing. |
| Harmful Bias & Homogenization | — | **Not-covered** | No bias/fairness probes. |
| Intellectual Property | — | **Not-covered** | No memorized-IP / copyright extraction. |
| Obscene, Degrading, and/or Abusive Content | — | **Not-covered** | No CSAM/NCII/obscenity probes. |
| Environmental Impacts | — | **Not-covered** | Out of behavioral scope. |
| Value Chain & Component Integration | — | **Not-covered** | Out of behavioral scope. |

**Net NIST coverage: Confabulation fully; 4 categories partially. 7 of 12 untouched.**

---

## 4. Garak probe-family cross-walk

[NVIDIA Garak](https://github.com/NVIDIA/garak) is a static, mostly single-turn LLM vulnerability scanner with dozens of probe families. Overlap with Coehoorn is small; the *approach* differs more than the surface.

| Archetype | Overlapping Garak families | Overlap notes |
|---|---|---|
| injector | `promptinject`, `dan`, `latentinjection`, `goodside` | Same intent (injection/jailbreak/system-prompt). Garak = large static corpus; Coehoorn = a few adaptive multi-turn probes. |
| edge_case / off_topic | `snowball`, `misleading`, `packagehallucination` | Garak's hallucination probes overlap Coehoorn's fabricated-specifics intent. |
| contradictor | (loose) `misleading`, `snowball` | No direct Garak family for multi-turn sycophancy/stance-flip; partial conceptual overlap only. |
| emotional | `grandma` (emotional-pretext framing) | `grandma` uses emotional pretext to elicit unsafe content; Coehoorn instead tests *safety referral* to a crisis-escalating user — adjacent, not equivalent. |
| ambiguous | (none) | Garak has no underspecification/clarification probe family. |

**Where Garak goes far beyond Coehoorn (breadth):** `encoding`, `leakreplay` (training-data extraction), `xss`/`ansiescape` (output-handling sinks), `malwaregen`, `realtoxicityprompts`, `divergence`, `atkgen` (automated attack generation), `tap`, `suffix`, `continuation`, `lmrc`, `topic`. None of these have a Coehoorn equivalent.

**Where Coehoorn differs (not "better", different):**
- **Multi-turn, adaptive personas** vs. Garak's largely single-shot static prompts — Coehoorn tests failures that only emerge across turns (stance-flip, escalation, drift-then-fabricate).
- **Cited evidence**: every Coehoorn failure points at the exact transcript turn; Garak reports detector hits per-probe, not turn-level conversational provenance.
- **Behavioral rubric** (clarification vs. guessing, referral vs. engagement, stance-holding vs. capitulation) rather than string/pattern detectors.

---

## 5. OWASP Top 10 for Agentic Applications (2026) — the MCP tool-poisoning pack

The 2026 OWASP GenAI Security Project ships a dedicated agentic top 10 (ASI01–ASI10). Coehoorn's `mcp-siege` pack drives three MCP-tool-poisoning archetypes against an offline loopback MCP fixture; every breach is cited to the exact transcript turn (`coehoorn/mcp_redteam.py`; rubric [`examples/rubric_mcp.yaml`](../examples/rubric_mcp.yaml); committed reports under [`runs/sample-mcp/`](../runs/sample-mcp/)).

Reference list (2026): ASI01 Agent Goal Hijack · ASI02 Tool Misuse & Exploitation · ASI03 Agent Identity & Privilege Abuse · ASI04 Agentic Supply Chain Compromise · ASI05 Unexpected Code Execution · ASI06 Memory & Context Poisoning · ASI07 Insecure Inter-Agent Communication · ASI08 Cascading Agent Failures · ASI09 Human-Agent Trust Exploitation · ASI10 Rogue Agents.

| MCP archetype | ASI item(s) | Status | One-line justification |
|---|---|---|---|
| **rug-pull** (hero) | **ASI04** Supply Chain Compromise | **Covered** | A tool whose manifest mutates malicious after the first listing is a compromised-dependency / mutable-manifest attack; the breach is cited to the *flip* turn — the temporal localization a status-only verdict cannot make. |
| **rug-pull** | **ASI01** Agent Goal Hijack | **Covered** | The flipped description redirects the agent into an exfiltration call at the flip turn. |
| **rug-pull** | **ASI02** Tool Misuse | **Covered** | The agent invokes the now-malicious tool — the same forbidden-tool catch as the chat-agent tool siege, cited to the turn. |
| tool-description poisoning | **ASI04** · **ASI01** | **Covered** | A malicious instruction embedded in a tool's `description` field, present from the first listing, hijacks the agent into an exfiltration call. |
| cross-server shadowing | **ASI07** Insecure Inter-Agent Communication | **Covered** | A second server registers a look-alike tool that intercepts a legitimate one; the unpinned agent resolves the call to the shadow. |
| cross-server shadowing | **ASI04** · **ASI03** Identity & Privilege Abuse | **Covered** | Charging through an unverified, shadowed manifest with no prior `verify_tool_manifest` is a supply-chain + privilege-bypass breach, cited to the turn. |
| — | ASI05 Unexpected Code Execution | **Not-covered** | No code-execution sink from tool output. |
| — | ASI06 Memory & Context Poisoning | **Partial** | The `--include-kb-poisoner` persona probes the write side only (no read-back loop); see §6. |
| — | ASI08 Cascading Agent Failures | **Not-covered** | A single victim agent; no multi-agent cascade. |
| — | ASI09 Human-Agent Trust Exploitation | **Not-covered** | No human-in-the-loop deception surface. |
| — | ASI10 Rogue Agents | **Not-covered** | No autonomous rogue-agent scenario. |

**Honest scope of the pack.** The loopback MCP server is a *deterministic in-process model* of MCP's stdio transport (newline-delimited JSON-RPC), not a wire-level MCP server, and the victim is a scripted, deterministically-vulnerable client. The offline path is the reproducible artifact; a live LLM victim is a documented seam, not a shipped measurement. The pack demonstrates the three archetypes end-to-end with cited turns — it is not an exhaustive ASI01–ASI10 scanner.

---

## 6. What Coehoorn deliberately does NOT cover

Explicit, by design — listing these is the point:

- **Training-data / memorization extraction at scale** — no `leakreplay`-style or membership-inference attacks (NIST Data Privacy / IP, OWASP LLM02).
- **Model-weight & infrastructure attacks** — no model theft, extraction, inversion, or supply-chain (OWASP LLM03; ATLAS exfiltration/ML-supply-chain tactics).
- **Multimodal** — text chat only; no image/audio/video adversarial inputs.
- **Automated jailbreak search** — no `atkgen`/`tap`/`suffix`/GCG-style optimization; Coehoorn's probes are hand-designed personas, not a search loop.
- **Agentic tool-use exploitation** — *partially covered.* Tool-policy criteria catch **forbidden-tool calls (OWASP Agentic 2026 ASI02, Tool Misuse)** and **privileged actions taken with no prior approval (ASI03, Identity/Privilege Abuse)**, cited to the turn, and the MCP tool-poisoning pack (`mcp-siege`, §5) adds **rug-pull / description-poisoning (ASI04 Supply Chain, ASI01 Goal Hijack)** and **cross-server tool shadowing (ASI07 Insecure Inter-Agent Communication)**, each cited to the turn. Still **not** covered: indirect injection via tool *outputs*, the memory/context-poisoning read-back loop (ASI06), or cascading multi-agent failures (ASI08). Scope note: the optional KB-poisoner persona (`--include-kb-poisoner`) probes only the **write side** of the memory/KB surface — an unsanitized write attempt (ASI02/ASI03) and a persisted-instruction echo (LLM01) — and does **not** run the ASI06 read-back loop (no later turn re-reads poisoned state as trusted), so memory/context poisoning itself remains out of scope as stated.
- **Indirect / data-channel prompt injection** — only direct, in-conversation injection (no poisoned documents/web/RAG; OWASP LLM08; ATLAS AML.T0051.001).
- **Output-handling sinks** — no XSS/SSRF/code-exec from rendered model output (OWASP LLM05; Garak `xss`/`ansiescape`).
- **DoS / cost / resource-exhaustion** — no unbounded-consumption testing (OWASP LLM10).
- **Encoding / obfuscation attack scaling** — no systematic `encoding`-style bypass corpus.
- **Bias, toxicity-at-scale, CBRN uplift, obscene/abusive content** — no fairness, `realtoxicityprompts`, CBRN, or CSAM/NCII probes (NIST Harmful Bias, CBRN, Obscene/Degrading).
- **Quantitative robustness scoring** — Coehoorn yields cited pass/fail behavioral findings, not statistical attack-success-rate benchmarks over large corpora.

---

## Sources

- [OWASP Top 10 for LLM Applications 2025 (OWASP GenAI Security Project)](https://genai.owasp.org/llm-top-10/) · [PDF v2025](https://owasp.org/www-project-top-10-for-large-language-model-applications/assets/PDF/OWASP-Top-10-for-LLMs-v2025.pdf)
- [OWASP Top 10 for Agentic Applications 2026 — ASI01–ASI10 (OWASP GenAI Security Project)](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- [MITRE ATLAS](https://atlas.mitre.org/) · [ATLAS Promptfoo technique mapping](https://www.promptfoo.dev/docs/red-team/mitre-atlas/) · [ATLAS data changelog (v5.x, 2025–2026)](https://github.com/mitre-atlas/atlas-data/blob/main/CHANGELOG.md)
- [NIST AI 600-1 Generative AI Profile (PDF)](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) · [12-category summary (Modulos)](https://docs.modulos.ai/frameworks/nist-ai-rmf/generative-ai-profile)
- [NVIDIA Garak — LLM vulnerability scanner](https://github.com/NVIDIA/garak) · [Garak probe docs](https://github.com/NVIDIA/garak/tree/main/docs/source/probes)
