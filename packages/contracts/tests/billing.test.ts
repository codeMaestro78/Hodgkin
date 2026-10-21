import { describe, expect, it } from "vitest";
import {
  BillingEntitlementSchema,
  RazorpayCreditOrderSchema,
  RazorpayPaymentVerificationSchema,
} from "../src/billing";

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

describe("Razorpay Standard Checkout contracts", () => {
  it("accepts only INR orders with a server-issued Razorpay order and public key", () => {
    expect(
      RazorpayCreditOrderSchema.safeParse({
        purchaseId: "3c5c0e8b-47f8-4552-b3a4-7c893d1e1e29",
        orderId: "order_fixture123",
        amount: 100,
        currency: "INR",
        keyId: "rzp_test_fixture123",
      }).success,
    ).toBe(true);
    expect(
      RazorpayCreditOrderSchema.safeParse({
        purchaseId: "3c5c0e8b-47f8-4552-b3a4-7c893d1e1e29",
        orderId: "order_fixture123",
        amount: 100,
        currency: "USD",
        keyId: "rzp_test_fixture123",
        keySecret: "must-not-be-present",
      }).success,
    ).toBe(false);
  });

  it("requires all three callback fields and a SHA-256 signature", () => {
    expect(
      RazorpayPaymentVerificationSchema.safeParse({
        razorpay_payment_id: "pay_fixture123",
        razorpay_order_id: "order_fixture123",
        razorpay_signature: "a".repeat(64),
      }).success,
    ).toBe(true);
    expect(
      RazorpayPaymentVerificationSchema.safeParse({
        razorpay_payment_id: "pay_fixture123",
        razorpay_order_id: "order_fixture123",
        razorpay_signature: "short",
      }).success,
    ).toBe(false);
  });
});
