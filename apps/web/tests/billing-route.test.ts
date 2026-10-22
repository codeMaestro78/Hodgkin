import { beforeEach, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const proxy = vi.hoisted(() => vi.fn());
vi.mock("../lib/research-proxy", () => ({ forwardResearch: proxy }));
import { GET } from "../app/api/billing/entitlement/route";
import { POST as checkout } from "../app/api/billing/checkout/route";
import { POST as portal } from "../app/api/billing/portal/route";
import { GET as availability } from "../app/api/billing/checkout-availability/route";
import { GET as creditPacks } from "../app/api/billing/credit-packs/route";
import { POST as creditCheckout } from "../app/api/billing/credit-checkout/route";
import { POST as verifySubscription } from "../app/api/billing/verify-subscription/route";
import { GET as subscription } from "../app/api/billing/subscription/route";
import { POST as cancelCheckout } from "../app/api/billing/checkout/cancel/route";

beforeEach(() => {
  proxy.mockReset();
  proxy.mockResolvedValue(
    new Response('{"status":"not_configured"}', { status: 200 }),
  );
});

it("forwards the authenticated entitlement read to the API without client billing inputs", async () => {
  const request = new NextRequest(
    "http://localhost/api/billing/entitlement?plan=investigator&units=999",
  );
  const response = await GET(request);

  expect(proxy).toHaveBeenCalledWith(request, "/billing/entitlement");
  expect(response.status).toBe(200);
});

it("forwards Checkout, Portal, and purchase availability through the authenticated BFF", async () => {
  const checkoutRequest = new NextRequest(
    "http://localhost/api/billing/checkout",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "idempotency-key": "request-key-123",
      },
      body: JSON.stringify({ planKey: "scholar", interval: "monthly" }),
    },
  );
  await checkout(checkoutRequest);
  expect(proxy).toHaveBeenLastCalledWith(
    checkoutRequest,
    "/billing/checkout",
    "POST",
  );

  const portalRequest = new NextRequest("http://localhost/api/billing/portal", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
  });
  await portal(portalRequest);
  expect(proxy).toHaveBeenLastCalledWith(
    portalRequest,
    "/billing/portal",
    "POST",
  );

  const availabilityRequest = new NextRequest(
    "http://localhost/api/billing/checkout-availability",
  );
  await availability(availabilityRequest);
  expect(proxy).toHaveBeenLastCalledWith(
    availabilityRequest,
    "/billing/checkout-availability",
  );

  const packsRequest = new NextRequest(
    "http://localhost/api/billing/credit-packs",
  );
  await creditPacks(packsRequest);
  expect(proxy).toHaveBeenLastCalledWith(packsRequest, "/billing/credit-packs");

  const creditCheckoutRequest = new NextRequest(
    "http://localhost/api/billing/credit-checkout",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "idempotency-key": "credit-request-key-123",
      },
      body: JSON.stringify({ packageKey: "starter" }),
    },
  );
  await creditCheckout(creditCheckoutRequest);
  expect(proxy).toHaveBeenLastCalledWith(
    creditCheckoutRequest,
    "/billing/credit-checkout",
    "POST",
  );
});

it("forwards subscription verification, status, and abandoned-checkout cancellation via BFF", async () => {
  const verificationRequest = new NextRequest(
    "http://localhost/api/billing/verify-subscription",
    { method: "POST", body: JSON.stringify({ razorpay_subscription_id: "sub_fixture123" }) },
  );
  await verifySubscription(verificationRequest);
  expect(proxy).toHaveBeenLastCalledWith(
    verificationRequest,
    "/billing/verify-subscription",
    "POST",
  );

  const subscriptionRequest = new NextRequest("http://localhost/api/billing/subscription");
  await subscription(subscriptionRequest);
  expect(proxy).toHaveBeenLastCalledWith(subscriptionRequest, "/billing/subscription");

  const cancelRequest = new NextRequest("http://localhost/api/billing/checkout/cancel", {
    method: "POST",
    body: JSON.stringify({ subscriptionId: "sub_fixture123" }),
  });
  await cancelCheckout(cancelRequest);
  expect(proxy).toHaveBeenLastCalledWith(
    cancelRequest,
    "/billing/checkout/cancel",
    "POST",
  );
});
