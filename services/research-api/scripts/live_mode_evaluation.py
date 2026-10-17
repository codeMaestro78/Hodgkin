"""Live cross-mode evaluation runner (Phase 6 pilot).

Runs the real graph (OpenAI + Tavily) for each workload case and explicit mode on a
disposable loopback PostgreSQL database migrated to head, then writes
``modes-observation-v1`` records with ``evidence_kind="live_observation"``.

Safety properties:
* The database is always a freshly created loopback database; configured hosted URLs
  are never read (``APP_ENV=test`` disables .env loading for Settings).
* Only provider keys and model routing are read from ``.env``; values are never printed.
* A run starts only if settled model spend plus that mode's worst-case model cost
  (its token ceilings at the configured model rate) stays within ``--max-model-usd``.
* Results are appended per run, so an interrupted evaluation resumes without repeating
  completed runs or forgetting spend.

Observations carry no quality claims: gold labels are drafts awaiting human
adjudication, so rubric metrics, dimension states and human scores stay unset.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "evaluation/modes/v1"
MODES = ("focused", "balanced", "deep")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
sys.path.insert(0, str(ROOT / "scripts"))
ENV_KEYS = ("OPENAI_API_KEY", "TAVILY_API_KEY", "LLM_PROVIDER", "LLM_MODEL_NAME")


def read_env_keys(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key in ENV_KEYS:
            values[key] = value.strip().strip('"').strip("'")
    missing = {"OPENAI_API_KEY", "TAVILY_API_KEY"} - values.keys()
    if missing:
        raise SystemExit(f"missing provider keys in {path.name}: {sorted(missing)}")
    return values


def require_loopback(url: str, name: str) -> None:
    if urlsplit(url).hostname not in LOOPBACK:
        raise SystemExit(f"{name} must point to loopback infrastructure")


def with_database(url: str, name: str) -> str:
    return urlunsplit(urlsplit(url)._replace(path="/" + name))


def worst_case_model_usd(budget, model: str, provider: str) -> Decimal:
    from research_api.pricing import model_rate

    rate = model_rate(model, provider)
    if rate is None:
        return budget.max_estimated_cost_usd
    # The run ledger refuses model calls beyond these token ceilings.
    return rate.cost(budget.max_input_tokens, budget.max_output_tokens)


def admit(spent: Decimal, worst_case: Decimal, cap: Decimal) -> bool:
    return spent + worst_case <= cap


def source_tree_sha256() -> str:
    digest = hashlib.sha256()
    for path in sorted((ROOT / "src/research_api").rglob("*.py")):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def load_receipts(path: Path) -> dict[tuple[str, str], dict]:
    done: dict[tuple[str, str], dict] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            done[(row["case_id"], row["mode"])] = row
    return done


def append_line(path: Path, line: str) -> None:
    with path.open("a") as handle:
        handle.write(line + "\n")


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def observation(case, mode: str, receipt: dict, snapshot: dict, limits: dict) -> dict:
    from evaluate_modes import METRICS

    def measured(value, source):
        return {"value": value, "source": source if value is not None else None}

    return {
        "version": "modes-observation-v1",
        "case_id": case.id,
        "mode": mode,
        "requested_mode": mode,
        "policy_origin": "explicit",
        "evidence_kind": "live_observation",
        "snapshot": snapshot,
        "receipt_sha256": hashlib.sha256(canonical(receipt).encode()).hexdigest(),
        "limits": limits,
        "usage": {
            "operations": receipt["operations"],
            "sources": receipt["sources"],
            "verified_findings": receipt["verified_findings"],
            "input_tokens": receipt["input_tokens"],
            "output_tokens": receipt["output_tokens"],
        },
        # Case dimensions are evaluation labels; mapping them requires human adjudication.
        "dimension_states": {d.id: "unknown" for d in case.dimensions},
        "quality": "partial" if receipt["verified_findings"] else "insufficient_evidence",
        "failed": receipt["status"] != "completed",
        "human_review_reference": None,
        "metrics": {name: None for name in METRICS},
        "human_scores": {
            name: None for name in ("directness", "decision_usefulness", "information_density")
        },
        "measurements": {
            "queue_wait_ms": measured(0, "direct_graph_invocation_no_queue"),
            "first_useful_evidence_ms": measured(
                receipt["first_source_ms"], "first_source_retrieved_at_minus_run_start"
            ),
            "end_to_end_ms": measured(receipt["end_to_end_ms"], "runner_monotonic_clock"),
            "estimated_cost_usd": measured(
                float(receipt["ledger_cost_usd"]), "usage_ledger_model_and_tavily_policy_estimate"
            ),
            "settled_cost_usd": measured(
                float(receipt["model_cost_usd"]), "model_provider_usage_at_pricing_table"
            ),
        },
    }


async def collect(tenant, run_id, started_at: datetime) -> dict:
    from sqlalchemy import func, select

    from research_api.db.models import ProviderCall, Report, ResearchRun, Source, UsageLedger
    from research_api.db.session import tenant_session

    async with tenant_session(str(tenant)) as session:
        run = await session.get(ResearchRun, run_id)
        usage = await session.scalar(select(UsageLedger).where(UsageLedger.run_id == run_id))
        report = await session.scalar(
            select(Report).where(Report.run_id == run_id).order_by(Report.version.desc())
        )
        calls = list(
            await session.scalars(select(ProviderCall).where(ProviderCall.run_id == run_id))
        )
        sources = await session.scalar(
            select(func.count()).select_from(Source).where(Source.run_id == run_id)
        )
        first_source = await session.scalar(
            select(func.min(Source.retrieved_at)).where(Source.run_id == run_id)
        )
    raw_ops: dict[str, int] = {}
    operations = {"search": 0, "extract": 0}
    model_cost = Decimal(0)
    for call in calls:
        if call.provider == "internal" and call.operation == "model":
            cost = ((call.provider_usage or {}).get("accounting") or {}).get("costUsd")
            model_cost += Decimal(cost) if cost is not None else Decimal(0)
            continue
        key = f"{call.provider}:{call.operation}"
        raw_ops[key] = raw_ops.get(key, 0) + 1
        if call.provider in {"tavily", "serper"}:
            if "extract" in call.operation:
                operations["extract"] += 1
            elif "search" in call.operation:
                operations["search"] += 1
    document = (report.document or {}) if report else {}
    narrative = document.get("narrative") or {}
    return {
        "run_id": str(run_id),
        "status": run.status,
        "error_code": run.error_code,
        "operations": operations,
        "raw_provider_operations": raw_ops,
        "ledger_search_calls": usage.search_calls if usage else 0,
        "sources": int(sources or 0),
        "verified_findings": len(document.get("findings") or []) if report else 0,
        "report_version": document.get("version"),
        "report_published": bool(report and report.published),
        "report_content_hash": report.content_hash if report else None,
        "narrative_status": narrative.get("status"),
        "narrative_reason": narrative.get("reason"),
        "input_tokens": usage.input_tokens if usage else None,
        "output_tokens": usage.output_tokens if usage else None,
        "ledger_cost_usd": str(usage.estimated_cost_usd if usage else Decimal(0)),
        "model_cost_usd": str(model_cost),
        "first_source_ms": (
            max(0, int((first_source - started_at).total_seconds() * 1000))
            if first_source
            else None
        ),
    }


async def evaluate(args, values: dict[str, str]) -> int:
    from evaluate_modes import load_cases, validate_observations
    from langgraph.checkpoint.memory import InMemorySaver
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from research_api.config import Settings
    from research_api.db.models import Tenant, User
    from research_api.db.session import tenant_session
    from research_api.graph import builder
    from research_api.mode_policy import MODE_POLICY_VERSION, resolve_mode_budget
    from research_api.mode_reports import policy_for_mode
    from research_api.repositories.runs import RunRepository

    class Checkpointer(InMemorySaver):
        def __init__(self, thread_id):
            super().__init__()
            self.thread_id = thread_id

        def config(self):
            return {"configurable": {"thread_id": self.thread_id}}

    cases = load_cases(FIXTURES / "cases.jsonl")
    if args.cases:
        wanted = set(args.cases)
        cases = [case for case in cases if case.id in wanted]
    modes = args.modes or list(MODES)
    done = load_receipts(args.receipts_path)
    spent = sum((Decimal(r["model_cost_usd"]) for r in done.values()), Decimal(0))
    cap = Decimal(args.max_model_usd)

    settings = Settings(
        _env_file=None,
        OPENAI_API_KEY=values["OPENAI_API_KEY"],
        TAVILY_API_KEY=values["TAVILY_API_KEY"],
        LLM_PROVIDER=values.get("LLM_PROVIDER", "openai"),
        LLM_MODEL_NAME=values.get("LLM_MODEL_NAME", "gpt-4o-mini"),
    )
    model, provider = settings.LLM_MODEL_NAME, settings.LLM_PROVIDER
    snapshot = {
        "model": model,
        "provider": f"{provider}+tavily",
        "prompt": "source_tree_sha256:" + source_tree_sha256(),
        "schema": "modes-observation-v1",
        "graph": builder.MODE_GRAPH_VERSION,
        "policy": MODE_POLICY_VERSION,
    }
    admin = create_async_engine(os.environ["DATABASE_ADMIN_URL"])
    tenant, user = uuid.uuid4(), uuid.uuid4()
    try:
        async with async_sessionmaker(admin)() as session, session.begin():
            session.add(Tenant(id=tenant, name="Live mode evaluation"))
            session.add(User(id=user, tenant_id=tenant, external_subject=str(user)))
    finally:
        await admin.dispose()

    for case in cases:
        for mode in modes:
            if (case.id, mode) in done:
                continue
            budget = resolve_mode_budget(mode)
            worst = worst_case_model_usd(budget, model, provider)
            if not admit(spent, worst, cap):
                print(f"STOP {case.id}/{mode}: {spent} + worst {worst} > {cap}", flush=True)
                return 2
            async with tenant_session(str(tenant)) as session:
                run = await RunRepository(session, tenant).create(
                    user_id=user,
                    question=case.question,
                    mode=mode,
                    mode_policy_version=MODE_POLICY_VERSION,
                    budget=budget,
                )
                run_id = run.id
            started_at, started = datetime.now(UTC), monotonic()
            runner_error = None
            try:
                await asyncio.wait_for(
                    builder.run_graph(
                        settings,
                        tenant_id=tenant,
                        user_id=user,
                        run_id=run_id,
                        question=case.question,
                        checkpointer=Checkpointer(f"{tenant}:{run_id}"),
                    ),
                    timeout=budget.max_wall_clock_ms / 1000 + 180,
                )
            except Exception as exc:  # recorded honestly as a failed observation
                runner_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            elapsed = int((monotonic() - started) * 1000)
            receipt = await collect(tenant, run_id, started_at)
            receipt.update(
                case_id=case.id,
                mode=mode,
                end_to_end_ms=elapsed,
                runner_error=runner_error,
                question_sha256=hashlib.sha256(case.question.encode()).hexdigest(),
            )
            spent += Decimal(receipt["model_cost_usd"])
            policy = policy_for_mode(
                budget.max_search_calls, mode=mode, max_sources=budget.max_sources
            )
            receipt["limits"] = {
                "provider_operations": budget.max_provider_operations or budget.max_search_calls,
                "sources": policy.source_count,
                "candidate_findings": policy.candidate_count,
                "context_chars": policy.context_chars,
                "output_tokens": policy.output_tokens,
                "plan_questions": policy.question_count,
            }
            append_line(args.receipts_path, canonical(receipt))
            done[(case.id, mode)] = receipt
            print(
                f"{case.id}/{mode}: {receipt['status']} {elapsed / 1000:.0f}s "
                f"findings={receipt['verified_findings']} sources={receipt['sources']} "
                f"ops={receipt['operations']} model=${receipt['model_cost_usd']} "
                f"total_model=${spent}" + (f" error={runner_error}" if runner_error else ""),
                flush=True,
            )

    by_id = {case.id: case for case in load_cases(FIXTURES / "cases.jsonl")}
    rows = [
        observation(by_id[c], m, receipt, snapshot, receipt["limits"])
        for (c, m), receipt in sorted(done.items())
    ]
    validate_observations(rows, list(by_id.values()))
    write_json(args.observations_path, rows)
    print(f"wrote {len(rows)} observations; total model spend ${spent}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True, help="directory outside the repository")
    parser.add_argument("--max-model-usd", default="3.00")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--modes", nargs="*", choices=MODES)
    parser.add_argument("--keep-database", action="store_true")
    args = parser.parse_args()
    out = Path(args.output).resolve()
    if out.is_relative_to(ROOT.parents[1]):
        raise SystemExit("write live results outside the repository")
    out.mkdir(parents=True, exist_ok=True)
    args.receipts_path, args.observations_path = out / "receipts.jsonl", out / "observations.json"

    values = read_env_keys(ROOT / ".env")
    os.environ["APP_ENV"] = "test"
    sys.path.insert(0, str(ROOT / "tests"))
    import conftest  # noqa: F401  # enforces loopback DB/S3 defaults for this process
    import psycopg

    for name in ("DATABASE_URL", "DATABASE_ADMIN_URL", "OBJECT_STORAGE_ENDPOINT"):
        require_loopback(os.environ[name], name)
    database = "live_mode_eval_" + uuid.uuid4().hex[:8]
    base_admin = os.environ["DATABASE_ADMIN_URL"]
    scheme, rest = base_admin.split("://", 1)
    plain = scheme.split("+", 1)[0] + "://" + rest
    with psycopg.connect(plain, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{database}"')
    print(f"database {database}", flush=True)
    os.environ["DATABASE_URL"] = with_database(os.environ["DATABASE_URL"], database)
    os.environ["DATABASE_ADMIN_URL"] = with_database(base_admin, database)
    os.environ["TEST_DATABASE_ADMIN_URL"] = os.environ["DATABASE_ADMIN_URL"]
    os.environ.update({k: v for k, v in values.items()})
    try:
        import subprocess

        migrated = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env=os.environ,
            capture_output=True,
            text=True,
        )
        if migrated.returncode:
            print(migrated.stderr[-600:], file=sys.stderr)
            return 1
        import boto3

        from research_api.config import Settings

        storage = Settings(_env_file=None)
        s3 = boto3.client(
            "s3",
            endpoint_url=storage.OBJECT_STORAGE_ENDPOINT,
            aws_access_key_id=storage.OBJECT_STORAGE_ACCESS_KEY.get_secret_value(),
            aws_secret_access_key=storage.OBJECT_STORAGE_SECRET_KEY.get_secret_value(),
            region_name=storage.OBJECT_STORAGE_REGION,
        )
        bucket = storage.OBJECT_STORAGE_BUCKET
        if bucket not in {b["Name"] for b in s3.list_buckets().get("Buckets", [])}:
            s3.create_bucket(Bucket=bucket)
        return asyncio.run(evaluate(args, values))
    finally:
        if not args.keep_database:
            with psycopg.connect(plain, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
            print(f"dropped {database}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
