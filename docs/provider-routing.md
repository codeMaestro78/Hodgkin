# Provider Routing

See [agents.md](./agents.md#provider-router) for the `provider_router`
node contract, and [reliability.md](./reliability.md) for circuit-breaker
behavior on provider failure.

## Principle

**Do not call every provider for every query.** That creates correlated
duplication, unnecessary cost, and more state to reconcile. Use a router,
then escalate only on low coverage or low confidence.

## Providers

| Provider | Capability | Production role |
|---|---|---|
| Serper | Fast real-time Google SERP and news discovery | Candidate URL discovery, freshness checks |
| Tavily | AI-oriented search, extraction, crawl, map, research | Dense content retrieval, domain-constrained search |
| Parallel | Long/multi-hop web research, structured enrichment | Escalation path for difficult tasks |
| Playwright | Deterministic browser automation | Local fallback for JS-heavy public pages |
| Browserbase | Managed remote browsers | Hosted browser fallback, authenticated sessions |

## Routing decision table

| Task shape | First choice | Escalation |
|---|---|---|
| Discover authoritative URLs | Serper Search | Tavily Search |
| Breaking or recent news | Serper News | Tavily with date and domain filters |
| Extract relevant passages from known URLs | Tavily Extract | Browser fallback |
| Search plus cleaned, token-dense context | Tavily Search (advanced) | Parallel Search |
| Multi-hop question requiring synthesis across many sources | Parallel Task | Custom LangGraph worker set |
| Entity list enrichment | Parallel Task Group / FindAll | Serper plus extraction workers |
| JS-rendered or interactive page unavailable to extractors | Playwright or Browserbase | Mark unavailable |
| Logged-in page explicitly authorized by user | Isolated Browserbase session | Human upload/export |

## Routing algorithm

1. **Deterministic rules first**, per the table above, keyed on task
   shape (discovery vs. extraction vs. multi-hop vs. freshness vs.
   rendering requirement).
2. **Jev resolves ambiguity** in a single batched call:
   - `Choice`: `serper | tavily | parallel | browser`
   - `Score`: expected research complexity
   - `Noul`: whether fresh news is required
   - `Noul`: whether multi-hop synthesis is required
   - `Noul`: whether known URLs must be rendered in a browser
3. **Code applies budget and permission constraints** last — this is the
   final decision, not Jev's output. Low-confidence routing falls back to
   Tavily or a deterministic rule, not another LLM loop.

## Cost and latency considerations

| Provider | Relative cost | Relative latency | Notes |
|---|---|---|---|
| Serper | Low | ~1-2s typical | Snippets only — fetch the source before citing |
| Tavily | Low-medium | Low-medium | Generated "answer" field can obscure provenance; keep result-level sources |
| Parallel | Medium-high | Higher (async task) | Use only after the routing gate; poll status cheaply, do not block a worker thread |
| Playwright | Medium (compute) | Medium-high | Expensive and brittle; sandbox, restrict domains, enforce timeouts |
| Browserbase | Higher (hosted) | Medium-high | Session management overhead; isolate per tenant, encrypt secrets |

## Freshness requirements

Tasks flagged as needing fresh news route to Serper News first, escalating
to Tavily with explicit date/domain filters. Freshness is a `Noul`
judgment from Jev, confirmed by the sub-question's `sourceClasses` hint
from the planner.

## Extraction requirements

Known-URL passage extraction prefers Tavily Extract (cleaned, structured
output) before falling back to a full browser render, which is reserved
for JS-heavy pages extractors cannot handle.

## Provider failures

Provider adapter errors are typed and caught at the adapter boundary (see
[reliability.md](./reliability.md)):

- Timeout → bounded retry with backoff → circuit-break → escalate to the
  next provider in the table, or mark the sub-question `failed` if no
  escalation path remains.
- Malformed/empty response → treated as low coverage, feeding into the
  reflector's gap analysis rather than silently succeeding.

## Request fingerprints

Every provider call carries a deterministic fingerprint (normalized query +
provider + params) used for:
- Idempotent retries (no duplicate billed calls on retry).
- Duplicate-query rejection within a run (`no repeated normalized query`
  budget rule — see [reflection.md](./reflection.md)).
- Cost/rate-limit accounting per tenant.

## Rate limits

Rate limiting is enforced via Redis (see [redis.md](./redis.md)) — a
global semaphore per provider, plus a per-tenant budget check against the
usage ledger in PostgreSQL (see [database.md](./database.md)).

## Provider endpoints (verified against current documentation at blueprint time)

| Provider | Endpoint |
|---|---|
| Tavily Search | `POST https://api.tavily.com/search` |
| Tavily Research | `POST https://api.tavily.com/research` |
| Serper Search | `POST https://google.serper.dev/search` |
| Serper News | `POST https://google.serper.dev/news` |
| TypeSafe AI System One (Jev) | `POST https://api.typesafe.ai/v1/systemone` |
| Parallel Task MCP | `https://task-mcp.parallel.ai/mcp` (Streamable HTTP) |

For Parallel REST Search and Task APIs, use the current official SDK
generated from its API specification rather than hard-coding beta paths.
Pin the SDK version and contract-test provider adapters — see
[testing.md](./testing.md).

`TODO: verify repository path` for the actual adapter implementations
(proposed: `services/research-api/providers/{serper,tavily,parallel,playwright,browserbase}.py`).
