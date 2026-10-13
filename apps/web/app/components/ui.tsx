import Link from "next/link";
import type { ReactNode } from "react";

export function Icon({
  name,
  size = 20,
}: {
  name:
    | "arrow"
    | "plus"
    | "search"
    | "book"
    | "layers"
    | "chevron"
    | "close"
    | "menu"
    | "external"
    | "check"
    | "copy"
    | "download"
    | "eye";
  size?: number;
}) {
  const paths = {
    arrow: "M4 12h16m-6-6 6 6-6 6",
    plus: "M12 5v14M5 12h14",
    search: "m16 16 4 4M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
    book: "M4 4h6l2 2 2-2h6v16h-6l-2 2-2-2H4V4Zm8 2v16",
    layers: "m12 3 10 6-10 6L2 9l10-6ZM2 13l10 6 10-6M2 17l10 6 10-6",
    chevron: "m9 5 7 7-7 7",
    close: "m6 6 12 12M6 18 18 6",
    menu: "M4 8h16M4 16h16",
    external: "M14 3h7v7M21 3 10 14M10 3H3v18h18v-7",
    check: "m5 12 4 4L19 6",
    copy: "M9 9h12v12H9V9ZM15 9V3H3v12h6",
    download: "M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4",
    eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}

export function Brand({ light = false }: { light?: boolean }) {
  return (
    <Link
      href="/"
      className={`brand-lockup${light ? " brand-light" : ""}`}
      aria-label="HogsKin home"
    >
      <span className="brand-symbol" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
      HogsKin<span className="brand-period">.</span>
    </Link>
  );
}

export function ActionLink({
  href,
  children,
  secondary = false,
}: {
  href: string;
  children: ReactNode;
  secondary?: boolean;
}) {
  return (
    <Link href={href} className={secondary ? "action secondary" : "action"}>
      {children}
      <span className="action-icon">
        <Icon name="arrow" size={17} />
      </span>
    </Link>
  );
}

export function Status({ status }: { status: string }) {
  const label = status.replaceAll("_", " ");
  return (
    <span className={`status-badge status-${status}`}>
      <span aria-hidden="true" />
      {label}
    </span>
  );
}

export function domain(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "Web source";
  }
}

export function safeUrl(url: string) {
  try {
    const value = new URL(url);
    return ["https:", "http:"].includes(value.protocol)
      ? value.href
      : undefined;
  } catch {
    return undefined;
  }
}

export function dateLabel(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Recently"
    : new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
      }).format(date);
}
