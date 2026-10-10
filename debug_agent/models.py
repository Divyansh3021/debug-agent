"""Model boundary.

``ScriptedModel`` is the default. It returns schema-valid JSON so the graph,
the validation loop, and the tests run without an API key. ``OpenAICompatibleModel``
speaks the same ``complete`` method, so swapping brains does not change the graph.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from typing import Protocol

# The first mitigation attempt is a reversible flag ramp. The second is the
# durable edit. The old text is the buggy branch in the checkout scenario;
# tests assert it still matches that file.
ASYNC_BRANCH_OLD = """\
    if async_capture:
        # The async path forwards the order key as-is. Callers that did not
        # mint one hit the ledger with an empty key and the call times out.
        key = order.get("idempotency_key")
    else:
        key = order.get("idempotency_key") or mint_idempotency_key(order_id)
    return client.capture(order_id, key, amount)
"""

ASYNC_BRANCH_NEW = """\
    # The flag changes when capture is sent, not whether it is idempotent.
    key = order.get("idempotency_key") or mint_idempotency_key(order_id)
    return client.capture(order_id, key, amount)
"""

_PREFERRED_HYPOTHESIS = "change:flag-checkout.async_capture"


class Model(Protocol):
    def complete(self, *, system: str, user: str) -> str:
        """Return the model's raw text for one system/user pair."""


class ScriptedModel:
    """Offline stand-in that follows the same JSON contracts as a live model.

    On the first mitigation attempt it chooses the reversible flag ramp. After
    a critique is present (attempt >= 1) it proposes the code edit. A live model
    receives the critique in the same prompt and is expected to make that shift
    itself; this class replays it so the tutorial is reproducible.
    """

    def complete(self, *, system: str, user: str) -> str:
        del system
        task = _task(user)
        if task == "classify":
            return _classify(user)
        if task.startswith("narrate-"):
            return _narrate(user)
        if task == "mitigate":
            return _mitigate(user)
        raise ValueError(f"scripted model has no response for task {task!r}")


class OpenAICompatibleModel:
    """Chat-completions client for any OpenAI-compatible endpoint."""

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, *, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]


class RecordingModel:
    """Stores every prompt and response for the audit trail."""

    def __init__(self, inner: Model) -> None:
        self.inner = inner
        self.transcript: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def complete(self, *, system: str, user: str) -> str:
        response = self.inner.complete(system=system, user=user)
        with self._lock:
            self.transcript.append({"system": system, "user": user, "response": response})
        return response


def model_from_env() -> Model:
    choice = os.environ.get("DEBUG_AGENT_MODEL", "scripted").strip().lower()
    if choice == "scripted":
        return ScriptedModel()
    if choice in {"openai", "openai-compatible"}:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("DEBUG_AGENT_MODEL=openai requires OPENAI_API_KEY")
        return OpenAICompatibleModel(
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            api_key=api_key,
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        )
    raise RuntimeError(f"Unknown DEBUG_AGENT_MODEL {choice!r}. Use 'scripted' or 'openai'.")


def _task(user: str) -> str:
    for line in user.splitlines():
        if line.startswith("task:"):
            return line.split(":", 1)[1].strip()
    return ""


def _classify(user: str) -> str:
    ids = re.findall(r"^hypothesis_id: (\S+)", user, flags=re.MULTILINE)
    fact_ids = re.findall(r"^fact_id: (\S+)", user, flags=re.MULTILINE)
    if _PREFERRED_HYPOTHESIS in ids:
        chosen = _PREFERRED_HYPOTHESIS
    elif ids:
        chosen = ids[0]
    else:
        chosen = "NONE"
    return json.dumps(
        {
            "primary_id": chosen,
            "narrative": (
                "The async-capture flag moved to full rollout inside the incident "
                "window, and the failing path reaches the ledger without an idempotency key."
            ),
            "cited_fact_ids": fact_ids,
        }
    )


def _narrate(user: str) -> str:
    fact_ids = re.findall(r"^fact_id: (\S+)", user, flags=re.MULTILINE)
    if not fact_ids:
        return json.dumps({"narrative": "No facts to cite.", "cited_fact_ids": ["missing:none"]})
    return json.dumps(
        {
            "narrative": "Repeated timeouts report a missing idempotency key on capture.",
            "cited_fact_ids": fact_ids[:1],
        }
    )


def _mitigate(user: str) -> str:
    attempt = 0
    for line in user.splitlines():
        if line.startswith("attempt:"):
            attempt = int(line.split(":", 1)[1].strip())
            break
    if attempt == 0:
        return json.dumps(
            {
                "rationale": (
                    "Failing captures start when checkout.async_capture ramps to 100. "
                    "Ramping it back to 0 is reversible and stops new traffic taking the broken path."
                ),
                "risk": "low",
                "actions": [
                    {
                        "kind": "flag",
                        "summary": "Ramp checkout.async_capture from 100 to 0",
                        "payload": {"flag": "checkout.async_capture", "from": 100, "to": 0},
                    }
                ],
            }
        )
    return json.dumps(
        {
            "rationale": (
                "A flag ramp stops new traffic but leaves the async path itself broken. "
                "Mint the idempotency key on that path so the ledger contract holds with the flag on."
            ),
            "risk": "medium",
            "actions": [
                {
                    "kind": "edit",
                    "summary": "Mint an idempotency key on the async capture path",
                    "payload": {
                        "path": "src/checkout/capture.py",
                        "old": ASYNC_BRANCH_OLD,
                        "new": ASYNC_BRANCH_NEW,
                    },
                }
            ],
        }
    )
