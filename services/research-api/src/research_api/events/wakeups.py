"""Best-effort commit hints. PostgreSQL remains the only event log/replay source."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from time import monotonic

from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

Key = tuple[uuid.UUID, uuid.UUID]
CHANNEL = "research:event-wakeups:v1"
logger = logging.getLogger("research_api.events")


class EventWakeups:
    def __init__(self) -> None:
        self._watchers: dict[Key, set[asyncio.Event]] = {}
        self._outgoing: asyncio.Queue[Key] | None = None
        self._pending: set[Key] = set()
        self.connected = asyncio.Event()
        self._warned = False
        self._publish_retry_at = 0.0

    @contextmanager
    def watch(self, tenant: uuid.UUID, run: uuid.UUID) -> Iterator[asyncio.Event]:
        key = (tenant, run)
        signal = asyncio.Event()
        self._watchers.setdefault(key, set()).add(signal)
        try:
            yield signal
        finally:
            self._watchers[key].discard(signal)
            if not self._watchers[key]:
                del self._watchers[key]

    def _wake(self, key: Key) -> None:
        for signal in self._watchers.get(key, ()):
            signal.set()

    def committed(self, tenant: uuid.UUID, run: uuid.UUID) -> None:
        """Called only after commit; no network I/O or task allocation on writes."""
        key = (tenant, run)
        self._wake(key)
        if self._outgoing is not None and key not in self._pending:
            try:
                self._outgoing.put_nowait(key)
            except asyncio.QueueFull:
                # Dropping a hint is safe: SSE still polls/replays PostgreSQL.
                return
            self._pending.add(key)

    def _unavailable(self) -> None:
        if not self._warned:
            logger.warning("event_wakeups.redis_unavailable: PostgreSQL polling remains active")
            self._warned = True

    async def _publish(self, client: Redis, outgoing: asyncio.Queue[Key]) -> None:
        while True:
            tenant, run = key = await outgoing.get()
            # A commit while this publish is in flight may need a new hint: a
            # remote reader might already have consumed the previous hint.
            self._pending.discard(key)
            try:
                if monotonic() < self._publish_retry_at:
                    continue
                await client.publish(CHANNEL, f"{tenant}:{run}")
            except (RedisError, OSError, TimeoutError):
                self._publish_retry_at = monotonic() + 30
                self._unavailable()
            finally:
                outgoing.task_done()

    async def _listen(self, client: Redis) -> None:
        delay = 1
        while True:
            try:
                async with client.pubsub() as subscriber:
                    await subscriber.subscribe(CHANNEL)
                    while True:
                        message = await subscriber.get_message(timeout=1)
                        if message is None:
                            continue
                        if message["type"] == "subscribe":
                            self.connected.set()
                            self._warned = False
                            delay = 1
                        elif message["type"] == "message":
                            value = message.get("data")
                            if not isinstance(value, bytes) or len(value) != 73:
                                continue
                            try:
                                tenant, run = value.decode("ascii").split(":")
                                self._wake((uuid.UUID(tenant), uuid.UUID(run)))
                            except (UnicodeError, ValueError):
                                continue
            except (RedisError, OSError, TimeoutError):
                self.connected.clear()
                self._unavailable()
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)

    @asynccontextmanager
    async def transport(self, url: str | None) -> AsyncIterator[None]:
        if url is None:
            yield
            return
        if self._outgoing is not None:
            raise RuntimeError("event wakeup transport already running")
        outgoing: asyncio.Queue[Key] = asyncio.Queue(maxsize=1024)
        client = Redis.from_url(
            url,
            decode_responses=False,
            max_connections=2,
            socket_connect_timeout=0.5,
            socket_timeout=2,
            retry=Retry(NoBackoff(), 0),
        )
        self._outgoing = outgoing
        tasks = [
            asyncio.create_task(self._publish(client, outgoing)),
            asyncio.create_task(self._listen(client)),
        ]
        try:
            yield
        finally:
            self._outgoing = None
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await client.aclose()
            self.connected.clear()
            self._pending.clear()
            self._warned = False
            self._publish_retry_at = 0.0


event_wakeups = EventWakeups()
