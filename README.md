# debug-agent

A runnable reference for an agentic debugging system. It takes an incident, collects evidence through pluggable connectors, runs parallel root-cause specialists, and only then asks a model to classify and propose a fix. A Basil-shaped test run validates the fix in a scratch workspace. The run ends as a report, a draft pull request, or an escalation.

[ARCHITECTURE.md](ARCHITECTURE.md) is the design note: what the original pipeline was missing, and the contracts this code actually implements. Read that first if you are here to learn the shape. This file is how to run and extend it.

The graph is built with [LangGraph](https://langchain-ai.github.io/langgraph/). The default model is scripted, so the checkout scenario is reproducible without an API key.

## Run the checkout incident

The fixture is a payment capture timeout. Twelve minutes after `checkout.async_capture` ramps to 100, ledger captures start failing because the async path forwards an empty idempotency key. A deploy of checkout 1.42.0 landed in the lookback window and introduced that path.

```bash
pip install -e ".[dev]"
python -m debug_agent run scenarios/checkout_async_capture
python -m debug_agent graph
```

The run writes `runs/checkout_async_capture/`:

| File | What it is |
| --- | --- |
| `report.md` | Coverage, specialist findings, diagnosis, both attempts, audit trail |
| `pull_request.md` | Review body, including rollback |
| `diff.patch` | Unified diff of the durable fix |
| `model_transcript.json` | Every prompt and response |
| `state.json` | Redacted evidence and decisions |
| `workspace/` | Scratch tree Basil tested. The scenario sources are untouched |

What the two attempts teach:

1. The planner ramps the flag back to 0. That is the right operational mitigation, and it does not make the unit test pass, because the test holds the flag on and demands a key.
2. Basil's critique goes back to the planner. The second plan mints a key on the async path. Basil passes. Policy is `propose` because this is production payments, so the outcome is a draft pull request rather than an apply.

## Layout

```
debug_agent/
  connectors/    registry, fixtures, and vendor adapters
  specialists/   breadcrumb, crash, change, dependency
  runners/       Basil result contract and pytest/tmt engines
  policy.py      autonomy and approval, in code
  prompts.py     the only two judgment prompts, plus crash narration
  models.py      scripted model and OpenAI-compatible client
  graph.py       LangGraph topology
  service.py     run_debug entry point
scenarios/checkout_async_capture/
tests/           graph, policy, connectors, redaction
```

## Use a live model

```bash
export DEBUG_AGENT_MODEL=openai
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://api.openai.com/v1   # optional
export OPENAI_MODEL=gpt-4o-mini                     # optional
python -m debug_agent run scenarios/checkout_async_capture
```

The live model has to return the JSON schemas in `debug_agent/prompts.py`. Classification is rejected when the hypothesis id or a cited fact id was not produced by a specialist. A bad edit fails Basil and comes back as a critique until the attempt budget is spent.

## Register a real backend

Fixtures are the default for every capability. Set any of these to add a vendor connector beside them:

| Variable | Capability | Adapter |
| --- | --- | --- |
| `JAEGER_URL` | traces | `GET /api/traces` |
| `LOKI_URL` | logs | Loki query_range |
| `PROMETHEUS_URL` | metrics | PromQL query_range |
| `PAGERDUTY_URL` + `PAGERDUTY_TOKEN` | incidents | incidents list |
| `LAUNCHDARKLY_URL` + `LAUNCHDARKLY_TOKEN` | feature flags | audit log subset |
| `UNLEASH_URL` + `UNLEASH_TOKEN` | feature flags | admin events |
| `GITHUB_DEPLOYMENTS_URL` + `GITHUB_TOKEN` | deploys | deployment objects |

Each adapter normalizes into the schema in [ARCHITECTURE.md](ARCHITECTURE.md). Specialists never branch on the vendor name. The parsers are unit-tested with sample payloads, so you can see the subset they accept before pointing them at a cluster.

To add a system that is not in that table, implement `collect(self, query)` and `registry.register(...)`. Unknown capabilities are rejected. A connector that raises is recorded on the coverage report and the rest of the fan-out continues.

## Point validation at BASIL

The validation node speaks `basil-result.v1` and records the tmt context BASIL uses (`basil_test_repo_url`, `basil_test_repo_ref`, `basil_test_relative_path`). The checkout scenario includes `tests/main.fmf` for that reason.

The default engine is pytest, isolated from this repo's own pytest config. If you have [tmt](https://tmt.readthedocs.io/) installed:

```bash
export DEBUG_AGENT_BASIL_ENGINE=tmt
```

A real BASIL deployment should consume the same result object. This prototype does not guess a private REST path.

## Tests

```bash
pytest
```

The graph test runs the checkout scenario end to end: flag ramp fails Basil, the code edit passes, secrets from the log fixture are absent from the report, and a sev-1 copy of the same incident stops after diagnosis.

## What this will not do

- It will not edit `scenarios/` in place. Plans apply to a copy under the run directory.
- It will not open a GitHub pull request. `draft_pr` means the diff and the review body are ready for a publisher you control.
- It will not roll back a deploy. A `rollback` action is stored and reported. There is no deploy-write connector.
- It will not treat a model narrative as evidence. Cited ids have to exist.
