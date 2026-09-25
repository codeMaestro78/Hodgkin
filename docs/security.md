# Security

Authentication, authorization, tenancy, and secret-handling policy. See
[prompt-injection.md](./prompt-injection.md) for the dedicated policy on
untrusted web content, and [reliability.md](./reliability.md) for
failure-mode handling that overlaps with security (circuit breakers,
timeouts).

## Authentication

- The browser authenticates to the Next.js BFF via an HTTP-only session
  cookie (see [events-and-sse.md](./events-and-sse.md#transport) for why
  this matters specifically for the SSE endpoint, which cannot carry
  arbitrary headers via native `EventSource`).
- The BFF authenticates to the Python research API using its own
  service-to-service credential — `TODO: verify repository path` /
  `PROPOSED` for the exact mechanism (mTLS, signed internal JWT, etc.).

## Authorization

- Every API endpoint resolves the caller's `tenant_id`/`user_id` from the
  session and scopes the operation to it (see [api.md](./api.md)).
- Cross-tenant access attempts return `403`, not a filtered `200` — the
  distinction matters for not leaking existence of another tenant's data.

## Tenant isolation

- Every durable record carries a `tenant_id` (see
  [database.md](./database.md#tables-proposed-derived-from-the-blueprints-persistence-list)).
- Isolation is enforced at both the repository/query layer (explicit
  predicate on every query) and the database layer (row-level access
  policy or equivalent mandatory scoping) — defense in depth, not either/or.
- Provider API keys are stored **per tenant, encrypted**.
- Per-tenant rate and cost budgets are enforced against the usage ledger
  (see [database.md](./database.md), [reflection.md](./reflection.md#hard-limits)).
- Browser automation uses a **separate browser context per run** — never
  shared across tenants or even across runs within a tenant.

## API security

- All request/response bodies are schema-validated (Zod/Pydantic) at the
  boundary — see [state-management.md](./state-management.md).
- Idempotency keys prevent duplicate billed operations on retry (see
  [api.md](./api.md), [reliability.md](./reliability.md#idempotency)).
- Rate limits are enforced per tenant (via Redis — see
  [redis.md](./redis.md)) in addition to per-provider global limits.

## Provider credentials

- Provider API keys (Serper, Tavily, Parallel, Browserbase, Jev) are
  encrypted at rest, scoped per tenant where the provider relationship is
  tenant-specific, and never logged in full.
- Credentials are injected into adapter calls server-side only — never
  sent to the browser, never exposed to page content fetched during
  research.

## Browser isolation

- Each run gets an isolated browser context (Playwright local, or a
  Browserbase managed session).
- Protocol and IP allowlisting blocks local/private IP ranges (SSRF
  protection) — see [prompt-injection.md](./prompt-injection.md#mitigations).
- File downloads are blocked by default; arbitrary code execution in the
  browser context is disabled.
- Authenticated or side-effecting browser actions (e.g., a logged-in
  session explicitly authorized by the user) require explicit human
  approval before execution — implemented as a LangGraph interrupt (see
  [langgraph.md](./langgraph.md#interrupts)).

## Secret management

- Secrets (provider keys, service credentials, signing keys) are never
  committed to the repository and never exposed to LLM tool-call surfaces
  reachable from browsed page content.
- `PROPOSED` secret store (e.g., a managed secrets manager) —
  `TODO: verify repository path` for the actual mechanism.

## Audit logs

- Source access, human-approval decisions, and data exports are audit
  logged, tenant-scoped, and retained per the retention policy in
  [artifact-storage.md](./artifact-storage.md#retention).

## Rate limits and cost controls

- Enforced at two layers: Redis-backed fast-path limiting (see
  [redis.md](./redis.md)) and the durable usage ledger in PostgreSQL,
  which is the authoritative check for budget enforcement (see
  [reflection.md](./reflection.md#hard-limits)).

## Source access

- The frontend and API never expose full raw artifacts — only metadata
  and the specific verified excerpt tied to a citation (see
  [artifact-storage.md](./artifact-storage.md#access-control)).
