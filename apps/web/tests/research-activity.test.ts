import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { ResearchActivity } from "../app/components/research-activity";

const occurredAt = "2026-10-16T10:00:00Z";

it("shows only the three most recent labeled records, newest first", () => {
  const html = renderToStaticMarkup(
    createElement(ResearchActivity, {
      status: "verifying",
      events: [
        { sequence: 1, label: "Old task", occurredAt },
        { sequence: 2, label: "Collected sources", occurredAt },
        { sequence: 3, label: null, occurredAt },
        { sequence: 4, label: "Checked quotes", occurredAt },
        { sequence: 5, label: "Review started", occurredAt },
      ],
    }),
  );
  expect(html).not.toContain("Old task");
  expect(html.match(/<li>/g)).toHaveLength(3);
  expect(html.indexOf("Review started")).toBeLessThan(
    html.indexOf("Checked quotes"),
  );
  expect(html.indexOf("Checked quotes")).toBeLessThan(
    html.indexOf("Collected sources"),
  );
});

it("treats recorded labels as text, never HTML instructions", () => {
  const html = renderToStaticMarkup(
    createElement(ResearchActivity, {
      status: "researching",
      events: [
        {
          sequence: 1,
          label: "<script>alert(1)</script>",
          occurredAt: "invalid",
        },
      ],
    }),
  );
  expect(html).not.toContain("<script>");
  expect(html).toContain("&lt;script&gt;");
  expect(html).toContain("Recorded</time>");
});

it("uses an honest empty state instead of inventing activity", () => {
  const html = renderToStaticMarkup(
    createElement(ResearchActivity, {
      status: "queued",
      events: [],
    }),
  );
  expect(html).toContain("Waiting for the first activity record.");
  expect(html).not.toContain("<time");
});
