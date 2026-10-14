"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Brand, Icon } from "./ui";
import {
  canComplete,
  emptyOnboarding,
  onboardingProfileSchema,
  stepValid,
} from "../../lib/onboarding";
import type { OnboardingDraft, OnboardingProfile } from "../../lib/onboarding";

const steps = [
  "About you",
  "Your field",
  "Your workplace",
  "Your question",
  "Research depth",
  "Ready to research",
];
const roles = [
  ["Student", "Coursework, thesis and exploration"],
  ["Researcher", "Evidence and new perspectives"],
  ["Engineer / builder", "Technical decisions and comparisons"],
  ["Founder / operator", "Markets, products and strategy"],
  ["Writer / analyst", "Clear explanations and source checks"],
  ["Educator", "Teaching and deeper understanding"],
];
const fields = [
  "Computer science",
  "Engineering",
  "Business & economics",
  "Medicine & health",
  "Biology",
  "Social sciences",
  "Education",
  "Environmental science",
  "Design",
  "Public policy",
];
const workplaces = [
  ["University", "Study, teaching or academic research"],
  ["Company", "Products, markets and decisions"],
  ["Healthcare", "Clinical and health research"],
  ["Research lab", "Independent or institutional research"],
  ["Government", "Policy and public-sector work"],
  ["Independent", "Personal projects or freelance work"],
] as const;
const depths = [
  ["Focused", "Up to 6 sources", "One specific question or a quick decision."],
  [
    "Balanced",
    "Up to 12 sources",
    "Broader coverage and considered comparisons.",
  ],
  ["Deep", "Up to 20 sources", "More perspectives and supporting evidence."],
] as const;
const suggestions = [
  "Compare tools for building a reliable research agent",
  "Understand the evidence behind a recent development",
  "Explore a market before making a product decision",
];

