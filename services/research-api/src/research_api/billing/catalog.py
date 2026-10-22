"""Versioned research-unit catalogs with historical currency and price terms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

from research_api.mode_policy import ResearchMode

CatalogStatus = Literal["draft", "active"]
PlanKey = Literal["free", "scholar", "investigator"]


@dataclass(frozen=True, slots=True)
class PlanTerms:
    key: PlanKey
    monthly_allowance_units: int
    allowed_modes: tuple[ResearchMode, ...]
    currency: Literal["USD", "INR"]
    monthly_price: Decimal
    annual_price: Decimal | None


@dataclass(frozen=True, slots=True)
class BillingCatalog:
    version: str
    status: CatalogStatus
    mode_unit_prices: Mapping[ResearchMode, int]
    plans: Mapping[PlanKey, PlanTerms]

    @property
    def monthly_allowances(self) -> Mapping[PlanKey, int]:
        return MappingProxyType(
            {key: plan.monthly_allowance_units for key, plan in self.plans.items()}
        )


MODE_UNIT_PRICES: Mapping[ResearchMode, int] = MappingProxyType(
    {"focused": 1, "balanced": 2, "deep": 4}
)

LEGACY_BILLING_CATALOG = BillingCatalog(
    version="research-units-v1-2026-10-19",
    status="active",
    mode_unit_prices=MODE_UNIT_PRICES,
    plans=MappingProxyType(
        {
            "free": PlanTerms(
                key="free",
                monthly_allowance_units=5,
                allowed_modes=("focused",),
                currency="USD",
                monthly_price=Decimal("0"),
                annual_price=None,
            ),
            "scholar": PlanTerms(
                key="scholar",
                monthly_allowance_units=40,
                allowed_modes=("focused", "balanced", "deep"),
                currency="USD",
                monthly_price=Decimal("14"),
                annual_price=Decimal("132"),
            ),
            "investigator": PlanTerms(
                key="investigator",
                monthly_allowance_units=120,
                allowed_modes=("focused", "balanced", "deep"),
                currency="USD",
                monthly_price=Decimal("36"),
                annual_price=Decimal("348"),
            ),
        }
    ),
)

USD_BILLING_CATALOG = BillingCatalog(
    version="research-units-v2-2026-10-19",
    status="active",
    mode_unit_prices=MODE_UNIT_PRICES,
    plans=MappingProxyType(
        {
            "free": PlanTerms(
                key="free",
                monthly_allowance_units=5,
                allowed_modes=("focused",),
                currency="USD",
                monthly_price=Decimal("0"),
                annual_price=None,
            ),
            "scholar": PlanTerms(
                key="scholar",
                monthly_allowance_units=20,
                allowed_modes=("focused", "balanced"),
                currency="USD",
                monthly_price=Decimal("5.99"),
                annual_price=Decimal("59.99"),
            ),
            "investigator": PlanTerms(
                key="investigator",
                monthly_allowance_units=40,
                allowed_modes=("focused", "balanced", "deep"),
                currency="USD",
                monthly_price=Decimal("12.99"),
                annual_price=Decimal("129.99"),
            ),
        }
    ),
)

BILLING_CATALOG = BillingCatalog(
    version="research-units-v3-2026-10-22",
    status="active",
    mode_unit_prices=MODE_UNIT_PRICES,
    plans=MappingProxyType(
        {
            "free": PlanTerms(
                key="free",
                monthly_allowance_units=5,
                allowed_modes=("focused",),
                currency="INR",
                monthly_price=Decimal("0"),
                annual_price=None,
            ),
            "scholar": PlanTerms(
                key="scholar",
                monthly_allowance_units=20,
                allowed_modes=("focused", "balanced"),
                currency="INR",
                monthly_price=Decimal("599"),
                annual_price=Decimal("5999"),
            ),
            "investigator": PlanTerms(
                key="investigator",
                monthly_allowance_units=40,
                allowed_modes=("focused", "balanced", "deep"),
                currency="INR",
                monthly_price=Decimal("1299"),
                annual_price=Decimal("12999"),
            ),
        }
    ),
)

APPROVED_CATALOGS: Mapping[str, BillingCatalog] = MappingProxyType(
    {
        LEGACY_BILLING_CATALOG.version: LEGACY_BILLING_CATALOG,
        USD_BILLING_CATALOG.version: USD_BILLING_CATALOG,
        BILLING_CATALOG.version: BILLING_CATALOG,
    }
)


class CatalogNotApprovedError(RuntimeError):
    """Raised if draft commercial terms are used as an authorization source."""


def require_approved_catalog(catalog: BillingCatalog = BILLING_CATALOG) -> BillingCatalog:
    if catalog.status != "active":
        raise CatalogNotApprovedError("billing catalog has not been approved")
    return catalog
