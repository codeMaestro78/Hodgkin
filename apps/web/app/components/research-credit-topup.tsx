"use client";

import Script from "next/script";
import { useEffect, useRef, useState } from "react";
import { checkoutFailureMessage } from "../../lib/billing-pricing";

type Pack = { key: string; amountMinor: number; units: number; expiryDays: null };
type Catalog = { enabled: boolean; currency: string; packs: Pack[] };
type Balance = { enabled: boolean; availableUnits?: number; reservedUnits?: number; frozen?: boolean };
type PendingPurchase = {
  purchaseId: string;
  packageKey: string;
  amountMinor: number;
  currency: string;
  units: number;
  createdAt: string | null;
  orderId: string | null;
  orderState: "not_started" | "creating" | "created" | "uncertain";
  canResume: boolean;
};
type Diagnostics = { ready: boolean; mode: "test" | "live" | "unconfigured"; checks: { id: string; label: string; ready: boolean }[] };
type RazorpayResult = {
  razorpay_payment_id: string;
  razorpay_order_id: string;
  razorpay_signature: string;
};
type CheckoutOrder = {
  purchaseId: string;
  orderId: string;
  amount: number;
  currency: string;
  keyId: string;
};

export function shouldHideCreditTopUp(
  catalog: Catalog | null,
  balance: Balance | null,
  message: string,
): boolean {
  return catalog === null && balance === null && message.length === 0;
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => {
      open: () => void;
      on: (event: string, callback: (details: { error?: { description?: string } }) => void) => void;
    };
  }
}

