import { ActionLink, Brand } from "./components/ui";
export default function NotFound() {
  return (
    <main className="fallback-page">
      <Brand />
      <div>
        <span className="fallback-code">404</span>
        <h1>This trail ends here.</h1>
        <p>
          We couldn’t find that page. Start a new question or return to the
          workspace.
        </p>
        <ActionLink href="/research">Open workspace</ActionLink>
      </div>
    </main>
  );
}
