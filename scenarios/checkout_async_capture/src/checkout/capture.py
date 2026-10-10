"""Charge capture for the checkout service.

Sync captures mint an idempotency key when the caller did not supply one.
The async path is selected with the flag ``checkout.async_capture``.
"""

from __future__ import annotations

import hashlib


class LedgerTimeout(TimeoutError):
    """The ledger call did not accept the capture."""


class Ledger:
    def capture(self, order_id: str, idempotency_key: str | None, amount_cents: int) -> dict:
        if not idempotency_key:
            raise LedgerTimeout(
                f"ledger.capture timed out for {order_id}: idempotency_key is missing"
            )
        return {
            "order_id": order_id,
            "idempotency_key": idempotency_key,
            "amount_cents": amount_cents,
            "status": "captured",
        }


def mint_idempotency_key(order_id: str) -> str:
    digest = hashlib.sha256(f"checkout:{order_id}".encode()).hexdigest()
    return digest[:24]


def capture_payment(order: dict, *, async_capture: bool, ledger: Ledger | None = None) -> dict:
    client = ledger or Ledger()
    order_id = str(order["id"])
    amount = int(order["amount_cents"])
    if async_capture:
        # The async path forwards the order key as-is. Callers that did not
        # mint one hit the ledger with an empty key and the call times out.
        key = order.get("idempotency_key")
    else:
        key = order.get("idempotency_key") or mint_idempotency_key(order_id)
    return client.capture(order_id, key, amount)
