export type PaidPlanKey = "scholar" | "investigator";

export type CheckoutAvailability =
  | { status: "available"; plans: PaidPlanKey[]; billingPeriods: ("monthly" | "yearly")[] }
  | { status: "disabled" | "error"; plans: [] };

const PAID_PLAN_KEYS = new Set<PaidPlanKey>(["scholar", "investigator"]);

export function parseCheckoutAvailability(
  responseOk: boolean,
  payload: unknown,
): CheckoutAvailability {
  if (!responseOk || !payload || typeof payload !== "object") {
    return { status: "error", plans: [] };
  }

  const value = payload as { enabled?: unknown; plans?: unknown; billingPeriods?: unknown };
  if (typeof value.enabled !== "boolean" || !Array.isArray(value.plans)) {
    return { status: "error", plans: [] };
  }
  if (!value.enabled) return { status: "disabled", plans: [] };

  const plans = [...new Set(value.plans)].filter(
    (plan): plan is PaidPlanKey =>
      typeof plan === "string" && PAID_PLAN_KEYS.has(plan as PaidPlanKey),
  );
  const periods = Array.isArray(value.billingPeriods)
    ? [...new Set(value.billingPeriods)].filter(
        (period): period is "monthly" | "yearly" => period === "monthly" || period === "yearly",
      )
    : ["monthly" as const];
  return plans.length && periods.length
    ? { status: "available", plans, billingPeriods: periods }
    : { status: "disabled", plans: [] };
}

export function checkoutFailureMessage(
  status: number,
  detail: unknown,
  retryAfterSeconds?: string | null,
): string {
  const safeDetails = new Set([
    "Too many requests. Please retry shortly.",
    "Daily research-credit purchase limit reached",
    "Finish an existing credit checkout before starting another",
    "Payment order status is uncertain. Do not retry checkout; contact support.",
    "Research-credit purchases are not available",
    "Credit checkout is temporarily unavailable",
    "Research-credit checkout is temporarily unavailable",
  ]);
  if (status === 409 && typeof detail === "string" && detail.length <= 240) {
    return detail;
  }
  if (status === 429 && detail === "Too many requests. Please retry shortly." && retryAfterSeconds) {
    const seconds = Number(retryAfterSeconds);
    if (Number.isInteger(seconds) && seconds > 0 && seconds <= 3600) {
      return `Too many requests. Please try again in ${seconds} seconds.`;
    }
  }
  if (
    (status === 429 || status === 503) &&
    typeof detail === "string" &&
    safeDetails.has(detail)
  ) {
    return detail;
  }
  if (status === 429) {
    return "Checkout is rate-limited. Please wait briefly before trying again.";
  }
  if (status === 503) {
    return "Checkout is temporarily unavailable. Please try again shortly.";
  }
  return "Secure checkout could not be opened. Please try again.";
}

type EntitlementSnapshot = {
  status?: string;
  planKey?: string;
};

type ActivationPollOptions = {
  attempts?: number;
  signal?: AbortSignal;
  wait?: (attempt: number, signal?: AbortSignal) => Promise<void>;
};

function waitBeforeRetry(attempt: number, signal?: AbortSignal): Promise<void> {
  const delayMs = Math.min(500 * 2 ** attempt, 4000);
  return new Promise((resolve) => {
    if (signal?.aborted) {
      resolve();
      return;
    }
    const finish = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", finish);
      resolve();
    };
    const timer = setTimeout(finish, delayMs);
    signal?.addEventListener("abort", finish, { once: true });
  });
}

export async function waitForPaidPlanActivation<T extends EntitlementSnapshot>(
  load: () => Promise<T>,
  options: ActivationPollOptions = {},
): Promise<T | null> {
  const attempts = Math.max(1, Math.floor(options.attempts ?? 7));
  const wait = options.wait ?? waitBeforeRetry;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (options.signal?.aborted) return null;
    try {
      const snapshot = await load();
      if (
        snapshot.status === "active" &&
        (snapshot.planKey === "scholar" || snapshot.planKey === "investigator")
      ) {
        return snapshot;
      }
    } catch {
      // A transient read/webhook delay is bounded by the fixed attempt count.
    }
    if (attempt + 1 < attempts) await wait(attempt, options.signal);
  }
  return null;
}
