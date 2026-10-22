"use client";
import Link from "next/link";
import Script from "next/script";
import { useEffect, useState } from "react";
import { Icon } from "../components/ui";
import { Critter, type CritterKind } from "../components/crew/critter";
import {
  checkoutFailureMessage,
  parseCheckoutAvailability,
  type CheckoutAvailability,
  type PaidPlanKey,
  waitForPaidPlanActivation,
} from "../../lib/billing-pricing";

type Billing = "monthly" | "yearly";
type PricingSubscription = {
  id: string;
  planKey: PaidPlanKey;
  billingPeriod: Billing;
  status: string;
  currentPeriodEnd: string | null;
  cancelAtCycleEnd: boolean;
};

type RazorpayCheckoutResult = {
  razorpay_payment_id: string;
  razorpay_subscription_id: string;
  razorpay_signature: string;
};

type RazorpayCheckoutOptions = {
  key: string;
  subscription_id: string;
  name: string;
  description: string;
  handler: (result: RazorpayCheckoutResult) => void | Promise<void>;
  modal: { ondismiss: () => void };
  theme: { color: string };
};

type RazorpayCheckoutInstance = {
  open: () => void;
  on: (event: "payment.failed", callback: () => void) => void;
};

type SubscriptionCheckout = {
  subscriptionId: string;
  keyId: string;
  amountMinor: number;
  currency: string;
  name: string;
  description: string;
};

function isSubscriptionCheckout(value: unknown): value is SubscriptionCheckout {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return (
    typeof result.subscriptionId === "string" &&
    typeof result.keyId === "string" &&
    typeof result.amountMinor === "number" &&
    typeof result.currency === "string" &&
    typeof result.name === "string" &&
    typeof result.description === "string"
  );
}

function getErrorDetail(value: unknown): unknown {
  return value && typeof value === "object" ? (value as { detail?: unknown }).detail : undefined;
}

