import asyncio
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock

from redis.exceptions import ConnectionError as RedisConnectionError

from research_api.events import wakeups
from research_api.events.wakeups import EventWakeups


def test_hints_are_tenant_and_run_scoped_and_watchers_cleanup():
    hub = EventWakeups()
    tenant, run = uuid.uuid4(), uuid.uuid4()
    with hub.watch(tenant, run) as first, hub.watch(tenant, run) as second:
        hub.committed(uuid.uuid4(), run)
        hub.committed(tenant, uuid.uuid4())
        assert not first.is_set() and not second.is_set()
        hub.committed(tenant, run)
        assert first.is_set() and second.is_set()
    assert hub._watchers == {}


def test_queue_is_bounded_and_duplicate_queued_hints_are_coalesced():
    hub = EventWakeups()
    hub._outgoing = asyncio.Queue(maxsize=1)
    tenant, run = uuid.uuid4(), uuid.uuid4()
    with hub.watch(tenant, run) as signal:
        for _ in range(100):
            hub.committed(tenant, run)
        assert hub._outgoing.qsize() == 1
        assert len(hub._pending) == 1
        signal.clear()
        hub.committed(tenant, uuid.uuid4())  # Full queue: drop hint, never fail the write.
        hub.committed(tenant, run)
        assert signal.is_set()
        assert hub._outgoing.qsize() == 1
        assert len(hub._pending) == 1


async def test_redis_outage_never_blocks_local_commit_hints_and_closes_tasks(monkeypatch, caplog):
    client = MagicMock()
    client.publish = AsyncMock(side_effect=RedisConnectionError("secret URL"))
    client.aclose = AsyncMock()
    subscriber = MagicMock()
    subscriber.subscribe = AsyncMock(side_effect=RedisConnectionError("secret URL"))
    subscriber.__aenter__ = AsyncMock(return_value=subscriber)
    subscriber.__aexit__ = AsyncMock(return_value=False)
    client.pubsub.return_value = subscriber
    monkeypatch.setattr(wakeups.Redis, "from_url", lambda *_, **__: client)
    hub = EventWakeups()
    tenant, run = uuid.uuid4(), uuid.uuid4()
    with caplog.at_level(logging.WARNING, logger="research_api.events"):
        async with hub.transport("redis://fixture"):
            with hub.watch(tenant, run) as signal:
                hub.committed(tenant, run)
                assert signal.is_set()
                await asyncio.wait_for(hub._outgoing.join(), timeout=0.5)
    client.aclose.assert_awaited_once()
    assert hub._outgoing is None and hub._watchers == {}
    assert "secret" not in caplog.text
    assert len(caplog.records) == 1


async def test_new_commit_while_publish_in_flight_keeps_a_trailing_hint():
    hub = EventWakeups()
    outgoing = asyncio.Queue(maxsize=1)
    hub._outgoing = outgoing
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def publish(channel, payload):
        calls.append((channel, payload))
        if len(calls) == 1:
            entered.set()
            await release.wait()

    client = MagicMock()
    client.publish = publish
    tenant, run = uuid.uuid4(), uuid.uuid4()
    task = asyncio.create_task(hub._publish(client, outgoing))
    try:
        hub.committed(tenant, run)
        await asyncio.wait_for(entered.wait(), timeout=0.5)
        hub.committed(tenant, run)
        hub.committed(tenant, run)
        assert outgoing.qsize() == 1
        release.set()
        await asyncio.wait_for(outgoing.join(), timeout=0.5)
        assert len(calls) == 2
        assert hub._pending == set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_malformed_binary_hint_does_not_kill_listener():
    hub = EventWakeups()
    tenant, run = uuid.uuid4(), uuid.uuid4()
    messages = asyncio.Queue()
    for message in [
        {"type": "subscribe"},
        {"type": "message", "data": b"\xff" * 73},
        {"type": "message", "data": b"x" * 73},
        {"type": "message", "data": f"{tenant}:{run}".encode()},
    ]:
        messages.put_nowait(message)
    subscriber = MagicMock()
    subscriber.subscribe = AsyncMock()

    async def receive(**_):
        return await messages.get()

    subscriber.get_message = AsyncMock(side_effect=receive)
    subscriber.__aenter__ = AsyncMock(return_value=subscriber)
    subscriber.__aexit__ = AsyncMock(return_value=False)
    client = MagicMock()
    client.pubsub.return_value = subscriber
    with hub.watch(tenant, run) as signal:
        task = asyncio.create_task(hub._listen(client))
        try:
            await asyncio.wait_for(signal.wait(), timeout=0.5)
            assert hub.connected.is_set()
            assert not task.done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_failed_publish_cools_down_without_blocking_local_hints(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(wakeups, "monotonic", lambda: now[0])
    hub = EventWakeups()
    outgoing = asyncio.Queue(maxsize=8)
    hub._outgoing = outgoing
    client = MagicMock()
    client.publish = AsyncMock(side_effect=RedisConnectionError("private address"))
    task = asyncio.create_task(hub._publish(client, outgoing))
    try:
        tenant, run = uuid.uuid4(), uuid.uuid4()
        hub.committed(tenant, run)
        await asyncio.wait_for(outgoing.join(), timeout=0.5)
        with hub.watch(tenant, run) as signal:
            for _ in range(5):
                hub.committed(tenant, run)
                await asyncio.wait_for(outgoing.join(), timeout=0.5)
            assert signal.is_set()
        assert client.publish.await_count == 1
        assert not hub._pending
        now[0] += 31
        client.publish.side_effect = None
        hub.committed(tenant, run)
        await asyncio.wait_for(outgoing.join(), timeout=0.5)
        assert client.publish.await_count == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
