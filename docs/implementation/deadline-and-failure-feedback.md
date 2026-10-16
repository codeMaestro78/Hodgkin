# Depth deadlines and visible failure feedback — 2026-10-14

## Reproduced causes

The supplied trace shows a Deep run with a two-minute active budget. Planning
and checkpoint work consumed 42,412 ms before approval; the next claim retained
that spend, leaving approximately 78 seconds for collection and publication.
Database statements commonly took hundreds of milliseconds. This is a workload
budget mismatch, not evidence that approval waiting was charged.

A second regression involved fresh parallel workers receiving overlapping URLs.
Pending extraction slots held by a sibling were incorrectly interpreted as a
crash-recovery receipt problem. The exact regression test failed with
`ProviderRecoveryNeededError: recovery-needed: extraction receipt missing` before
the fix. Both fully overlapping and mixed overlapping/new-URL tests now pass.

The frontend also used a queued fallback for terminal statuses, retained stale
approval feedback, put the failure below the scroll position, and unmounted the
report on approval refresh. Browser checks reproduce the case while the reader
is scrolled down and the snapshot response is deliberately blocked.

## Changes and bounds

- New API submissions use visible mode defaults: quick explanations 2 minutes,
  Focused 3, Balanced 5, Deep 10. The composer sends `maxWallClockMs` explicitly
  and explains that planning, collection and verification share the active budget.
  These are ceilings, not promises of completion time. Explicit lower deadlines
  are respected. Search/source, token, estimated-cost and reflection caps are unchanged.
- Existing persisted budgets and failed runs are not rewritten. For a timed-out
  run, the retry button displays the proposed limit and sends a bounded
  `maxWallClockMs` query parameter. A retry is a new run and may incur provider
  costs. Without this explicit override, the retry endpoint keeps the old budget.
- Fresh workers skip sibling-owned URLs while still processing newly admitted
  URLs. Recovery of a previously paid request still requires trustworthy receipts;
  ambiguous calls are not refunded or redispatched. Source admission ceilings,
  tenant predicates, locks and ledger accounting remain enforced.
- Dispatcher preload is one tenant-scoped run/job/budget join rather than three
  queries. Remaining active time now deducts dispatcher and graph preparation.
  `dispatcher.budget` records the limit and remaining milliseconds without prompts.
- Quiet SSE connections back off from one to five seconds; waiting approvals
  poll at five seconds. Replay pages still drain immediately, and persisted events
  remain the authoritative signal. This trades bounded idle update latency for
  lower database contention; it is not a production p95 latency claim.
- A status rail is outside the report/evidence scroll regions. Failed runs use
  an assertive accessible alert with a plain-language cause and a single visible
  retry action. Terminal events update it immediately before snapshot refresh.
  A stale nonterminal snapshot cannot overwrite a known terminal state.
- Approval refresh retains the mounted report and selected source. Header motion
  no longer repeats when a report arrives. Status colors and newly mounted report
  opacity use 180 ms transitions; reduced motion disables these transitions.
  Readable content is not shifted for decoration.

## Validation

Final local checks passed: 347 backend tests, 57 web tests, Ruff, Python and
TypeScript type checks, the production web build, and 35 browser checks (11
failure-specific plus 24 automation checks). `git diff --check` passed.

Local provider/artifact mocks cover deadlines, unchanged explicit caps, original
budget preservation on retry, overlapping-source concurrency, uncertain replay,
durable deadlines, cancellation and tenant isolation. Browser fixtures intercept
every API request: 11 failure-specific checks cover scrolled failure visibility,
stale snapshots, preserved DOM on approval, disclosed retry allowance, mobile
overflow and reduced motion, alongside the prior 24 automation checks.

No failed hosted run was reset, no hosted migration was required, and no paid
research was started for validation. Restart/update the API and frontend before
using the new behavior. The next live smoke test requires an explicit user-triggered
new attempt; old two-minute runs retain their original budget and evidence.

Further latency work should measure hosted pool wait, database RTT and dependency
time, and consider running the API near its database. Raising a deadline does
not by itself make research faster or guarantee that every run can finish.
