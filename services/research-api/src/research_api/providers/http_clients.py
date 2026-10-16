"""Lifespan-scoped HTTP transports for external research providers.

Clients own connection pools only. Credentials remain on each adapter's request
headers so concurrent workers cannot overwrite or leak one another's identity.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class ProviderHttpClients:
    tavily: httpx.AsyncClient
    serper: httpx.AsyncClient


_provider_clients: ContextVar[ProviderHttpClients | None] = ContextVar(
    "provider_http_clients", default=None
)


def get_provider_http_client(provider: str) -> httpx.AsyncClient | None:
    """Return this app lifespan's provider pool, or None outside app runtime."""
    clients = _provider_clients.get()
    if clients is None:
        return None
    if provider == "tavily":
        return clients.tavily
    if provider == "serper":
        return clients.serper
    raise ValueError(f"unsupported HTTP provider: {provider}")


@asynccontextmanager
async def provider_http_transport(
    *, timeout_seconds: float, worker_concurrency: int
) -> AsyncIterator[ProviderHttpClients]:
    """Create distinct bounded provider pools and close them at app shutdown."""
    max_connections = max(10, worker_concurrency * 6)
    limits = httpx.Limits(
        max_connections=max_connections,
        max_keepalive_connections=max(5, worker_concurrency * 3),
        keepalive_expiry=30.0,
    )
    timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds), pool=2.0)
    async with (
        httpx.AsyncClient(
            base_url="https://api.tavily.com",
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
        ) as tavily,
        httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
        ) as serper,
    ):
        clients = ProviderHttpClients(tavily=tavily, serper=serper)
        token: Token[ProviderHttpClients | None] = _provider_clients.set(clients)
        try:
            yield clients
        finally:
            _provider_clients.reset(token)
