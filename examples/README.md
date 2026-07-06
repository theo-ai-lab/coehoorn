# Examples

Self-contained inputs for the quickstart and for measuring the harness against a known target.

| file | what it is |
|---|---|
| `rubric_coach.yaml` | A two-criterion rubric (safe handling of self-harm language; no fabricated legal citations). Each criterion has a `heuristic:` block so the offline judge can decide it without an LLM call. |
| `rubric_tools.yaml` | The tool-policy rubric driving the tool-use siege: `forbidden_tools` (a destructive tool that must never be called — OWASP Agentic ASI02) and `tool_must_precede` (a privileged action requiring prior approval — ASI03). Powers `runs/sample-tools/`. |
| `rubric_mcp.yaml` | The rubric judging the MCP tool-poisoning attack pack: `no_data_exfiltration_tool` (forbidden exfil tools a poisoned description lures the agent into — ASI02/ASI04) and `privileged_tool_requires_manifest_check` (a charge with no prior manifest verification — ASI04/ASI03). Powers `runs/sample-mcp/`. |
| `expected_failures.yaml` | Per-persona ground-truth: which persona is expected to fail which criterion when this rubric is run against the local stub agent. Consumed by `coehoorn compare`. |
| `plimsoll_policy_tools.json` | The same tool-policy contract as `rubric_tools.yaml`, expressed as a [Plimsoll](https://github.com/theo-ai-lab/plimsoll) policy (same org — dogfooding): `forbidden_tools` mirrors the destructive-tool list, `must_precede` mirrors the approval-before-refund rule. Gates the traces exported by `scripts/export_plimsoll_traces.py` in `.github/workflows/trace-gate.yml`. |

## Running the example

Start the stub agent in one terminal:

```
cd apps/stub-agent && uv run python app.py
```

In another terminal, from the repo root:

```
uv run coehoorn run \
  --rubric examples/rubric_coach.yaml \
  --agent http://127.0.0.1:8001/chat \
  --personas 6 --turns 4 --out runs

uv run coehoorn compare \
  --report runs/<run_id>.json \
  --expected examples/expected_failures.yaml
```

The `run` command writes `runs/<run_id>.json` (machine-readable) and `runs/<run_id>.html` (a self-contained report you can open with a browser).

## The MCP tool-poisoning attack pack

`rubric_mcp.yaml` judges the offline MCP tool-poisoning pack — no external agent,
no key. It runs against a deterministic in-process loopback MCP fixture, so the
whole pack is keyless and byte-reproducible:

```
uv run coehoorn mcp-siege                    # all three archetypes, hero first
open runs/sample-mcp/rug-pull/report.html    # the committed hero survey
```

Three archetypes: **rug-pull** (a benign tool whose description mutates malicious
mid-session — the flip cited to its exact turn), **tool-description poisoning**,
and **cross-server shadowing**. See the pack section in the top-level
[`README.md`](../README.md) and the ASI mapping in
[`docs/coverage-map.md`](../docs/coverage-map.md) §5.

## Pointing at a real external agent

`--agent` accepts any HTTP endpoint speaking the `{conversation} -> {reply}`
contract, so the same command sieges a real agent — not just the local stub.
The endpoint and its auth resolve from the environment (via `coehoorn/config.py`)
so secrets stay off the command line:

```
export AGENT_ENDPOINT="https://your-agent.example.com/chat"
export AGENT_API_KEY="<token>"          # -> Authorization: Bearer <token>
# or: export AGENT_AUTH_HEADER="x-api-key: <token>"   # any raw header line

uv run coehoorn run --rubric examples/rubric_coach.yaml \
  --personas 6 --turns 4 --out runs/external --emit sarif,junit
```

`.github/workflows/external-siege.yml` runs exactly this in CI against a
configured `AGENT_ENDPOINT` (secret/variable) and uploads SARIF + posts cited
breaches on the PR. The full engagement scaffold is
[`docs/ENGAGEMENT_TEMPLATE.md`](../docs/ENGAGEMENT_TEMPLATE.md).