export function OnboardingFlow({
  initialProfile,
  next = "/research",
}: {
  initialProfile: OnboardingProfile | null;
  next?: string;
}) {
  const [draft, setDraft] = useState<OnboardingDraft>(
    initialProfile ?? emptyOnboarding,
  );
  const [step, setStep] = useState(
    initialProfile?.status === "in_progress" ? initialProfile.step : 1,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) heading.current?.focus({ preventScroll: true });
    started.current = true;
  }, [step]);
  function update<K extends keyof OnboardingDraft>(
    key: K,
    value: OnboardingDraft[K],
  ) {
    setDraft((current) => ({ ...current, [key]: value }));
    setError("");
    setSaved("");
  }
  async function save(action: "save" | "complete" | "skip", targetStep = step) {
    if (busy) return;
    setBusy(true);
    setError("");
    setSaved("");
    try {
      // Copy only known fields; initialProfile also contains persistence metadata.
      const { role, field, workplace, workplaceName, topic, depth } = draft;
      const response = await fetch("/api/onboarding", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          action,
          step: targetStep,
          next,
          draft: { role, field, workplace, workplaceName, topic, depth },
        }),
      });
      const body = (await response.json()) as {
        profile?: unknown;
        redirect?: string;
        error?: string;
      };
      if (
        !response.ok ||
        !onboardingProfileSchema.safeParse(body.profile).success
      )
        throw new Error(
          body.error ?? "Your setup was not saved. Please try again.",
        );
      if (action !== "save") {
        const destination = body.redirect === next ? next : "/research";
        window.location.assign(
          action === "complete" && destination === "/research"
            ? "/research?setup=ready"
            : destination,
        );
        return;
      }
      setStep(targetStep);
      setSaved("Progress saved to your account.");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Setup could not be saved. Please try again.",
      );
    }
    setBusy(false);
  }
  function continueStep(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!stepValid(step, draft)) return;
    void save(step === 6 ? "complete" : "save", Math.min(6, step + 1));
  }
  const headings = [
    "What best describes you?",
    "What’s your field?",
    "Where do you do your work?",
    "What are you researching?",
    "How much ground should we cover?",
    "Your workspace, ready for you.",
  ];
  const descriptions = [
    "Choose a role or describe it in your own words. You can change these details later.",
    "Pick a field or type your own. This stays in your account as context for your work.",
    "Choose the kind of place you work. Naming an organisation is optional and does not create a team workspace.",
    "A question is enough. We’ll place it in the composer for you to review—not start a search automatically.",
    "Choose a default, not a subscription. You can change the depth before every research run.",
    "Review your choices. You stay in control of the question, scope and when research begins.",
  ];
  return (
    <div className="onboarding-page">
      <a href="#onboarding-content" className="skip-link">
        Skip to setup
      </a>
      <header className="onboarding-header">
        <Brand />
        <div className="onboarding-progress">
          <progress value={step} max={6} aria-label="Setup progress" />
          <span>
            Step {step} of 6 · {steps[step - 1]}
          </span>
        </div>
        <button
          className="onboarding-skip"
          disabled={busy}
          onClick={() => void save("skip")}
        >
          Skip setup
        </button>
      </header>
      <main id="onboarding-content" className="onboarding-content">
        <nav className="onboarding-step-nav" aria-label="Setup steps">
          {steps.map((label, index) => (
            <span
              key={label}
              aria-current={step === index + 1 ? "step" : undefined}
              data-current={step === index + 1}
              data-done={step > index + 1}
            >
              {index + 1}
              <span>{label}</span>
            </span>
          ))}
        </nav>
        <form
          onSubmit={continueStep}
          className="onboarding-form"
          aria-busy={busy}
        >
          <section
            key={step}
            className="onboarding-step"
            aria-labelledby="onboarding-heading"
          >
            <p className="onboarding-kicker">{steps[step - 1]}</p>
            <h1 id="onboarding-heading" ref={heading} tabIndex={-1}>
              {headings[step - 1]}
            </h1>
            <p className="onboarding-description">{descriptions[step - 1]}</p>
            <fieldset disabled={busy} className="onboarding-fields">
              <legend className="sr-only">{steps[step - 1]}</legend>
              {step === 1 && (
                <>
                  <label htmlFor="onboarding-role">Your role</label>
                  <input
                    id="onboarding-role"
                    value={draft.role}
                    onChange={(e) => update("role", e.target.value)}
                    maxLength={120}
                    placeholder="e.g. Research scientist, product analyst…"
                    autoComplete="organization-title"
                  />
                  <div className="onboarding-options two-columns">
                    {roles.map(([name, description]) => (
                      <button
                        type="button"
                        key={name}
                        aria-pressed={draft.role === name}
                        onClick={() => update("role", name!)}
                      >
                        <Icon name="book" size={18} />
                        <span>
                          <strong>{name}</strong>
                          <small>{description}</small>
                        </span>
                        {draft.role === name && <Icon name="check" size={16} />}
                      </button>
                    ))}
                  </div>
                </>
              )}
              {step === 2 && (
                <>
                  <label htmlFor="onboarding-field">Your field</label>
                  <input
                    id="onboarding-field"
                    value={draft.field}
                    onChange={(e) => update("field", e.target.value)}
                    maxLength={120}
                    placeholder="e.g. Distributed systems, health economics…"
                  />
                  <div className="onboarding-chips">
                    {fields.map((field) => (
                      <button
                        type="button"
                        key={field}
                        aria-pressed={draft.field === field}
                        onClick={() => update("field", field)}
                      >
                        {field}
                      </button>
                    ))}
                  </div>
                </>
              )}
              {step === 3 && (
                <>
                  <div className="onboarding-options three-columns">
                    {workplaces.map(([name, description]) => (
                      <button
                        type="button"
                        key={name}
                        aria-pressed={draft.workplace === name}
                        onClick={() => update("workplace", name)}
                      >
                        <Icon name="layers" size={20} />
                        <strong>{name}</strong>
                        <small>{description}</small>
                      </button>
                    ))}
                  </div>
                  {draft.workplace && draft.workplace !== "Independent" && (
                    <div className="onboarding-organisation">
                      <label htmlFor="onboarding-workplace-name">
                        Organisation name <span>(optional)</span>
                      </label>
                      <input
                        id="onboarding-workplace-name"
                        value={draft.workplaceName}
                        onChange={(e) =>
                          update("workplaceName", e.target.value)
                        }
                        maxLength={160}
                        autoComplete="organization"
                        placeholder="Your university, company or organisation"
                      />
                    </div>
                  )}
                </>
              )}
              {step === 4 && (
                <>
                  <label htmlFor="onboarding-topic">
                    Your first research question <span>(optional)</span>
                  </label>
                  <textarea
                    id="onboarding-topic"
                    value={draft.topic}
                    onChange={(e) => update("topic", e.target.value)}
                    rows={4}
                    maxLength={1000}
                    placeholder="What would you like to understand or decide?"
                    aria-describedby="onboarding-topic-note"
                  />
                  <p id="onboarding-topic-note" className="onboarding-note">
                    {draft.topic.length}/1000 characters. Leave blank to begin
                    with a fresh question.
                  </p>
                  <div className="onboarding-chips">
                    {suggestions.map((suggestion) => (
                      <button
                        type="button"
                        key={suggestion}
                        onClick={() => update("topic", suggestion)}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </>
              )}
              {step === 5 && (
                <>
                  <div className="onboarding-options depth-options">
                    {depths.map(([name, limit, description]) => (
                      <button
                        type="button"
                        key={name}
                        aria-pressed={draft.depth === name}
                        onClick={() => update("depth", name)}
                      >
                        <div>
                          <strong>{name}</strong>
                          {draft.depth === name && (
                            <Icon name="check" size={18} />
                          )}
                        </div>
                        <span>{description}</span>
                        <small>{limit}</small>
                      </button>
                    ))}
                  </div>
                  <p className="onboarding-note">
                    Simple evergreen explainers use up to two sources. Source
                    ceilings are maximums, not a promise of that many useful
                    sources.
                  </p>
                  <p className="onboarding-note">
                    No payment or subscription is selected here.
                  </p>
                </>
              )}
              {step === 6 && (
                <>
                  <dl className="onboarding-review">
                    {[
                      ["Role", draft.role, 1],
                      ["Field", draft.field, 2],
                      [
                        "Workplace",
                        draft.workplace === "Independent"
                          ? "Independent"
                          : [draft.workplace, draft.workplaceName]
                              .filter(Boolean)
                              .join(" · "),
                        3,
                      ],
                      [
                        "First question",
                        draft.topic || "Start with a fresh question",
                        4,
                      ],
                      ["Default depth", draft.depth, 5],
                    ].map(([label, value, index]) => (
                      <div key={label}>
                        <dt>{label}</dt>
                        <dd>{value}</dd>
                        <button
                          type="button"
                          onClick={() => setStep(Number(index))}
                          aria-label={`Edit ${label}`}
                        >
                          Edit
                        </button>
                      </div>
                    ))}
                  </dl>
                  <div className="onboarding-expectations">
                    <Icon name="eye" />
                    <div>
                      <strong>A research trail you can inspect.</strong>
                      <p>
                        Questions become collected sources, checked assertions
                        and a report. Exact passage matches and model reviews
                        are not factual certification. Your research begins only
                        when you press Start research.
                      </p>
                    </div>
                  </div>
                </>
              )}
            </fieldset>
          </section>
          {error && (
            <p className="onboarding-error" role="alert">
              {error}
            </p>
          )}
          <p className="onboarding-save-state" role="status" aria-live="polite">
            {busy ? "Saving your setup…" : saved}
          </p>
          <footer className="onboarding-actions">
            <button
              type="button"
              className="onboarding-back"
              disabled={busy || step === 1}
              onClick={() => void save("save", step - 1)}
            >
              Back
            </button>
            <button
              className="onboarding-continue"
              type="submit"
              disabled={
                busy ||
                !stepValid(step, draft) ||
                (step === 6 && !canComplete(draft))
              }
            >
              {busy ? "Saving…" : step === 6 ? "Open my workspace" : "Continue"}
              <Icon name="arrow" size={18} />
            </button>
          </footer>
          <p className="onboarding-privacy">
            Optional account preferences. Not permissions, pricing or a change
            to your research limits. Skip at any time.
          </p>
        </form>
      </main>
    </div>
  );
}
