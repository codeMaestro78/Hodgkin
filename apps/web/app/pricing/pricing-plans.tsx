"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "../components/ui";
import { Critter, type CritterKind } from "../components/crew/critter";

type Billing = "monthly" | "yearly";

type Plan = {
  id: string;
  name: string;
  summary: string;
  monthly: string;
  yearly: string;
  yearlyMonthly: string;
  cta: string;
  crew: CritterKind[];
  features: string[];
};

const PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    summary: "For a few good questions a month.",
    monthly: "$0",
    yearly: "$0",
    yearlyMonthly: "$0",
    cta: "Start free",
    crew: ["folio"],
    features: [
      "Proposed: 5 monthly research units · Focused mode",
      "Cited answers with source passages",
      "Research history and personal library",
      "Markdown and BibTeX export",
    ],
  },
  {
    id: "scholar",
    name: "Scholar",
    summary: "For steady, weekly research.",
    monthly: "$5.99",
    yearly: "$59.99",
    yearlyMonthly: "$5.00",
    cta: "Choose Scholar",
    crew: ["lens", "folio"],
    features: [
      "20 monthly research units",
      "Focused and Balanced modes",
      "Compare reports side by side",
      "Revocable read-only report sharing",
      "Markdown and BibTeX export",
    ],
  },
  {
    id: "investigator",
    name: "Investigator",
    summary: "For questions that come back on a schedule.",
    monthly: "$12.99",
    yearly: "$129.99",
    yearlyMonthly: "$10.83",
    cta: "Choose Investigator",
    crew: ["seal", "quill", "lens"],
    features: [
      "40 monthly research units",
      "Focused, Balanced and Deep modes",
      "Bounded batches and scheduled runs",
      "Everything in Scholar",
    ],
  },
];

function PlanCard({
  plan,
  billing,
  checkoutEnabled,
  signedIn,
  busy,
  error,
  onChoose,
}: {
  plan: Plan;
  billing: Billing;
  checkoutEnabled: boolean;
  signedIn: boolean;
  busy: string | null;
  error: string;
  onChoose: (planKey: string) => void;
}) {
  const price = billing === "yearly" ? plan.yearly : plan.monthly;
  return (
    <article className="pr-plan" data-plan={plan.id}>
      <div className="pr-plan-crew" aria-hidden="true">
        {plan.crew.map((kind, index) => (
          <Critter key={kind} kind={kind} size={46} delay={index * 450} />
        ))}
      </div>
      <h3>{plan.name}</h3>
      <p className="pr-plan-summary">{plan.summary}</p>
      <p className="pr-price">
        <span className="pr-price-clip">
          <span className="pr-price-value" key={`${billing}-${price}`}>
            {price}
          </span>
        </span>
        <span className="pr-price-unit">
          {plan.id === "free"
            ? "forever"
            : billing === "yearly"
              ? "/ year"
              : "/ month"}
        </span>
      </p>
      <p className="pr-price-note">
        {plan.id === "free"
          ? "No card needed"
          : billing === "yearly"
            ? `${plan.yearlyMonthly} / month, billed annually`
            : "Billed monthly"}
      </p>
      {plan.id === "free" ? (
        <Link
          href="/signup?plan=free"
          className="lp-btn lp-btn-paper"
          data-magnetic
        >
          {plan.cta}
        </Link>
      ) : !checkoutEnabled ? (
        <span className="lp-btn lp-btn-paper" aria-disabled="true">
          Paid plans coming soon
        </span>
      ) : !signedIn ? (
        <Link href="/login" className="lp-btn lp-btn-paper">
          Sign in to choose
        </Link>
      ) : billing === "yearly" ? (
        <span className="lp-btn lp-btn-paper" aria-disabled="true">
          Annual billing coming soon
        </span>
      ) : (
        <button
          type="button"
          className="lp-btn lp-btn-paper"
          disabled={busy !== null}
          onClick={() => onChoose(plan.id)}
        >
          {busy === plan.id ? "Opening secure checkout…" : plan.cta}
        </button>
      )}
      {error && (
        <p className="pr-checkout-error" role="alert">
          {error}
        </p>
      )}
      <ul className="pr-plan-features">
        {plan.features.map((feature) => (
          <li key={feature}>
            <Icon name="check" size={14} />
            {feature}
          </li>
        ))}
      </ul>
    </article>
  );
}

export function PricingPlans() {
  const [billing, setBilling] = useState<Billing>("monthly");
  const [checkoutEnabled, setCheckoutEnabled] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [checkoutError, setCheckoutError] = useState("");
  const [free, ...paid] = PLANS;

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/billing/checkout-availability", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (response.status === 401) {
          setSignedIn(false);
          return;
        }
        if (!response.ok) return;
        const result = (await response.json()) as {
          enabled?: boolean;
          plans?: string[];
        };
        setSignedIn(true);
        setCheckoutEnabled(result.enabled === true);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  async function choosePlan(planKey: string) {
    if (busy) return;
    setBusy(planKey);
    setCheckoutError("");
    try {
      const response = await fetch("/api/billing/checkout", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": crypto.randomUUID(),
        },
        body: JSON.stringify({ planKey, interval: "monthly" }),
      });
      const result = (await response.json()) as {
        url?: string;
        detail?: string;
      };
      if (!response.ok || !result.url) {
        throw new Error(
          response.status === 401
            ? "Sign in again to continue."
            : "Secure checkout could not be opened. Please try again.",
        );
      }
      const target = new URL(result.url);
      if (
        target.protocol !== "https:" ||
        target.hostname !== "checkout.stripe.com"
      )
        throw new Error("The checkout destination could not be verified.");
      window.location.assign(target.toString());
    } catch (error) {
      setCheckoutError(
        error instanceof Error
          ? error.message
          : "Secure checkout could not be opened.",
      );
      setBusy(null);
    }
  }
  return (
    <>
      <div
        className="pr-billing"
        role="group"
        aria-label="Billing period"
        data-billing={billing}
      >
        <span className="pr-billing-thumb" aria-hidden="true" />
        {(["monthly", "yearly"] as const).map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={billing === option}
            onClick={() => setBilling(option)}
          >
            {option === "monthly" ? "Monthly" : "Yearly"}
            {option === "yearly" && <small>Save about 17%</small>}
          </button>
        ))}
      </div>
      <div className="pr-plans">
        <div className="pr-plan-group pr-plan-free" data-reveal>
          {free && (
            <PlanCard
              plan={free}
              billing={billing}
              checkoutEnabled={false}
              signedIn={signedIn}
              busy={busy}
              error=""
              onChoose={choosePlan}
            />
          )}
        </div>
        <div className="pr-plan-group pr-plan-paid" data-reveal>
          {paid.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              billing={billing}
              checkoutEnabled={checkoutEnabled}
              signedIn={signedIn}
              busy={busy}
              error={checkoutError}
              onChoose={choosePlan}
            />
          ))}
        </div>
      </div>
    </>
  );
}
