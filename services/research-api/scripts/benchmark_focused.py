"""Explicitly authorized paid checks, local persistence only; never prints credentials."""

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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


async def benchmark(
    count: int,
    offset: int = 0,
    *,
    question: str | None = None,
    discovery_provider: str | None = None,
    http_client_mode: str = "shared",
) -> None:
    if http_client_mode not in {"shared", "worker"}:
        raise ValueError("unsupported provider HTTP client mode")
    if question is not None and (count != 1 or not 5 <= len(question.strip()) <= 1000):
        raise ValueError("a custom question requires one run and 5–1000 characters")
    # Validate destinations BEFORE importing modules that construct application pools.
    from research_api.config import get_settings

    settings = get_settings()
    if discovery_provider is not None:
        if discovery_provider not in {"tavily", "serper"}:
            raise ValueError("unsupported discovery provider")
        settings = settings.model_copy(
            update={"SERPER_DISCOVERY_ENABLED": discovery_provider == "serper"}
        )
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
    if settings.SERPER_DISCOVERY_ENABLED and not settings.SERPER_API_KEY:
        raise ValueError("Serper discovery requires its configured credential")

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
    from research_api.providers.http_clients import provider_http_transport
    from research_api.report_document import report_diagnostics
    from research_api.repositories.runs import RunBudgetDefaults, RunRepository

    admin = create_async_engine(os.environ["TEST_DATABASE_ADMIN_URL"])
    tenant, user = uuid.uuid4(), uuid.uuid4()
    async with async_sessionmaker(admin)() as session, session.begin():
        session.add(Tenant(id=tenant, name="Isolated authorized live latency benchmark"))
        session.add(User(id=user, tenant_id=tenant, external_subject=f"benchmark:{user}"))
    logger = logging.getLogger("research_api.dependencies")
    previous = logger.level, logger.handlers[:], logger.propagate
    capture = Capture()

    @asynccontextmanager
    async def selected_http_transport() -> AsyncIterator[object | None]:
        if http_client_mode == "worker":
            # Reproduce the pre-pooling lifecycle: each worker adapter owns its
            # own HTTP client and closes it after collection.
            yield None
            return
        async with provider_http_transport(
            timeout_seconds=settings.PROVIDER_TIMEOUT_SECONDS,
            worker_concurrency=settings.WORKER_CONCURRENCY,
        ) as clients:
            yield clients

    logger.setLevel(logging.INFO)
    logger.handlers, logger.propagate = [capture], False
    try:
        async with (
            CheckpointPool(settings) as pool,
            event_wakeups.transport(settings.REDIS_URL),
            selected_http_transport(),
        ):
            questions = (
                [question.strip()] if question is not None else QUESTIONS[offset : offset + count]
            )
            for index, question in enumerate(questions, offset + 1):
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
                    source_rows = list(
                        await session.scalars(select(Source).where(Source.run_id == run.id))
                    )
                    result = {
                        "event": "benchmark.result",
                        "check": index,
                        "runId": str(run.id),
                        "mode": report.document["mode"] if report and report.document else None,
                        "status": final.status,
                        "discoveryProvider": "serper"
                        if settings.SERPER_DISCOVERY_ENABLED
                        else "tavily",
                        "httpClientMode": http_client_mode,
                        "errorCode": final.error_code,
                        "elapsedMs": round(elapsed, 2),
                        "localClaimMs": round(queue_ms, 2),
                        "firstSourceFromCreationMs": round(
                            (first - final.created_at).total_seconds() * 1000, 2
                        )
                        if first
                        else None,
                        "sources": len(source_rows),
                        "sourceDiversity": {
                            "distinctHosts": len(
                                {
                                    (urlsplit(source.canonical_url).hostname or "").lower()
                                    for source in source_rows
                                    if urlsplit(source.canonical_url).hostname
                                }
                            ),
                            "distinctPublishers": len(
                                {
                                    source.publisher.strip().casefold()
                                    for source in source_rows
                                    if source.publisher and source.publisher.strip()
                                }
                            ),
                            "independenceAssessed": False,
                        },
                        "providerOperations": usage.search_calls,
                        "accountedEstimatedCostUsd": str(usage.estimated_cost_usd),
                        "quality": report.document["quality"]
                        if report and report.document
                        else None,
                        "documentDiagnostics": report_diagnostics(report.document)
                        if report and report.document
                        else None,
                        "coverage": {
                            "associationOnly": True,
                            "requirementsTotal": len(report.document["requirements"]),
                            "requirementsAddressed": sum(
                                row["status"] == "addressed"
                                for row in report.document["requirements"]
                            ),
                            "questionsTotal": len(report.document["questionCoverage"]),
                            "questionsAddressed": sum(
                                row["status"] == "addressed"
                                for row in report.document["questionCoverage"]
                            ),
                        }
                        if report and report.document
                        else None,
                        "capturedLogRecords": len(capture.lines),
                        "droppedLogRecords": capture.dropped,
                        "workloadFingerprint": hashlib.sha256(
                            json.dumps(
                                {
                                    "version": "focused-discovery-pair-v1",
                                    "mode": "focused",
                                    "question": question,
                                    "requirements": [
                                        "Explain operational trade-offs",
                                        "State evidence limitations",
                                    ],
                                    "providerOperations": 6,
                                    "activeBudgetMs": 180000,
                                    "modelRouting": final.model_routing,
                                },
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode()
                        ).hexdigest(),
                    }
                metrics = analyze(io.StringIO("\n".join(capture.lines)))
                records = [json.loads(line) for line in capture.lines if line.startswith("{")]
                result["modelCalls"] = [
                    {
                        key: row.get(key)
                        for key in (
                            "role",
                            "model",
                            "provider",
                            "outcome",
                            "remoteDurationMs",
                            "durationMs",
                        )
                    }
                    for row in records
                    if row.get("event") == "dependency.outcome"
                    and row.get("operation") == "model"
                    and row.get("outcome") != "started"
                ]
                result["synthesis"] = [
                    {
                        key: row.get(key)
                        for key in (
                            "candidateCount",
                            "verifiedClaimCount",
                            "rejectionCounts",
                            "claimStatuses",
                        )
                    }
                    for row in records
                    if row.get("operation") == "synthesis.findings"
                ]
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
    parser.add_argument("--question", help="Optional 5–1000 character question; requires --runs 1")
    parser.add_argument("--discovery-provider", choices=("tavily", "serper"))
    parser.add_argument(
        "--compare-discovery",
        action="store_true",
        help="Two paid runs of the same single workload; one per discovery route",
    )
    parser.add_argument(
        "--compare-http-clients",
        action="store_true",
        help="Two paid Focused runs of one workload; worker-owned clients vs shared pools",
    )
    args = parser.parse_args()
    if not args.confirm_paid:
        parser.error("explicit --confirm-paid approval required")
    if args.runs + args.offset > 3:
        parser.error("selected checks must stay within the three-question workload")
    if args.question is not None and (
        args.runs != 1 or not 5 <= len(args.question.strip()) <= 1000
    ):
        parser.error("custom question requires --runs 1 and 5–1000 characters")
    if args.compare_discovery and (args.runs != 1 or args.discovery_provider is not None):
        parser.error("discovery comparison requires --runs 1 and no single-provider override")
    if args.compare_discovery and args.compare_http_clients:
        parser.error("choose only one comparison")
    if args.compare_http_clients and (args.runs != 1 or args.discovery_provider is not None):
        parser.error("HTTP-client comparison requires --runs 1 and no single-provider override")

    async def run_selected() -> None:
        if args.compare_discovery:
            # Preflight before either arm can spend. Same question, requirements,
            # mode, model routes and budgets; each arm gets fresh run/receipts.
            from research_api.config import get_settings

            if not get_settings().SERPER_API_KEY:
                raise ValueError("comparison requires the configured Serper credential")
            for provider in ("tavily", "serper"):
                await benchmark(1, args.offset, question=args.question, discovery_provider=provider)
        elif args.compare_http_clients:
            # Keep all run settings and discovery route fixed; vary only whether
            # provider HTTP clients are worker-owned or shared by the lifespan.
            question = args.question or QUESTIONS[args.offset]
            for mode in ("worker", "shared"):
                await benchmark(
                    1,
                    args.offset,
                    question=question,
                    http_client_mode=mode,
                )
        else:
            await benchmark(
                args.runs,
                args.offset,
                question=args.question,
                discovery_provider=args.discovery_provider,
            )

    try:
        asyncio.run(run_selected())
    except Exception as error:
        print(json.dumps({"event": "benchmark.error", "errorType": type(error).__name__}))
        raise SystemExit(1) from None