export function ResearchCreditTopUp({
  revision,
  expanded = false,
  summaryLabel = "Add research units",
}: {
  revision: number;
  expanded?: boolean;
  summaryLabel?: string;
}) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [pendingPurchases, setPendingPurchases] = useState<PendingPurchase[]>([]);
  const [pendingError, setPendingError] = useState("");
  const [refreshingPurchases, setRefreshingPurchases] = useState(false);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [checkoutScriptReady, setCheckoutScriptReady] = useState(false);
  const requestKey = useRef<{ packKey: string; key: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const [catalogResponse, balanceResponse] = await Promise.all([
          fetch("/api/billing/credit-packs", { cache: "no-store", signal: controller.signal }),
          fetch("/api/billing/credit-balance", { cache: "no-store", signal: controller.signal }),
        ]);
        if (!catalogResponse.ok || !balanceResponse.ok) throw new Error();
        const [nextCatalog, nextBalance] = await Promise.all([
          catalogResponse.json() as Promise<Catalog>,
          balanceResponse.json() as Promise<Balance>,
        ]);
        if (!controller.signal.aborted) {
          setCatalog(nextCatalog);
          setBalance(nextBalance);
        }
        try {
          const pendingResponse = await fetch("/api/billing/credit-purchases", {
            cache: "no-store",
            signal: controller.signal,
          });
          if (!pendingResponse.ok) throw new Error("Pending checkouts are unavailable");
          const pending = (await pendingResponse.json()) as { purchases?: PendingPurchase[] };
          if (!controller.signal.aborted) {
            setPendingPurchases(Array.isArray(pending.purchases) ? pending.purchases : []);
            setPendingError("");
          }
        } catch {
          if (!controller.signal.aborted) {
            setPendingError("Pending checkouts could not be checked. Refresh status before starting another purchase.");
          }
        }
        try {
          const diagnosticsResponse = await fetch("/api/billing/credit-packs/diagnostics", {
            cache: "no-store",
            signal: controller.signal,
          });
          if (diagnosticsResponse.ok && !controller.signal.aborted)
            setDiagnostics((await diagnosticsResponse.json()) as Diagnostics);
        } catch {
          // Diagnostics are explanatory only; never make checkout depend on them.
        }
      } catch {
        if (!controller.signal.aborted) setMessage("Purchased-credit balance is temporarily unavailable.");
      }
    }
    void load();
    return () => controller.abort();
  }, [revision]);

  async function refreshPendingPurchases() {
    if (refreshingPurchases) return;
    setRefreshingPurchases(true);
    try {
      const [purchaseResponse, balanceResponse] = await Promise.all([
        fetch("/api/billing/credit-purchases", { cache: "no-store" }),
        fetch("/api/billing/credit-balance", { cache: "no-store" }),
      ]);
      if (!purchaseResponse.ok) throw new Error();
      const payload = (await purchaseResponse.json()) as { purchases?: PendingPurchase[] };
      setPendingPurchases(Array.isArray(payload.purchases) ? payload.purchases : []);
      if (balanceResponse.ok) setBalance((await balanceResponse.json()) as Balance);
      setPendingError("");
    } catch {
      setPendingError("Status could not be refreshed. Your payment state has not been changed.");
    } finally {
      setRefreshingPurchases(false);
    }
  }

  async function openRazorpayCheckout(
    order: CheckoutOrder,
    pack: Pick<Pack, "units" | "amountMinor">,
  ) {
    if (
      !order.orderId.startsWith("order_") ||
      order.amount !== pack.amountMinor ||
      order.currency !== "INR" ||
      !order.keyId.startsWith("rzp_")
    ) throw new Error("The payment order could not be validated.");

    const verify = async (result: RazorpayResult) => {
      setMessage("Verifying payment securely…");
      for (let attempt = 0; attempt < 4; attempt += 1) {
        const verifyResponse = await fetch("/api/billing/credit-checkout/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(result),
        });
        const verification = (await verifyResponse.json()) as { status?: string; detail?: string };
        if (verification.status === "paid") {
          const balanceResponse = await fetch("/api/billing/credit-balance", { cache: "no-store" });
          if (balanceResponse.ok) setBalance((await balanceResponse.json()) as Balance);
          setPendingPurchases((purchases) => purchases.filter((item) => item.purchaseId !== order.purchaseId));
          requestKey.current = null;
          setBusy(null);
          setMessage("Payment verified. Your research units are ready.");
          return;
        }
        if (verification.status !== "processing" || attempt === 3) {
          throw new Error(
            verification.status === "processing"
              ? "Payment is still processing. Your balance will update after capture; do not pay again."
              : verification.detail ?? "Payment could not be verified. No units were added.",
          );
        }
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    };

    const RazorpayConstructor = window.Razorpay;
    if (!RazorpayConstructor) throw new Error("Secure checkout is still loading. Please try again.");
    const checkout = new RazorpayConstructor({
      key: order.keyId,
      amount: order.amount,
      currency: order.currency,
      name: "HogsKin",
      description: `Add ${pack.units} research units`,
      order_id: order.orderId,
      handler: (result: RazorpayResult) => {
        void verify(result).catch((error: unknown) => {
          setBusy(null);
          setMessage(error instanceof Error ? error.message : "Payment verification failed.");
        });
      },
      modal: {
        ondismiss: () => {
          setBusy(null);
          setMessage("Checkout closed. You can continue this same checkout later.");
        },
      },
      theme: { color: "#315b60" },
    });
    checkout.on("payment.failed", (details) => {
      setBusy(null);
      setMessage(details.error?.description ?? "Payment failed. No units were added.");
    });
    checkout.open();
  }

  async function buy(pack: Pack) {
    if (busy) return;
    if (!checkoutScriptReady || !window.Razorpay) {
      setMessage("Secure checkout is still loading. Please try again in a moment.");
      return;
    }
    const key = requestKey.current?.packKey === pack.key
      ? requestKey.current.key
      : crypto.randomUUID();
    requestKey.current = { packKey: pack.key, key };
    setBusy(pack.key);
    setMessage("");
    try {
      const response = await fetch("/api/billing/credit-checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": key },
        body: JSON.stringify({ packageKey: pack.key }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: unknown } | null;
        throw new Error(
          checkoutFailureMessage(
            response.status,
            body?.detail,
            response.headers.get("retry-after"),
          ),
        );
      }
      const order = (await response.json()) as CheckoutOrder;
      await openRazorpayCheckout(order, pack);
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Checkout could not open. If an order was created, retrying uses the same order safely.",
      );
      setBusy(null);
      void refreshPendingPurchases();
    }
  }

  async function resume(purchase: PendingPurchase) {
    if (busy) return;
    if (!purchase.canResume || !catalog?.enabled || !checkoutScriptReady || !window.Razorpay) {
      setMessage("This checkout cannot be safely reopened yet. Refresh its status or contact support.");
      return;
    }
    setBusy(purchase.purchaseId);
    setMessage("");
    try {
      const response = await fetch(`/api/billing/credit-purchases/${purchase.purchaseId}/resume`, {
        method: "POST",
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: unknown } | null;
        throw new Error(typeof body?.detail === "string" ? body.detail : "The existing checkout could not be resumed.");
      }
      const order = (await response.json()) as CheckoutOrder;
      await openRazorpayCheckout(order, purchase);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The existing checkout could not be resumed.");
      setBusy(null);
      void refreshPendingPurchases();
    }
  }

  // Hide only while the initial request is in flight. Once the API has
  // responded, keep the panel visible even for an empty wallet and a disabled
  // catalog so the user can read the non-secret readiness diagnostics.
  if (shouldHideCreditTopUp(catalog, balance, message)) return null;
  return (
    <div className="workspace-credit-topup" aria-label="Purchased research credits">
      {catalog?.enabled && !balance?.frozen && (
        <Script
          src="https://checkout.razorpay.com/v1/checkout.js"
          strategy="afterInteractive"
          onReady={() => setCheckoutScriptReady(true)}
          onError={() => setMessage("Secure checkout could not be loaded. Please try again later.")}
        />
      )}
      {balance?.enabled && (
        <p>
          <strong>{balance.availableUnits} purchased units</strong> available
          {balance.reservedUnits ? ` · ${balance.reservedUnits} reserved` : ""}
        </p>
      )}
      {balance?.frozen && <p role="status">Purchased credits are paused for payment review.</p>}
      {pendingPurchases.length > 0 && (
        <section className="workspace-credit-pending" aria-label="Pending credit checkouts">
          <div className="workspace-credit-pending-heading">
            <strong>Checkout waiting for you</strong>
            <button type="button" onClick={() => void refreshPendingPurchases()} disabled={refreshingPurchases}>
              {refreshingPurchases ? "Checking…" : "Refresh status"}
            </button>
          </div>
          {pendingPurchases.map((purchase) => (
            <div className="workspace-credit-pending-item" key={purchase.purchaseId}>
              <span>
                {purchase.units} units · {(purchase.amountMinor / 100).toLocaleString(undefined, { style: "currency", currency: purchase.currency })}
              </span>
              {purchase.canResume ? (
                <button type="button" onClick={() => void resume(purchase)} disabled={busy !== null || !checkoutScriptReady || !catalog?.enabled}>
                  {busy === purchase.purchaseId ? "Opening same checkout…" : "Continue checkout"}
                </button>
              ) : (
                <p role="status">
                  Payment status needs review. Don’t pay again. Contact support with purchase ID {purchase.purchaseId}
                  {purchase.orderId ? ` and Razorpay order ${purchase.orderId}` : ""}.
                </p>
              )}
            </div>
          ))}
        </section>
      )}
      {pendingError && <p role="status">{pendingError}</p>}
      {catalog?.enabled && !balance?.frozen && (
        <details open={expanded}>
          <summary>{summaryLabel}</summary>
          <p>
            Your monthly plan units are used first; purchased units cover the remaining run cost.
            They do not reset monthly or unlock modes excluded by your plan.
          </p>
          <div className="workspace-credit-packs">
            {catalog.packs.map((pack) => (
              <button key={pack.key} type="button" disabled={busy !== null || pendingPurchases.length > 0 || !checkoutScriptReady} onClick={() => void buy(pack)}>
                {busy === pack.key
                  ? "Opening secure checkout…"
                  : pendingPurchases.length > 0
                    ? "Finish current checkout first"
                  : `${pack.key.charAt(0).toUpperCase()}${pack.key.slice(1)} · ${pack.units} units · ${(pack.amountMinor / 100).toLocaleString(undefined, { style: "currency", currency: catalog.currency })}`}
              </button>
            ))}
          </div>
        </details>
      )}
      {catalog && !catalog.enabled && diagnostics && (
        <details className="workspace-credit-diagnostics">
          <summary>Why can’t I buy credits?</summary>
          <p>Credit checkout is not available until every required setup check passes. No secret values are shown here.</p>
          <ul>
            {diagnostics.checks.filter((check) => !check.ready).map((check) => (
              <li key={check.id}>{check.label} is not ready</li>
            ))}
          </ul>
          {diagnostics.checks.every((check) => check.ready) && (
            <p>All setup checks pass. Refresh the balance or contact support if checkout is still unavailable.</p>
          )}
          <p>Detected Razorpay mode: {diagnostics.mode}.</p>
        </details>
      )}
      {message && <p role="status">{message}</p>}
    </div>
  );
}
