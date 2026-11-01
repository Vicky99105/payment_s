"""DefaultTaskQueue against the SDK's local queue devserver (`python -m vercel.queue.devserver`)."""

import json
import socket
import subprocess
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from vercel.queue import QueueClient

from backend.domain.errors import EnqueueError
from backend.integrations.queue.vercel_queue import DefaultTaskQueue

CONSUMER_GROUP = "itest-consumer"


@pytest.fixture(scope="module")
def devserver_url() -> Iterator[str]:
    proc = subprocess.Popen(
        [sys.executable, "-m", "vercel.queue.devserver", "--port", "0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        if not line:
            _, err = proc.communicate(timeout=5)
            pytest.fail(f"queue devserver did not start: {err}")
        yield str(json.loads(line)["baseUrl"])
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _point_sdk_at(monkeypatch: pytest.MonkeyPatch, base_url: str) -> None:
    monkeypatch.setenv("VERCEL_QUEUE_BASE_URL", base_url)
    monkeypatch.setenv("VERCEL_REGION", "iad1")
    # The `vercel dev` token: accepted by the devserver and disables deployment-id pinning.
    monkeypatch.setenv("VERCEL_QUEUE_TOKEN", "vc-dev-token")


@pytest.fixture
def topic(monkeypatch: pytest.MonkeyPatch, devserver_url: str) -> str:
    _point_sdk_at(monkeypatch, devserver_url)
    return f"itest-{uuid.uuid4().hex[:12]}"


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _receive_all(topic: str) -> list[Any]:
    payloads: list[Any] = []
    async for delivery in QueueClient().poll(topic, CONSUMER_GROUP, limit=10):
        payloads.append(delivery.accept().payload)
    return payloads


async def test_enqueue_publishes_transaction_id_payload(topic: str) -> None:
    await DefaultTaskQueue(topic).enqueue("txn_one")
    assert await _receive_all(topic) == [{"transaction_id": "txn_one"}]


async def test_duplicate_enqueue_delivers_once(topic: str) -> None:
    queue = DefaultTaskQueue(topic)
    await queue.enqueue("txn_dup")
    await queue.enqueue("txn_dup")
    assert await _receive_all(topic) == [{"transaction_id": "txn_dup"}]


async def test_warm_publishes_nothing_and_enqueue_still_works(topic: str) -> None:
    queue = DefaultTaskQueue(topic)
    await queue.warm()
    assert await _receive_all(topic) == []
    await queue.enqueue("txn_warm")
    assert await _receive_all(topic) == [{"transaction_id": "txn_warm"}]


async def test_unreachable_queue_raises_enqueue_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _point_sdk_at(monkeypatch, f"http://127.0.0.1:{_closed_port()}")
    with pytest.raises(EnqueueError):
        await DefaultTaskQueue("itest-unreachable").enqueue("txn_x")


async def test_warm_never_raises_when_queue_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _point_sdk_at(monkeypatch, f"http://127.0.0.1:{_closed_port()}")
    await DefaultTaskQueue("itest-unreachable").warm()


async def test_missing_region_raises_enqueue_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERCEL_REGION", raising=False)
    with pytest.raises(EnqueueError):
        await DefaultTaskQueue("itest-noregion").enqueue("txn_x")
