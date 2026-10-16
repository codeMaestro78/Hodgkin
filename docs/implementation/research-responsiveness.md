# Research responsiveness — 2026-10-16

## Reproduced symptoms and changes

The isolated browser fixture drives the actual composer and research page, with
all API calls intercepted and no paid provider requests:

```sh
playwright-cli -s=latency-check run-code --filename=apps/web/tests/browser-fixture/responsiveness-check.js
```

Run the existing Vite `automation-vite.config.mjs` fixture on loopback port 3102
first. Use a separate browser session; do not attach real authenticated sessions.

Before the fix, a verified account could not start research while optional
onboarding defaults were held pending. The composer now becomes ready immediately
after verified identity and account-scoped draft hydration. Late defaults still
respect edited fields and the submission freeze; account-switch guards remain.

Before the fix, a `node.started` notification waited behind an existing routine
source timer: the stage did not update within the fixture's 650 ms threshold.
Stage and terminal events now preempt routine source waits. One scheduler keeps
the earliest deadline; source bursts still coalesce at 1.5 seconds. Snapshot
fetches remain single-flight with a trailing refresh. Route cleanup cancels work.
The same synthetic check observed stage feedback in 15–26 ms after the fix; this
is not a production latency percentile or a model/provider speed measurement.

## Activity and motion

The waiting area shows up to three labeled persisted actions and the current
recorded stage, replacing the generic graphic/skeleton. It shows no simulated
thoughts, fabricated completion percentage or unpublished report prose. Actual
sources and methodology remain inspectable.

New activity/evidence rows use an opacity-only 180 ms entrance using the existing
easing token; stage markers transition their state colors. Reduced-motion users
receive no new entrance motion. Existing rows do not restart their animation on
every snapshot or keystroke. No animation library or dependency was added.

## Measurement without log noise

Research BFF responses expose numeric `Server-Timing` fields:

- `auth`: verified authentication/session processing.
- `upstream_headers`: backend time until response headers arrive.
- `proxy`: BFF processing to response construction (not network transfer time).

For SSE these timings cover connection establishment, not the stream lifetime.
The fields contain no identities, credentials, questions or upstream URLs.

## Verification and remaining limits

Nine browser checks cover optional-default readiness, stage preemption, source
burst coalescing, recorded activity, mobile overflow, reduced motion and immediate
terminal failure feedback/stream closure. The previous 36 workflow checks also
pass, including in-flight account switches and draft preservation. Unit tests
exercise scheduler preemption, cancellation and avoidance of duplicate timers.
The web suite passes 88 tests; contracts pass 30 tests and all 38 generated JSON
Schema documents validate. Type/lint checks and the production build pass.

This frontend slice did not claim faster research completion. At that point, backend SSE
polls the durable outbox with a 1–5 second active idle backoff (5 seconds while
awaiting approval). A future wake-up mechanism must publish only after commit,
retain PostgreSQL cursor replay, tolerate missed wake-ups, and remain correct
across replicas. Increasing database polling frequency blindly is not this fix.
The subsequent [commit wake-up implementation](event-delivery-latency.md) now
preempts these waits when hints arrive, retaining polling for missed hints.
Queue wait, database timings and provider/model durations still need a bounded
live workload before making end-to-end latency claims. No research budgets,
verification rules, migrations or hosted runtime settings changed in this slice.
