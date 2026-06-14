# Security and local-only design

Coehoorn is designed for local use only. This document records the design constraints that make that claim verifiable rather than aspirational.

## Network surface

Two — and only two — outbound destinations the harness ever calls:

1. **The target agent endpoint** you pass via `--agent <url>`. By default the quickstart points it at `http://127.0.0.1:8001/chat` (the local stub).
2. **`api.anthropic.com`** — only if you explicitly opt into LLM mode by setting `ANTHROPIC_API_KEY` in the environment. The default `--mode auto` falls back to fully-offline heuristic mode if no key is set.

No telemetry, no analytics, no crash reporting, no external callbacks. The HTML report viewer (`report_html.py`) inlines all CSS and emits no `<script>` tags; you can open `runs/<id>.html` with the network disconnected.

The optional extras stay inside this boundary. `coehoorn[mcp]` speaks MCP over
**stdio** (no listening socket, no new outbound destination); `coehoorn[inspect]`
writes an Inspect AI `EvalLog` to a **local file**. Neither is imported on the
core path — a clean-interpreter test asserts that `import coehoorn` pulls in
neither `mcp` nor `inspect_ai`.

## The stub agent

`apps/stub-agent/app.py` is a test fixture with deliberate flaws — it intentionally fails to recognise self-harm-related messages, and ~30% of the time fabricates a legal citation when asked legal questions. These are required for the harness to have a real failure to detect.

Design constraints on the stub:

- **Binds to `127.0.0.1` only**, never `0.0.0.0`. The Flask `app.run()` call hard-codes the loopback interface.
- **Prints a non-production warning** on startup: `WARNING: coehoorn stub has intentional flaws. Do NOT deploy as a real chat interface.`
- **Header comment** clearly labels it as a test fixture, not for production use.
- **No persistent state** — every request is judged from the message body alone.

If you change the stub to bind a non-loopback interface, you are deploying a chat agent that produces unsafe replies on the open network. Don't.

## Secrets handling

- `ANTHROPIC_API_KEY` is read from the process environment, loaded via `python-dotenv` from `.env` if present. The `.env` file is gitignored.
- The key is passed only to the official `anthropic` SDK; nothing in this codebase logs, prints, or persists it.
- Run artifacts (`runs/<id>.json`, `runs/<id>.html`) contain prompts, replies, persona descriptions, and rubric text. They do NOT contain the API key or any environment values. Treat them as "everything the LLM saw," not "everything the process knew."

## Run artifacts

- `runs/` directory contents are gitignored except for `runs/sample/` (the deterministic demo report).
- Each `<id>.json` is a serialized `Report` — full conversation transcripts, persona definitions, per-criterion verdicts, cited turn indices. Treat them as containing whatever you sent into the rubric and whatever the agent replied with.
- The HTML viewer is a self-contained artifact (one file, no assets). It can be emailed, attached, or printed without leaking dependencies.

## Reporting a vulnerability

If you find a security issue in the harness itself (escape paths, code-execution
from rubric input, leak of secrets to artifacts), report it privately to the
maintainer rather than in a public tracker.

## What this repo is NOT

- Not a production chat-agent runtime. The stub is a fixture, not a server.
- Not authenticated. There is no login, no user model, no session.
- Not multi-tenant. Designed for a single operator on a single machine.
- Not hardened against malicious rubric input. If you feed it a YAML file from an untrusted source, you're trusting that source.
