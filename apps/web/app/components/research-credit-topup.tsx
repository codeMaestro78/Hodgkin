"use client";

import { useEffect, useRef, useState } from "react";

type Pack = { key: string; amountMinor: number; units: number; expiryDays: null };
type Catalog = { enabled: boolean; currency: string; packs: Pack[] };
type Balance = { enabled: boolean; availableUnits?: number; reservedUnits?: number; frozen?: boolean };

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
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
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
      } catch {
        if (!controller.signal.aborted) setMessage("Purchased-credit balance is temporarily unavailable.");
      }
    }
    void load();
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.get("credits") !== "success") return;
    const sessionId = url.searchParams.get("session_id");
    url.searchParams.delete("credits");
    url.searchParams.delete("session_id");
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
    if (!sessionId || !/^cs_[A-Za-z0-9_]+$/.test(sessionId)) {
      setMessage("Checkout returned without a valid session. Check your balance shortly.");
      return;
    }
    let cancelled = false;
    async function checkPurchase() {
      setMessage("Payment returned. Waiting for verified credit delivery…");
      for (let attempt = 0; attempt < 10 && !cancelled; attempt += 1) {
        try {
          const response = await fetch(`/api/billing/credit-purchases/${sessionId}`, {
            cache: "no-store",
          });
          if (response.ok) {
            const result = (await response.json()) as { status: string };
            if (result.status === "paid") {
              const balanceResponse = await fetch("/api/billing/credit-balance", {
                cache: "no-store",
              });
              if (balanceResponse.ok && !cancelled) {
                setBalance((await balanceResponse.json()) as Balance);
                setMessage("Research credits are ready to use.");
                return;
              }
            } else if (result.status !== "pending") {
              if (!cancelled) setMessage("Payment needs review. Credits were not added; contact support before trying again.");
              return;
            }
          }
        } catch {
          // A transient network error must not imply payment failure or trigger a second purchase.
        }
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
      if (!cancelled) setMessage("Payment confirmation is pending. Refresh the budget shortly; do not buy again yet.");
    }
    void checkPurchase();
    return () => { cancelled = true; };
  }, []);

  async function buy(pack: Pack) {
    if (busy) return;
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
      if (!response.ok) throw new Error();
      const result = (await response.json()) as { url?: string };
      if (!result.url || new URL(result.url).hostname !== "checkout.stripe.com") throw new Error();
      window.location.assign(result.url);
    } catch {
      setMessage("Checkout could not open. No credits were added. Try again or refresh your budget.");
      setBusy(null);
    }
  }

  if (!catalog?.enabled && !balance?.availableUnits && !balance?.reservedUnits && !message)
    return null;
  return (
    <div className="workspace-credit-topup" aria-label="Purchased research credits">
      {balance?.enabled && (
        <p>
          <strong>{balance.availableUnits} purchased units</strong> available
          {balance.reservedUnits ? ` · ${balance.reservedUnits} reserved` : ""}
        </p>
      )}
      {balance?.frozen && <p role="status">Purchased credits are paused for payment review.</p>}
      {catalog?.enabled && !balance?.frozen && (
        <details open={expanded}>
          <summary>{summaryLabel}</summary>
          <p>Purchased units do not reset monthly and do not unlock additional research modes.</p>
          <div className="workspace-credit-packs">
            {catalog.packs.map((pack) => (
              <button key={pack.key} type="button" disabled={busy !== null} onClick={() => void buy(pack)}>
                {busy === pack.key ? "Opening checkout…" : `Add ${pack.units} units · ${(pack.amountMinor / 100).toLocaleString(undefined, { style: "currency", currency: "USD" })}`}
              </button>
            ))}
          </div>
        </details>
      )}
      {message && <p role="status">{message}</p>}
    </div>
  );
}
