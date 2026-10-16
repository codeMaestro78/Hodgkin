import Link from "next/link";
import { Brand } from "../ui";

const LINKS = [
  { href: "/#how", label: "How it works", key: "how" },
  { href: "/#verify", label: "Evidence", key: "verify" },
  { href: "/#workspace", label: "Workspace", key: "workspace" },
  { href: "/pricing", label: "Pricing", key: "pricing" },
  { href: "/#questions", label: "Questions", key: "questions" },
] as const;

export function SiteNav({ active }: { active?: "pricing" }) {
  return (
    <header className="lp-nav">
      <div className="lp-nav-inner">
        <div>
          <Brand />
        </div>
        <nav aria-label="Main navigation">
          {LINKS.map((link) => (
            <Link
              key={link.key}
              href={link.href}
              aria-current={active === link.key ? "page" : undefined}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="lp-nav-end">
          <Link href="/login" className="lp-nav-login">
            Log in
          </Link>
          <Link
            href="/research"
            className="lp-btn lp-btn-ink lp-btn-small"
            data-magnetic
          >
            Start research
          </Link>
        </div>
      </div>
      <span className="lp-progress" aria-hidden="true" />
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="lp-footer">
      <div className="lp-footer-brand">
        <Brand />
        <p>Curiosity, with a paper trail.</p>
      </div>
      <nav aria-label="Product">
        <h2>Product</h2>
        <Link href="/research">New research</Link>
        <Link href="/research/library">Library</Link>
        <Link href="/research/compare">Compare runs</Link>
        <Link href="/research/automation">Automation</Link>
        <Link href="/pricing">Pricing</Link>
      </nav>
      <nav aria-label="Account">
        <h2>Account</h2>
        <Link href="/login">Log in</Link>
        <Link href="/signup">Create account</Link>
        <Link href="/forgot-password">Reset password</Link>
      </nav>
    </footer>
  );
}
