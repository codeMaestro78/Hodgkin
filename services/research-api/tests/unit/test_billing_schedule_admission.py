import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from research_api import jobs
from research_api.billing.ledger import BillingUnitsExhausted
from research_api.config import Settings


async def test_quota_blocked_schedule_rolls_back_partial_run_admission(monkeypatch):
    schedule = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        budget={"max_search_calls": 6, "max_estimated_cost_usd": "5.00"},
        question="A scheduled question",
        approval_required=False,
        mode="focused",
        mode_policy_version="research-modes-v1",
        next_run_at=datetime.now(UTC) - timedelta(minutes=1),
        interval_minutes=60,
        last_quota_blocked_at=None,
        last_quota_blocked_reason=None,
    )

    class Session:
        def __init__(self):
            self.partial_admissions = []

        async def scalars(self, _statement):
            return [schedule]

        async def scalar(self, _statement):
            return 0

        @asynccontextmanager
        async def begin_nested(self):
            before = len(self.partial_admissions)
            try:
                yield
            except Exception:
                del self.partial_admissions[before:]
                raise

    session = Session()

    class Repository:
        def __init__(self, _session, _tenant):
            pass

        async def create_once(self, **_kwargs):
            session.partial_admissions.append("run-and-budget")
            raise BillingUnitsExhausted(
                required_units=1,
                available_units=0,
                period_end=datetime.now(UTC) + timedelta(days=1),
            )

    monkeypatch.setattr(jobs, "RunRepository", Repository)

    await jobs.schedule_due(session, schedule.tenant_id, Settings(APP_ENV="test"))

    assert session.partial_admissions == []
    assert schedule.last_quota_blocked_reason == "insufficient_units"
    assert schedule.last_quota_blocked_at is not None
    assert schedule.next_run_at > datetime.now(UTC)