type Plan = {
  id: "free" | PaidPlanKey;
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
    monthly: "₹0",
    yearly: "₹0",
    yearlyMonthly: "₹0",
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
    monthly: "₹599",
    yearly: "₹5,999",
    yearlyMonthly: "₹499.92",
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
    monthly: "₹1,299",
    yearly: "₹12,999",
    yearlyMonthly: "₹1,083.25",
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
  availability,
  availablePlans,
  availablePeriods,
  authStatus,
  signInRequired,
  busy,
  error,
  onChoose,
  onRetryAvailability,
}: {
  plan: Plan;
  billing: Billing;
  availability: CheckoutAvailability["status"] | "loading";
  availablePlans: PaidPlanKey[];
  availablePeriods: ("monthly" | "yearly")[];
  authStatus: "unknown" | "signed-in" | "signed-out";
  signInRequired: boolean;
  busy: string | null;
  error: string;
  onChoose: (planKey: PaidPlanKey) => void;
  onRetryAvailability: () => void;
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
      ) : availability === "loading" ? (
        <span className="lp-btn lp-btn-paper" aria-disabled="true">
          Checking checkout…
        </span>
      ) : signInRequired ||
        (authStatus === "signed-out" && availability !== "disabled") ? (
        <Link href="/login?next=%2Fpricing" className="lp-btn lp-btn-paper">
          Sign in to choose
        </Link>
      ) : availability === "error" ? (
        <button
          type="button"
          className="lp-btn lp-btn-paper"
          onClick={onRetryAvailability}
        >
          Retry checkout status
        </button>
      ) : availability === "disabled" || !availablePlans.includes(plan.id) ? (
        <span className="lp-btn lp-btn-paper" aria-disabled="true">
          Paid plans coming soon
        </span>
      ) : !availablePeriods.includes(billing) ? (
        <span className="lp-btn lp-btn-paper" aria-disabled="true">
          {billing === "yearly" ? "Annual billing coming soon" : "Monthly billing coming soon"}
        </span>
      ) : (
        <button
          type="button"
          className="lp-btn lp-btn-paper"
          disabled={busy !== null}
          onClick={() => {
            if (plan.id !== "free") onChoose(plan.id);
          }}
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
  const [availability, setAvailability] = useState<
    CheckoutAvailability["status"] | "loading"
  >("loading");
  const [authStatus, setAuthStatus] = useState<
    "unknown" | "signed-in" | "signed-out"
  >("unknown");
  const [availablePlans, setAvailablePlans] = useState<PaidPlanKey[]>([]);
  const [availablePeriods, setAvailablePeriods] = useState<("monthly" | "yearly")[]>([]);
  const [signInRequiredPlan, setSignInRequiredPlan] = useState<PaidPlanKey | null>(null);
  const [availabilityAttempt, setAvailabilityAttempt] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [checkoutError, setCheckoutError] = useState("");
  const [subscription, setSubscription] = useState<PricingSubscription | null>(null);
  const [manageBusy, setManageBusy] = useState(false);
  const [free, ...paid] = PLANS;

  useEffect(() => {
    const controller = new AbortController();
    setAvailability("loading");
    void fetch("/api/billing/checkout-availability", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        const result: unknown = await response.json().catch(() => null);
        const parsed = parseCheckoutAvailability(response.ok, result);
        setAvailability(parsed.status);
        setAvailablePlans(parsed.plans);
        setAvailablePeriods(parsed.status === "available" ? parsed.billingPeriods : []);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setAvailability("error");
          setAvailablePlans([]);
          setAvailablePeriods([]);
        }
      });
    void fetch("/api/auth/session", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then((response) => {
        if (!controller.signal.aborted) {
          setAuthStatus(
            response.status === 401
              ? "signed-out"
              : response.ok
                ? "signed-in"
                : "unknown",
          );
          if (response.ok) {
            void fetch("/api/billing/subscription", {
              cache: "no-store",
              signal: controller.signal,
            })
              .then((subscriptionResponse) => subscriptionResponse.json())
              .then((value: { subscription?: PricingSubscription | null }) => {
                if (!controller.signal.aborted) setSubscription(value.subscription ?? null);
              })
              .catch(() => undefined);
          }
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setAuthStatus("unknown");
      });
    return () => controller.abort();
  }, [availabilityAttempt]);

  async function choosePlan(planKey: PaidPlanKey) {
    setCheckoutError("");
    setBusy(planKey);
    try {
      const orderResponse = await fetch("/api/billing/checkout", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": crypto.randomUUID(),
        },
        body: JSON.stringify({ planKey, billingPeriod: billing }),
      });
      const order: unknown = await orderResponse.json().catch(() => null);
      if (!orderResponse.ok || !isSubscriptionCheckout(order)) {
        throw new Error(checkoutFailureMessage(orderResponse.status, getErrorDetail(order)));
      }
      const razorpayWindow = window as Window & {
        Razorpay?: new (options: RazorpayCheckoutOptions) => RazorpayCheckoutInstance;
      };
      if (!razorpayWindow.Razorpay) throw new Error("Secure checkout did not load. Please refresh and try again.");
      const checkout = new razorpayWindow.Razorpay({
        key: order.keyId,
        subscription_id: order.subscriptionId,
        name: order.name,
        description: order.description,
        handler: async (result: RazorpayCheckoutResult) => {
          try {
            const verification = await fetch("/api/billing/verify-subscription", {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: JSON.stringify(result),
            });
            if (!verification.ok) throw new Error("Payment verification could not be completed.");
            const activation = await waitForPaidPlanActivation(async () => {
              const entitlementResponse = await fetch("/api/billing/entitlement", {
                cache: "no-store",
              });
              if (!entitlementResponse.ok) throw new Error("Entitlement is not available yet");
              return entitlementResponse.json() as Promise<{
                status?: string;
                planKey?: string;
              }>;
            });
            setCheckoutError(
              activation
                ? `Payment verified. Your ${activation.planKey} plan is active.`
                : "Payment verified. Plan units appear after Razorpay confirms the captured payment; refresh in a moment.",
            );
            await refreshSubscription();
          } catch (error) {
            setCheckoutError(error instanceof Error ? error.message : "Payment verification could not be completed.");
          } finally {
            setBusy(null);
          }
        },
        modal: {
          ondismiss: () => {
            setBusy(null);
            void cancelAbandonedCheckout(order.subscriptionId);
          },
        },
        theme: { color: "#222b31" },
      });
      checkout.on("payment.failed", () => {
        setCheckoutError("Payment was not completed. No plan units were granted.");
      });
      checkout.open();
    } catch (error) {
      setCheckoutError(error instanceof Error ? error.message : "Secure checkout could not be opened.");
      setBusy(null);
    }
  }

  async function refreshSubscription() {
    const response = await fetch("/api/billing/subscription", { cache: "no-store" });
    if (!response.ok) return;
    const value: { subscription?: PricingSubscription | null } = await response.json();
    setSubscription(value.subscription ?? null);
  }

  async function cancelAbandonedCheckout(subscriptionId: string) {
    try {
      const response = await fetch("/api/billing/checkout/cancel", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ subscriptionId }),
      });
      if (response.ok) await refreshSubscription();
    } catch {
      // The backend retains the attempt as open/uncertain; the UI must not create retries itself.
    }
  }

  async function cancelSubscription() {
    setManageBusy(true);
    setCheckoutError("");
    try {
      const response = await fetch("/api/billing/portal", { method: "POST" });
      const result: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(checkoutFailureMessage(response.status, getErrorDetail(result)));
      }
      await refreshSubscription();
      setCheckoutError("Cancellation is scheduled for the end of the current paid period.");
    } catch (error) {
      setCheckoutError(error instanceof Error ? error.message : "Cancellation could not be confirmed.");
    } finally {
      setManageBusy(false);
    }
  }
  return (
    <>
      <Script
        src="https://checkout.razorpay.com/v1/checkout.js"
        strategy="afterInteractive"
        onError={() => setCheckoutError("Secure checkout could not load. Please try again later.")}
      />
      {subscription && (
        <section className="pr-subscription-status" aria-live="polite">
          <p>
            Current plan: <strong>{subscription.planKey}</strong> · {subscription.status}
            {subscription.currentPeriodEnd && ` · renews/ends ${new Date(subscription.currentPeriodEnd).toLocaleDateString()}`}
            {subscription.cancelAtCycleEnd && " · cancellation scheduled"}
          </p>
          {["active", "authenticated", "pending", "halted", "paused"].includes(subscription.status) && !subscription.cancelAtCycleEnd && (
            <button
              type="button"
              disabled={manageBusy}
              onClick={() => void cancelSubscription()}
            >
              {manageBusy ? "Scheduling cancellation…" : "Cancel at period end"}
            </button>
          )}
        </section>
      )}
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
              availability="disabled"
              availablePlans={[]}
              availablePeriods={[]}
              authStatus={authStatus}
              signInRequired={false}
              busy={busy}
              error=""
              onChoose={choosePlan}
              onRetryAvailability={() => setAvailabilityAttempt((value) => value + 1)}
            />
          )}
        </div>
        <div className="pr-plan-group pr-plan-paid" data-reveal>
          {paid.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              billing={billing}
              availability={availability}
              availablePlans={availablePlans}
              availablePeriods={availablePeriods}
              authStatus={authStatus}
              signInRequired={signInRequiredPlan === plan.id}
              busy={busy}
              error={checkoutError}
              onChoose={choosePlan}
              onRetryAvailability={() => setAvailabilityAttempt((value) => value + 1)}
            />
          ))}
        </div>
      </div>
    </>
  );
}
