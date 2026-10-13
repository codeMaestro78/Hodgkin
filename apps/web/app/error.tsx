"use client";
import { Brand, Icon } from "./components/ui";
export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="fallback-page">
      <Brand />
      <div>
        <h1>Let’s try that again.</h1>
        <p>
          This page couldn’t be opened. Try again or return to the research
          workspace.
        </p>
        <button onClick={reset} className="action">
          Try again
          <Icon name="arrow" size={18} />
        </button>
      </div>
    </main>
  );
}
