"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import type { FormEvent } from "react";
import { Brand, Icon } from "./ui";
import { useEntrance } from "./workspace-motion";
export function AuthPage({
  mode,
  configured,
  next = "/research",
  initialNotice = "",
}: {
  mode: "login" | "signup" | "forgot" | "reset";
  configured: boolean;
  next?: string;
  initialNotice?: string;
}) {
  const signup = mode === "signup";
  const forgot = mode === "forgot";
  const reset = mode === "reset";
  const [showPassword, setShowPassword] = useState(false);
  const [notice, setNotice] = useState(initialNotice);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const scope = useRef<HTMLElement>(null);
  useEntrance(
    scope,
    mode,
    ".auth-story-copy, .auth-form-heading, .account-form, .auth-local",
  );
  useEntrance(scope, notice, ".form-feedback");
  async function perform(action: string, fields: Record<string, string> = {}) {
    if (busy) return;
    setBusy(action);
    setNotice("");
    setFailed(false);
    try {
      const response = await fetch(`/api/auth/${action}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...fields, next }),
      });
      const result = (await response.json()) as {
        error?: string;
        message?: string;
        redirect?: string;
      };
      if (!response.ok)
        throw new Error(
          result.error ?? "Account request failed. Please try again.",
        );
      if (result.redirect) {
        window.location.assign(result.redirect);
        return;
      }
      setNotice(result.message ?? "Account request completed.");
    } catch (error) {
      setFailed(true);
      setNotice(
        error instanceof Error
          ? error.message
          : "The account service is unavailable.",
      );
    }
    setBusy(null);
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const fields = Object.fromEntries(
      [...data].filter(
        (entry): entry is [string, string] => typeof entry[1] === "string",
      ),
    );
    if (reset && fields.password !== fields.confirmPassword) {
      setFailed(true);
      setNotice("The passwords don’t match.");
      return;
    }
    void perform(mode, fields);
  }
  return (
    <main ref={scope} className={`auth-page ${signup ? "auth-signup" : ""}`}>
      <section className="auth-story">
        <Brand light />
        <div className="auth-story-copy">
          <span className="auth-story-line" />
          <h2>
            {signup ? (
              <>
                A place for your
                <br />
                next perspective.
              </>
            ) : (
              <>
                Pick up where
                <br />
                curiosity left off.
              </>
            )}
          </h2>
          <p>
            Your questions, the evidence behind them, and the ideas that come
            next. One considered workspace.
          </p>
        </div>
        <p className="auth-story-foot">
          Research the live web. Keep the trail.
        </p>
      </section>
      <section className="auth-form-area">
        <Link href="/" className="auth-back">
          <Icon name="arrow" size={16} />
          Back to home
        </Link>
        <div className="auth-form-wrap">
          <div className="auth-form-heading">
            <span className="auth-emblem">
              <Icon name={signup ? "plus" : "layers"} size={24} />
            </span>
            <h1>
              {forgot
                ? "Find your way back."
                : reset
                  ? "A fresh start."
                  : signup
                    ? "Make room for curiosity."
                    : "Welcome back."}
            </h1>
            <p>
              {forgot
                ? "We’ll send you a secure password-reset link."
                : reset
                  ? "Choose a new password for your account."
                  : signup
                    ? "Create a space for the questions worth pursuing."
                    : "Your next perspective starts here."}
            </p>
          </div>
          {!forgot && !reset && (
            <>
              <button
                type="button"
                className="google-auth"
                disabled={!configured || Boolean(busy)}
                onClick={() => void perform("google")}
              >
                <svg
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                  width="18"
                  height="18"
                >
                  <path
                    fill="#4285F4"
                    d="M21.6 12.23c0-.71-.06-1.39-.18-2.05H12v3.88h5.38a4.61 4.61 0 0 1-2 3.02v2.51h3.24c1.9-1.75 2.98-4.33 2.98-7.36Z"
                  />
                  <path
                    fill="#34A853"
                    d="M12 22c2.7 0 4.96-.9 6.62-2.41l-3.24-2.51c-.9.6-2.05.97-3.38.97-2.6 0-4.8-1.76-5.59-4.12H3.07v2.59A10 10 0 0 0 12 22Z"
                  />
                  <path
                    fill="#FBBC05"
                    d="M6.41 13.93a6 6 0 0 1 0-3.86V7.48H3.07a10 10 0 0 0 0 9.04l3.34-2.59Z"
                  />
                  <path
                    fill="#EA4335"
                    d="M12 5.95c1.47 0 2.79.5 3.82 1.49l2.87-2.87A9.6 9.6 0 0 0 12 2a10 10 0 0 0-8.93 5.48l3.34 2.59C7.2 7.71 9.4 5.95 12 5.95Z"
                  />
                </svg>
                {busy === "google"
                  ? "Connecting to Google…"
                  : "Continue with Google"}
              </button>
              <div className="auth-divider">
                <span>or use email</span>
              </div>
            </>
          )}
          <form onSubmit={submit} className="account-form">
            {signup && (
              <label>
                Full name
                <input
                  name="name"
                  autoComplete="name"
                  placeholder="Your name"
                  required
                  maxLength={120}
                />
              </label>
            )}
            {!reset && (
              <label>
                Email address
                <input
                  name="email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@example.com"
                  required
                  maxLength={254}
                />
              </label>
            )}
            {!forgot && (
              <label>
                {reset ? "New password" : "Password"}
                <span className="password-field">
                  <input
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete={
                      signup || reset ? "new-password" : "current-password"
                    }
                    placeholder={
                      signup || reset
                        ? "At least 8 characters"
                        : "Enter your password"
                    }
                    minLength={signup || reset ? 8 : undefined}
                    maxLength={128}
                    required
                  />
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => setShowPassword(!showPassword)}
                    aria-label={
                      showPassword ? "Hide password" : "Show password"
                    }
                    aria-pressed={showPassword}
                  >
                    <Icon name="eye" size={18} />
                  </button>
                </span>
              </label>
            )}
            {reset && (
              <label>
                Confirm new password
                <input
                  name="confirmPassword"
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  maxLength={128}
                  required
                />
              </label>
            )}
            {mode === "login" && (
              <Link className="auth-forgot" href="/forgot-password">
                Forgot password?
              </Link>
            )}
            <button
              className="action auth-submit"
              type="submit"
              disabled={!configured || Boolean(busy)}
            >
              {busy && busy !== "google"
                ? "Please wait…"
                : forgot
                  ? "Send reset link"
                  : reset
                    ? "Update password"
                    : signup
                      ? "Create account"
                      : "Log in"}
              <span className="action-icon">
                {busy ? (
                  <span className="motion-spinner" aria-hidden="true" />
                ) : (
                  <Icon name="arrow" size={17} />
                )}
              </span>
            </button>
            {notice && (
              <p className="form-feedback" role={failed ? "alert" : "status"}>
                {notice}
              </p>
            )}
          </form>
          <p className="auth-switch">
            {signup || forgot || reset
              ? "Already have an account?"
              : "New to HogsKin?"}{" "}
            <Link href={signup || forgot || reset ? "/login" : "/signup"}>
              {signup || forgot || reset ? "Log in" : "Create an account"}
            </Link>
          </p>
          <div className="auth-local">
            <span>
              {configured ? "Your private workspace" : "Setup required"}
            </span>
            <p>
              {configured
                ? "Sign in securely with Supabase. Your research history is private to your account."
                : "Supabase Auth must be configured before account access is available."}
            </p>
          </div>
        </div>
        <span className="auth-bottom-note">
          A clearer answer. A traceable path.
        </span>
      </section>
    </main>
  );
}
