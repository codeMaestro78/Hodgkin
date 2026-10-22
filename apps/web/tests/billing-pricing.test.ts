import { describe, expect, it, vi } from "vitest";
import {
  checkoutFailureMessage,
  shouldOfferCheckoutResume,
  paidAccessState,
  parseCheckoutAvailability,
  waitForPaidPlanActivation,
} from "../lib/billing-pricing";

describe("pricing checkout availability", () => {
  it("distinguishes provider-active subscriptions from ledger-confirmed access", () => {
    expect(paidAccessState("active", "scholar", "scholar")).toBe("active");
    expect(paidAccessState("active", "scholar", "free")).toBe("pending");
    expect(paidAccessState("created", "scholar", "free")).toBe("none");
    expect(paidAccessState("active", "investigator", "scholar")).toBe("pending");
    expect(paidAccessState("active", null, "free")).toBe("none");
  });

  it("surfaces safe checkout conflicts instead of hiding the server explanation", () => {
    expect(
      checkoutFailureMessage(
        409,
        "A checkout for a different plan is already open for this account",
      ),
    ).toBe("A checkout for a different plan is already open for this account");
    expect(checkoutFailureMessage(503, "internal details")).toContain(
      "temporarily unavailable",
    );
    expect(checkoutFailureMessage(500, "internal details")).toContain(
      "could not be opened",
    );
    expect(
      checkoutFailureMessage(503, "The configured Razorpay plan could not be verified"),
    ).toContain("No subscription was created");
    expect(
      shouldOfferCheckoutResume(
        503,
        "The existing checkout could not be verified. It is preserved; retry status check before creating another.",
      ),
    ).toBe(true);
    expect(
      shouldOfferCheckoutResume(503, "The configured Razorpay plan could not be verified"),
    ).toBe(false);
    expect(
      checkoutFailureMessage(429, "Finish an existing credit checkout before starting another"),
    ).toBe("Finish an existing credit checkout before starting another");
    expect(checkoutFailureMessage(429, { secrets: "do-not-display" })).toContain("rate-limited");
    expect(
      checkoutFailureMessage(429, "Too many requests. Please retry shortly.", "30"),
    ).toBe("Too many requests. Please try again in 30 seconds.");
  });

  it("exposes only the paid plans explicitly enabled by the server", () => {
    expect(
      parseCheckoutAvailability(true, {
        enabled: true,
        plans: ["scholar", "unknown", "investigator"],
      }),
    ).toEqual({
      status: "available",
      plans: ["scholar", "investigator"],
      billingPeriods: ["monthly"],
    });
  });

  it("keeps checkout closed when the backend says billing is disabled", () => {
    expect(
      parseCheckoutAvailability(true, { enabled: false, plans: [] }),
    ).toEqual({ status: "disabled", plans: [] });
  });

  it("distinguishes an unavailable status endpoint from a deliberate disabled state", () => {
    expect(parseCheckoutAvailability(false, {})).toEqual({
      status: "error",
      plans: [],
    });
    expect(parseCheckoutAvailability(true, { enabled: true, plans: "scholar" })).toEqual({
      status: "error",
      plans: [],
    });
  });

  it("waits for a server-confirmed paid entitlement after Checkout returns", async () => {
    let reads = 0;
    const read = vi.fn(async () => {
      reads += 1;
      return reads === 1
        ? { status: "active", planKey: "free" }
        : { status: "active", planKey: "scholar" };
    });
    const wait = vi.fn(async () => undefined);

    await expect(
      waitForPaidPlanActivation(read, { wait, attempts: 3 }),
    ).resolves.toEqual({ status: "active", planKey: "scholar" });
    expect(read).toHaveBeenCalledTimes(2);
    expect(wait).toHaveBeenCalledTimes(1);
  });

  it("does not treat a redirect or a free entitlement as paid activation", async () => {
    const wait = async () => undefined;
    await expect(
      waitForPaidPlanActivation(
        async () => ({ status: "active", planKey: "free" }),
        { wait, attempts: 3 },
      ),
    ).resolves.toBeNull();
  });
});
