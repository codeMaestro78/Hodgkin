"""One retry owner. Only known rejected/pre-dispatch calls may be retried."""

import asyncio
import random


def pre_dispatch_failure(error: BaseException) -> bool:
    current: BaseException | None = error
    for _ in range(8):
        if current is None:
            break
        # OpenAI 3 uses httpx2; Tavily uses httpx. Inspect causes, not messages.
        if type(current).__name__ in {"ConnectError", "ConnectTimeout", "PoolTimeout"} and (
            type(current).__module__.split(".")[0] in {"httpx", "httpx2", "httpcore"}
        ):
            return True
        current = current.__cause__
    return False


def rejected_without_usage(error: BaseException) -> bool:
    return pre_dispatch_failure(error) or getattr(error, "status_code", None) in {
        400,
        401,
        403,
        404,
        422,
        429,
    }


def retryable_openai(error: BaseException) -> bool:
    # 408/409/5xx and read/write failures may have executed: retain their reservation.
    return pre_dispatch_failure(error) or getattr(error, "status_code", None) == 429


async def retry_delay(attempt: int) -> None:
    await asyncio.sleep(random.SystemRandom().uniform(0.1, min(2.0, 0.25 * 2 ** (attempt - 1))))
