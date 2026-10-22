"use client";
import Link from "next/link";
import Script from "next/script";
import { useEffect, useState } from "react";
import { Icon } from "../components/ui";
import { Critter, type CritterKind } from "../components/crew/critter";
import {
  checkoutFailureMessage,
  paidAccessState,
  parseCheckoutAvailability,
  shouldOfferCheckoutResume,
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
type PricingEntitlement = { status?: string; planKey?: "free" | PaidPlanKey };

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
  canResume,
  lockedBySubscription,
  isCurrentPlan,
  onChoose,
  onResume,
  onManage,
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
  canResume: boolean;
  lockedBySubscription: boolean;
  isCurrentPlan: boolean;
  onChoose: (planKey: PaidPlanKey) => void;
  onResume: (planKey: PaidPlanKey, period: Billing) => void;
  onManage: () => void;
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
      ) : isCurrentPlan ? (
        <span className="lp-btn lp-btn-paper" aria-disabled="true">
          Current plan
        </span>
      ) : lockedBySubscription ? (
        <button type="button" className="lp-btn lp-btn-paper" onClick={onManage}>
          Manage current plan
        </button>
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
        <div className="pr-checkout-error" role="alert">
          <p>{error}</p>
          {canResume && plan.id !== "free" && (
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => {
                if (plan.id !== "free") onResume(plan.id, billing);
              }}
            >
              {busy === plan.id ? "Checking status…" : "Check status and reopen checkout"}
            </button>
          )}
        </div>
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
  const [resumeTarget, setResumeTarget] = useState<{ planKey: PaidPlanKey; billingPeriod: Billing } | null>(null);
  const [subscription, setSubscription] = useState<PricingSubscription | null>(null);
  const [entitlement, setEntitlement] = useState<PricingEntitlement | null>(null);
  const [manageBusy, setManageBusy] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [manageMessage, setManageMessage] = useState("");
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
            void refreshBillingState(controller.signal).catch(() => undefined);
          }
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setAuthStatus("unknown");
      });
    return () => controller.abort();
  }, [availabilityAttempt]);

  async function choosePlan(planKey: PaidPlanKey, billingPeriod: Billing = billing) {
    setCheckoutError("");
    setBusy(planKey);
    try {
      const orderResponse = await fetch("/api/billing/checkout", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "idempotency-key": crypto.randomUUID(),
        },
        body: JSON.stringify({ planKey, billingPeriod }),
      });
      const order: unknown = await orderResponse.json().catch(() => null);
      if (!orderResponse.ok || !isSubscriptionCheckout(order)) {
        const detail = getErrorDetail(order);
        setCheckoutError(checkoutFailureMessage(orderResponse.status, detail));
        setResumeTarget(
          shouldOfferCheckoutResume(orderResponse.status, detail)
            ? { planKey, billingPeriod }
            : null,
        );
        setBusy(null);
        return;
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
            await refreshBillingState();
            setResumeTarget(null);
          } catch (error) {
            setCheckoutError(error instanceof Error ? error.message : "Payment verification could not be completed.");
          } finally {
            setBusy(null);
          }
        },
        modal: {
          ondismiss: () => {
            setBusy(null);
            void cancelAbandonedCheckout(planKey, billingPeriod, order.subscriptionId);
          },
        },
        theme: { color: "#222b31" },
      });
      checkout.on("payment.failed", () => {
        setCheckoutError("Payment was not completed. No plan units were granted.");
        setResumeTarget({ planKey, billingPeriod });
      });
      setResumeTarget(null);
      checkout.open();
    } catch (error) {
      setCheckoutError(error instanceof Error ? error.message : "Secure checkout could not be opened.");
      // The request may have reached the API before the connection failed. A same-plan
      // status check is safe: the server reconciles the existing attempt before creating anything.
      setResumeTarget({ planKey, billingPeriod });
      setBusy(null);
    }
  }

  async function refreshBillingState(signal?: AbortSignal) {
    const [subscriptionResponse, entitlementResponse] = await Promise.all([
      fetch("/api/billing/subscription", {
        cache: "no-store",
        ...(signal ? { signal } : {}),
      }),
      fetch("/api/billing/entitlement", {
        cache: "no-store",
        ...(signal ? { signal } : {}),
      }),
    ]);
    const reads: Promise<unknown>[] = [];
    if (subscriptionResponse.ok) {
      reads.push(
        subscriptionResponse
          .json()
          .then((value: { subscription?: PricingSubscription | null }) =>
            setSubscription(value.subscription ?? null),
          ),
      );
    }
    if (entitlementResponse.ok) {
      reads.push(
        entitlementResponse
          .json()
          .then((value: PricingEntitlement) => setEntitlement(value)),
      );
    }
    await Promise.all(reads);
    if (!subscriptionResponse.ok || !entitlementResponse.ok) {
      throw new Error("Some billing status could not be refreshed.");
    }
  }

  async function cancelAbandonedCheckout(planKey: PaidPlanKey, billingPeriod: Billing, subscriptionId: string) {
    try {
      const response = await fetch("/api/billing/checkout/cancel", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ subscriptionId }),
      });
      if (!response.ok) {
        setCheckoutError(
          "Cancellation could not be confirmed. Your checkout is preserved and has not been replaced; check its status or resume it.",
        );
        setResumeTarget({ planKey, billingPeriod });
        return;
      }
      setResumeTarget(null);
      await refreshBillingState();
    } catch {
      setCheckoutError(
        "Could not confirm cancellation. Your checkout is preserved; check its status or resume it.",
      );
      setResumeTarget({ planKey, billingPeriod });
    }
  }

  async function cancelSubscription() {
    setManageBusy(true);
    setManageMessage("");
    try {
      const response = await fetch("/api/billing/portal", { method: "POST" });
      const result: unknown = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(checkoutFailureMessage(response.status, getErrorDetail(result)));
      }
      await refreshBillingState();
      setConfirmCancel(false);
      setManageMessage("Cancellation is scheduled. Your paid access continues through the current period.");
    } catch (error) {
      setManageMessage(error instanceof Error ? error.message : "Cancellation could not be confirmed.");
    } finally {
      setManageBusy(false);
    }
  }
  const planLabel = (planKey: PaidPlanKey) => planKey === "scholar" ? "Scholar" : "Investigator";
  const accessState = paidAccessState(subscription?.status, subscription?.planKey, entitlement?.planKey);
  const subscriptionIsActive = subscription?.status === "active";
  const subscriptionOpen = Boolean(subscription && !["cancelled", "completed", "expired"].includes(subscription.status));
  const canCancel = Boolean(subscription && ["active", "authenticated", "pending", "halted", "paused"].includes(subscription.status) && !subscription.cancelAtCycleEnd);
  const focusSubscriptionManagement = () => {
    const section = document.getElementById("subscription-management");
    section?.scrollIntoView({ behavior: "smooth", block: "center" });
    section?.focus({ preventScroll: true });
  };
  return (
    <>
      <Script
        src="https://checkout.razorpay.com/v1/checkout.js"
        strategy="afterInteractive"
        onError={() => setCheckoutError("Secure checkout could not load. Please try again later.")}
      />
      {subscription && (
        <section id="subscription-management" className="pr-subscription-status" aria-live="polite" tabIndex={-1}>
          <div className="pr-subscription-copy">
            <span className={`pr-subscription-badge pr-subscription-badge-${subscriptionIsActive || accessState === "active" ? "active" : "pending"}`}>
              {subscriptionIsActive
                ? "Active"
                : accessState === "active"
                  ? "Paid plan active"
                  : subscription.status === "authenticated"
                    ? "Authorized"
                    : subscription.status === "created"
                      ? "Checkout awaiting approval"
                      : subscription.status}
            </span>
            <h2>{planLabel(subscription.planKey)}</h2>
            <p>
              {subscriptionIsActive && accessState === "pending"
                ? `${planLabel(subscription.planKey)} is active with Razorpay. Paid units have not synced to your balance yet.`
                : accessState === "active"
                  ? `${planLabel(subscription.planKey)} is active${subscription.currentPeriodEnd ? ` through ${new Date(subscription.currentPeriodEnd).toLocaleDateString()}` : ""}.`
                : accessState === "pending"
                  ? "The subscription is authorized; paid units appear after the first captured payment is confirmed."
                  : subscription.status === "created"
                    ? "This checkout is waiting for your approval. Resume it to continue; no second subscription will be created."
                    : `Subscription status: ${subscription.status}.`}
            </p>
            {subscription.cancelAtCycleEnd && (
              <p className="pr-subscription-note">
                Cancellation is scheduled. Your paid access remains available through the current period.
              </p>
            )}
          </div>
          <div className="pr-subscription-actions">
            {subscription.status === "created" && (
              <button
                type="button"
                className="pr-manage-primary"
                disabled={busy !== null}
                onClick={() => void choosePlan(subscription.planKey, subscription.billingPeriod)}
              >
                {busy === subscription.planKey ? "Checking subscription…" : `Resume ${planLabel(subscription.planKey)} checkout`}
              </button>
            )}
            <button
              type="button"
              className="pr-manage-secondary"
              disabled={manageBusy}
              onClick={() => {
                setManageBusy(true);
                setManageMessage("");
                void refreshBillingState()
                  .then(() => setManageMessage("Subscription status refreshed."))
                  .catch(() => setManageMessage("Could not refresh subscription status. Try again shortly."))
                  .finally(() => setManageBusy(false));
              }}
            >
              {manageBusy ? "Refreshing…" : "Refresh status"}
            </button>
            {canCancel && !confirmCancel && (
              <button
                type="button"
                className="pr-manage-secondary"
                disabled={manageBusy}
                onClick={() => setConfirmCancel(true)}
              >
                Schedule cancellation
              </button>
            )}
          </div>
          {confirmCancel && canCancel && (
            <div className="pr-cancel-confirm" role="group" aria-label="Confirm subscription cancellation">
              <p>
                Cancel at the end of this billing period? You’ll keep {planLabel(subscription.planKey)} access
                {subscription.currentPeriodEnd ? ` through ${new Date(subscription.currentPeriodEnd).toLocaleDateString()}` : " until the period ends"}.
              </p>
              <button type="button" className="pr-manage-secondary" disabled={manageBusy} onClick={() => setConfirmCancel(false)}>
                Keep my plan
              </button>
              <button type="button" className="pr-manage-danger" disabled={manageBusy} onClick={() => void cancelSubscription()}>
                {manageBusy ? "Scheduling…" : "Confirm cancellation"}
              </button>
            </div>
          )}
          {manageMessage && <p className="pr-manage-message" role="status">{manageMessage}</p>}
        </section>
      )}
      {checkoutError && !resumeTarget && (
        <div className="pr-checkout-error pr-checkout-error-global" role="alert">
          <p>{checkoutError}</p>
        </div>
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
              canResume={false}
              lockedBySubscription={false}
              isCurrentPlan={false}
              onChoose={choosePlan}
              onResume={choosePlan}
              onManage={focusSubscriptionManagement}
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
              error={resumeTarget?.planKey === plan.id ? checkoutError : ""}
              canResume={resumeTarget?.planKey === plan.id}
              lockedBySubscription={subscriptionOpen}
              isCurrentPlan={subscription?.planKey === plan.id && (subscriptionIsActive || accessState === "active")}
              onChoose={choosePlan}
              onResume={(planKey) =>
                choosePlan(
                  planKey,
                  resumeTarget?.planKey === planKey
                    ? resumeTarget.billingPeriod
                    : billing,
                )
              }
              onManage={focusSubscriptionManagement}
              onRetryAvailability={() => setAvailabilityAttempt((value) => value + 1)}
            />
          ))}
        </div>
      </div>
    </>
  );
}
