import { describe, expect, it } from "vitest";
import { BillingEntitlementSchema } from "../src/billing";

describe("billing entitlement response", () => {
  it("represents the current unconfigured state without fabricated quota fields", () => {
    expect(
      BillingEntitlementSchema.parse({ status: "not_configured" }),
    ).toEqual({
      status: "not_configured",
    });
    expect(
      BillingEntitlementSchema.safeParse({
        status: "not_configured",
        availableUnits: 5,
      }).success,
    ).toBe(false);
  });

  it("accepts only a reconciled server entitlement projection", () => {
    const valid = {
      status: "active",
      planKey: "scholar",
      catalogVersion: "approved-catalog-v1",
      periodStart: "2026-10-01T00:00:00Z",
      periodEnd: "2026-11-01T00:00:00Z",
      allowanceUnits: 40,
      consumedUnits: 8,
      reservedUnits: 4,
      availableUnits: 28,
    } as const;
    expect(BillingEntitlementSchema.parse(valid)).toEqual(valid);
    expect(
      BillingEntitlementSchema.safeParse({ ...valid, availableUnits: 29 })
        .success,
    ).toBe(false);
    expect(
      BillingEntitlementSchema.safeParse({
        ...valid,
        periodEnd: "2026-09-30T00:00:00Z",
      }).success,
    ).toBe(false);
  });
});
