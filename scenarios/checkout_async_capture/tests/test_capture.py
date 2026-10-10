"""Contract tests for capture. The async path currently fails the second test."""

from checkout.capture import capture_payment


def test_sync_mints_key_when_missing():
    result = capture_payment({"id": "o1", "amount_cents": 500}, async_capture=False)
    assert result["status"] == "captured"
    assert result["idempotency_key"]


def test_async_mints_key_when_missing():
    result = capture_payment({"id": "o2", "amount_cents": 500}, async_capture=True)
    assert result["status"] == "captured"
    assert result["idempotency_key"]


def test_async_keeps_caller_key():
    result = capture_payment(
        {"id": "o3", "amount_cents": 500, "idempotency_key": "caller-key"},
        async_capture=True,
    )
    assert result["idempotency_key"] == "caller-key"
