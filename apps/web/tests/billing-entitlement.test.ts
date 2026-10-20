import { expect, it } from "vitest";
import { BillingEntitlementSchema } from "@research/contracts";

it("accepts the server-projected set of modes for an active plan", () => {
  expect(
    BillingEntitlementSchema.safeParse({
      status: "active",
      planKey: "scholar",
      allowedModes: ["focused", "balanced"],
      catalogVersion: "catalog-v2",
      periodStart: "2026-10-01T00:00:00Z",
      periodEnd: "2026-11-01T00:00:00Z",
      allowanceUnits: 20,
      consumedUnits: 0,
      reservedUnits: 0,
      availableUnits: 20,
    }).success,
  ).toBe(true);
});

it("rejects duplicate mode grants and grants on an unconfigured period", () => {
  const active = {
    status: "active",
    planKey: "scholar",
    allowedModes: ["focused", "focused"],
    catalogVersion: "catalog-v2",
    periodStart: "2026-10-01T00:00:00Z",
    periodEnd: "2026-11-01T00:00:00Z",
    allowanceUnits: 20,
    consumedUnits: 0,
    reservedUnits: 0,
    availableUnits: 20,
  };
  expect(BillingEntitlementSchema.safeParse(active).success).toBe(false);
  expect(
    BillingEntitlementSchema.safeParse({
      status: "not_configured",
      allowedModes: ["deep"],
    }).success,
  ).toBe(false);
});
