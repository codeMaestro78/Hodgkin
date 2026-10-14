from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from research_api.db.runtime_security import validate_runtime_role

FLAGS = (
    "rolsuper",
    "rolbypassrls",
    "rolcreatedb",
    "rolcreaterole",
    "rolreplication",
    "memberships",
    "owns_objects",
    "can_create",
)


def engine(flags):
    result = SimpleNamespace(mappings=lambda: SimpleNamespace(one=lambda: flags))

    @asynccontextmanager
    async def connect():
        yield SimpleNamespace(execute=AsyncMock(return_value=result))

    return SimpleNamespace(connect=connect)


@pytest.mark.asyncio
async def test_restricted_runtime_role_is_accepted():
    await validate_runtime_role(engine(dict.fromkeys(FLAGS, False)))


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe", FLAGS)
async def test_privileged_runtime_role_is_rejected(unsafe):
    flags = dict.fromkeys(FLAGS, False)
    flags[unsafe] = True
    with pytest.raises(RuntimeError, match="Unsafe runtime database role"):
        await validate_runtime_role(engine(flags))
