"""Explicitly authorized paid checks, local persistence only; never prints credentials."""

import argparse
import asyncio
import io
import json
import logging
import os
import uuid
from time import monotonic
from urllib.parse import urlsplit

from latency_report import analyze

QUESTIONS = [
    "Compare PostgreSQL LISTEN/NOTIFY and Redis Pub/Sub for delivering research progress "
    "events. Explain replay guarantees and connection-pooling constraints.",
    "Compare LangGraph checkpointing and application-level retries for a small research "
    "service. Explain recovery guarantees and cost-accounting trade-offs.",
    "Compare exact-quotation verification and semantic evidence checking in research "
    "assistants. Explain their limitations and practical latency trade-offs.",
]


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self.dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        if len(self.lines) < 10_000:
            self.lines.append(record.getMessage())
        else:
            self.dropped += 1


async def benchmark(count: int, offset: int = 0) -> None:
    # Validate destinations BEFORE importing modules that construct application pools.
    from research_api.config import get_settings

    settings = get_settings()
    targets = [
        settings.DATABASE_URL,
        os.environ.get("TEST_DATABASE_ADMIN_URL", ""),
        settings.OBJECT_STORAGE_ENDPOINT,
        settings.REDIS_URL,
    ]
    if settings.APP_ENV != "test" or any(
        parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.query or parsed.fragment
        for value in targets
        for parsed in [urlsplit(value.replace("postgresql+psycopg://", "postgresql://"))]
    ):
        raise ValueError("benchmark requires explicit loopback test infrastructure")
    if not settings.OPENAI_API_KEY or not settings.TAVILY_API_KEY:
        raise ValueError("both live provider credentials must be configured")

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from research_api import jobs
    from research_api.checkpointing import CheckpointPool
    from research_api.db.models import (
        Report,
        ResearchRun,
        RunEvent,
        Source,
        Tenant,
        UsageLedger,
        User,
    )
    from research_api.db.session import engine, tenant_session
    from research_api.dispatcher import execute
    from research_api.events.wakeups import event_wakeups
    from research_api.repositories.runs import RunBudgetDefaults, RunRepository

    admin = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    tenant, user = uuid.uuid4(), uuid.uuid4()
    async with async_sessionmaker(admin)() as session, session.begin():
        session.add(Tenant(id=tenant, name="Isolated authorized live latency benchmark"))
        session.add(User(id=user, tenant_id=tenant, external_subject=f"benchmark:{user}"))
    logger = logging.getLogger("research_api.dependencies")
    previous = logger.level, logger.handlers[:], logger.propagate
    capture = Capture()
    logger.setLevel(logging.INFO)
    logger.handlers, logger.propagate = [capture], False
    try:
        async with CheckpointPool(settings) as pool, event_wakeups.transport(settings.REDIS_URL):
            for index, question in enumerate(QUESTIONS[offset : offset + count], offset + 1):
                capture.lines.clear()
                capture.dropped = 0
                started = monotonic()
                async with tenant_session(str(tenant)) as session:
                    run = await RunRepository(session, tenant).create(
                        user_id=user,
                        question=question,
                        report_requirements=[
                            "Explain operational trade-offs",
                            "State evidence limitations",
                        ],
                        budget=RunBudgetDefaults(max_search_calls=6, max_wall_clock_ms=180_000),
                    )
                    await jobs.enqueue(session, run, settings)
                queued_at = monotonic()
                fence = await jobs.claim(tenant, uuid.uuid4(), settings)
                if fence is None or fence.run_id != run.id:
                    raise RuntimeError("benchmark job was not claimed")
                queue_ms = (monotonic() - queued_at) * 1000
                print(
                    json.dumps(
                        {"event": "benchmark.started", "check": index, "runId": str(run.id)}
                    ),
                    flush=True,
                )
                await execute(fence, settings, pool)
                elapsed = (monotonic() - started) * 1000
                async with tenant_session(str(tenant)) as session:
                    final = await session.get(ResearchRun, run.id)
                    if final is None:
                        raise RuntimeError("benchmark run missing")
                    report = await session.get(Report, final.report_id) if final.report_id else None
                    usage = await session.scalar(
                        select(UsageLedger).where(UsageLedger.run_id == run.id)
                    )
                    if usage is None:
                        raise RuntimeError("benchmark accounting missing")
                    first = await session.scalar(
                        select(func.min(RunEvent.occurred_at)).where(
                            RunEvent.run_id == run.id, RunEvent.event_type == "source.discovered"
                        )
                    )
                    sources = await session.scalar(
                        select(func.count()).select_from(Source).where(Source.run_id == run.id)
                    )
                    result = {
                        "event": "benchmark.completed",
                        "check": index,
                        "runId": str(run.id),
                        "status": final.status,
                        "errorCode": final.error_code,
                        "elapsedMs": round(elapsed, 2),
                        "localClaimMs": round(queue_ms, 2),
                        "firstSourceFromCreationMs": round(
                            (first - final.created_at).total_seconds() * 1000, 2
                        )
                        if first
                        else None,
                        "sources": sources,
                        "providerOperations": usage.search_calls,
                        "accountedEstimatedCostUsd": str(usage.estimated_cost_usd),
                        "quality": report.document["quality"]
                        if report and report.document
                        else None,
                        "capturedLogRecords": len(capture.lines),
                        "droppedLogRecords": capture.dropped,
                    }
                metrics = analyze(io.StringIO("\n".join(capture.lines)))
                result["dependencies"] = [
                    item for item in metrics["dependencies"] if item["category"] == "attempt"
                ]
                result["nodes"] = [
                    item for item in metrics["operations"] if item["operation"].startswith("node.")
                ]
                print(json.dumps(result), flush=True)
                if final.status != "completed":
                    # Do not blindly repeat failing paid attempts.
                    break
    finally:
        logger.setLevel(previous[0])
        logger.handlers, logger.propagate = previous[1], previous[2]
        await admin.dispose()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid", action="store_true")
    parser.add_argument("--runs", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--offset", type=int, choices=(0, 1, 2), default=0)
    args = parser.parse_args()
    if not args.confirm_paid:
        parser.error("explicit --confirm-paid approval required")
    if args.runs + args.offset > 3:
        parser.error("selected checks must stay within the three-question workload")
    try:
        asyncio.run(benchmark(args.runs, args.offset))
    except Exception as error:
        print(json.dumps({"event": "benchmark.error", "errorType": type(error).__name__}))
        raise SystemExit(1) from None
