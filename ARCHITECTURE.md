# Why the pipeline looks like this

A first sketch of an agentic debugger is a straight line: collect context, ask a model for the root cause, ask a model for the fix, run Basil, open a pull request. Jaeger and feature flags are arrows into two of those boxes.

That sketch names the right stages. It is a hard system to trust or to extend. This repo is the revised shape. The code for each row is the file in the last column.

| Straight line | What goes wrong | What this repo does | File |
| --- | --- | --- | --- |
| Jaeger and flags are wired into nodes | Every new tool is a special case inside the prompt | Nodes ask for a capability. Products are connectors. | `connectors.py` |
| The model reads raw logs | Secrets leak, and the model cites a span that was never there | Redact first. Specialists emit fact ids. The model may only cite those ids. | `collect.py`, `classify.py` |
| Diagnosis always becomes a patch | A sev-1, or an empty trace window, still produces a diff | Policy chooses `needs_data`, `observe_only`, `propose`, or `auto_fix`. | `policy.py` |
| "Other sub-agents" | No contract for adding one | A specialist returns hypotheses. The graph waits for all of them. | `specialists.py`, `graph.py` |
| One model call owns root cause | Breadcrumbs and the rollout that caused them get flattened | Breadcrumb, crash, change, and dependency stay separate claims. Classify picks. | `classify.py` |
| One fix attempt | The first idea is often "turn the flag off", which may not fix the code | Basil can fail. The critique goes back to the planner once. | `plan.py`, `validate.py` |
| Finalize means "open a PR" | Some runs should stop at an explanation | Finalize has several endings. A draft review is the one you get when tests passed and policy says propose. | `finalize.py` |

The sample incident is there so the arrows are not abstract. You can follow one flag rollout from `examples/checkout_async_capture.json` through every file in the table.
