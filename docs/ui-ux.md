# UI / UX Specification

The interface should feel like a **professional research operations
console**, not a chatbot. See [frontend.md](./frontend.md) for the
implementing component tree.

## Product concept

The user should simultaneously understand:
- What the system is doing
- Which agents are active
- What evidence has been found
- What remains uncertain
- How much time and budget have been used
- How each final claim maps to sources

## Desktop layout — three-region shell

| Region | Width | Contents |
|---|---|---|
| Left rail | 260–300 px | Project navigation, saved runs, filters, agent status, run history |
| Center workspace | Flexible | Research brief, streaming report, outline, claim-level citation markers |
| Right intelligence rail | 340–400 px | Execution tree, live events, sources, gaps, contradictions, budgets |

The right rail switches among **Agents**, **Evidence**, **Sources**, and
**Logs** tabs. Users should not be forced to watch raw logs to understand
progress — the default view is a synthesized status, not a terminal.

## Visual language

| Aspect | Spec |
|---|---|
| Background | Near-black graphite, not pure black |
| Surfaces | Restrained elevated panels with clear borders, not excessive glass blur |
| Status colors | Blue = planning, Violet = research, Amber = verification, Cyan = writing, Green = complete, Red = failure |
| Typography | Readable sans-serif for report content; monospace only for IDs, events, and metrics |
| Motion | Subtle state transitions and node pulses; disable decorative looping animation during long runs |
| Density | High but hierarchical — provide **Focus report** and **Inspect execution** modes |

## Agent execution tree

A vertical, expandable tree showing per node:
- Node name and worker role
- State: running, queued, complete, retrying, or failed
- Provider icon
- Elapsed time
- Sources found
- Verified claims
- Token and cost estimate

**Never expose private chain-of-thought.** Show concise, generated
progress summaries and tool metadata instead — this mirrors the backend
rule that raw model reasoning is not part of the durable event contract
(see [events-and-sse.md](./events-and-sse.md)).

## Citation interaction

Clicking a citation marker (`[12]`) opens a side popover with:
- Source title, publisher, URL, and date
- The exact supporting passage
- Verification status
- Source-quality indicator
- Other claims supported by the same source
- An "Open source" action

## Source disagreement

If sources disagree on a proposition, show **both** passages in a
side-by-side comparison view — never silently hide the conflict or pick a
"winner" for the user. This surfaces the contradiction ledger from
[evidence-system.md](./evidence-system.md#claim-ledger-and-contradiction-ledger).

## Responsive behavior

| Breakpoint | Behavior |
|---|---|
| Large monitor | Full three-region shell |
| Laptop | Collapsible left rail; right rail narrows to 320 px; report remains dominant |
| Tablet | Center workspace + right rail as a drawer |
| Mobile | Report-first single column; agents/sources in bottom sheets; timeline becomes a compact progress stepper |

## Modes

- **Focus report** — center workspace maximized, minimal chrome, for
  reading the synthesized answer.
- **Inspect execution** — intelligence rail and bottom timeline
  prioritized, for understanding *how* the answer was produced.

Both modes read from the same event-driven state (see
[frontend.md](./frontend.md#sse-integration)) — switching modes never
triggers a new fetch of already-streamed data.
