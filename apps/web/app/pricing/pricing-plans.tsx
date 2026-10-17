"use client";
import Link from "next/link";
import { useState } from "react";
import { Icon } from "../components/ui";
import { Critter, type CritterKind } from "../components/crew/critter";

type Billing = "monthly" | "yearly";

type Plan = {
  id: string;
  name: string;
  summary: string;
  monthly: number;
  yearly: number;
  cta: string;
  crew: CritterKind[];
  features: string[];
};

const PLANS: Plan[] = [
  {
    id: "free",
    name: "Free",
    summary: "For a few good questions a month.",
    monthly: 0,
    yearly: 0,
    cta: "Start free",
    crew: ["folio"],
    features: [
      "10 research runs a month",
      "Focused and Balanced depth",
      "Cited answers with source passages",
      "Library, history and PDF export",
    ],
  },
  {
    id: "scholar",
    name: "Scholar",
    summary: "For steady, weekly research.",
    monthly: 14,
    yearly: 11,
    cta: "Choose Scholar",
    crew: ["lens", "folio"],
    features: [
      "60 research runs a month",
      "Deep research, up to 20 sources",
      "Compare reports side by side",
      "Share read-only report links",
    ],
  },
  {
    id: "investigator",
    name: "Investigator",
    summary: "For questions that come back on a schedule.",
    monthly: 36,
    yearly: 29,
    cta: "Choose Investigator",
    crew: ["seal", "quill", "lens"],
    features: [
      "200 research runs a month",
      "Batches of questions in one go",
      "Scheduled runs with approval",
      "Everything in Scholar",
    ],
  },
];

function PlanCard({ plan, billing }: { plan: Plan; billing: Billing }) {
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
            ${price}
          </span>
        </span>
        <span className="pr-price-unit">
          {price === 0 ? "forever" : "/ month"}
        </span>
      </p>
      <p className="pr-price-note">
        {price === 0
          ? "No card needed"
          : billing === "yearly"
            ? `Billed $${price * 12} once a year`
            : "Billed monthly"}
      </p>
      <Link
        href={`/signup?plan=${plan.id}`}
        className={`lp-btn ${plan.id === "free" ? "lp-btn-paper" : "lp-btn-ink"}`}
        data-magnetic
      >
        {plan.cta}
      </Link>
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
  const [free, ...paid] = PLANS;
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
            {option === "yearly" && <small>Save about 20%</small>}
          </button>
        ))}
      </div>
      <div className="pr-plans">
        <div className="pr-plan-group pr-plan-free" data-reveal>
          {free && <PlanCard plan={free} billing={billing} />}
        </div>
        <div className="pr-plan-group pr-plan-paid" data-reveal>
          {paid.map((plan) => (
            <PlanCard key={plan.id} plan={plan} billing={billing} />
          ))}
        </div>
      </div>
    </>
  );
}
