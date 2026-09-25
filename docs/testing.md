# Testing Strategy

See [agent.md](./agent.md#12-testing-rules) for the enforceable summary an
AI coding agent must follow; this document expands on it.

## Test layers

| Layer | Scope | Mocked | Real |
|---|---|---|---|
| Unit tests | Pure functions (canonicalization, span matching, budget math) | N/A | N/A — no I/O |
| Schema tests | Zod and Pydantic definitions stay in sync; contract fixtures round-trip | N/A | Both schema libraries |
| Node tests | Single LangGraph node's input→output contract | LLM calls (fixed responses), provider adapters | Schema validation |
| Graph tests | Multi-node routing (`dispatch_workers`, `route_after_reflection`) | Nodes stubbed to fixed outputs | Graph wiring itself |
| Provider adapter tests | One adapter (Serper/Tavily/Parallel/Playwright/Browserbase) | HTTP layer (recorded fixtures/VCR-style) | Adapter parsing/normalization logic |
| Integration tests | Several real components together (e.g., API → LangGraph → Postgres, against a test DB) | External providers, Jev | Internal services, real DB |
| SSE tests | Event persistence, publication, replay, `Last-Event-ID` handling | N/A | Real event store (test instance) |
| Reducer tests | Fan-in merge-by-ID logic, including out-of-order/duplicate/conflicting inputs | N/A | N/A — pure functions over fixtures |
| Security tests | Tenant isolation (cross-tenant query attempts return 403/empty), secret handling | External providers | Real authz layer |
| Prompt injection tests | Retrieved content containing instruction-like text does not alter node behavior | LLM calls may be mocked or real, depending on what's being tested | See [prompt-injection.md](./prompt-injection.md) |
| Failure injection | Provider timeouts, worker crashes, malformed LLM output, mid-run cancellation | Providers/LLM (forced-failure fixtures) | Graph/reliability logic |
| Load testing | Concurrency limits, provider semaphores, SSE fan-out under many connections | Providers (rate-limited stubs) | Real coordination layer (Redis, semaphores) |
| Evaluation tests | Full benchmark run against the 60-question set | Nothing (or a fixed benchmark snapshot for CI) | Full pipeline |

## What to mock vs. test against real services

- **Always mock in CI**: Serper, Tavily, Parallel, Jev, and any billed
  external API — use recorded fixtures so tests are deterministic and
  free.
- **Test against real services in a separate, gated suite**: provider
  contract tests that verify the pinned SDK/API version still matches
  reality (see [provider-routing.md](./provider-routing.md#provider-endpoints-verified-against-current-documentation-at-blueprint-time)) —
  run on a schedule, not on every PR, to avoid flaky/costly CI.
- **Always real in integration tests**: PostgreSQL and Redis, against
  ephemeral test instances — these are cheap, fast, and catch real
  serialization/constraint bugs that mocks would hide.
- **Always mock for prompt-injection tests**: use a fixed, adversarial
  fixture page rather than fetching a real page, so the test is
  deterministic and doesn't depend on external content staying malicious
  (or staying online) over time.

## Reducer tests specifically

Reducer tests must cover, at minimum:
- Two branches returning the same entity ID with different content
  (conflict — last-write-wins by `updatedAt`, logged).
- Out-of-order arrival (branch B's result processed before branch A's).
- A branch returning zero results (partial fan-in).
- Replaying the same `WorkerResult` twice (idempotent — no duplication).

## Failure injection specifically

At minimum, inject:
- A provider timeout mid-run → confirm circuit breaker + escalation path.
- A worker crash (killed process) → confirm resume-from-checkpoint, not
  duplicate work.
- Malformed structured-output from an LLM call → confirm the
  retry-once-then-fail-safely behavior for `planner`/`distiller`/`writer`/
  `reflector`.
- Mid-run cancellation → confirm idempotent cancel and no corrupted
  partial evidence.

## CI expectations (proposed)

`PROPOSED` — no CI configuration confirmed against a real repository.
Reasonable baseline: unit + schema + node + reducer + security tests on
every PR; graph + integration + SSE tests on every PR against ephemeral
Postgres/Redis; provider contract tests and the 20-question evaluation
subset on a schedule (nightly) rather than per-PR, to control cost and
flakiness; the full 60-question benchmark on release branches.

`TODO: verify repository path` for actual test locations (proposed:
`services/research-api/tests/`, `apps/web/tests/`, `packages/contracts/tests/`).
