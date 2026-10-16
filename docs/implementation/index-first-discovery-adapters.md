# Index-first discovery: first adapter and durable receipt contract

Updated 2026-10-16. First slice: Serper Search behind
SERPER_DISCOVERY_ENABLED=false. OpenAlex, Semantic Scholar, Serper News, global
breakers and synthesis sharding remain future work.

## 1. Invariants

- Snippets and candidate metadata are untrusted discovery data, never evidence.
- Only extracted, preserved text enters Source and exact/semantic citation checks.
- Every discovery/extraction operation reserves the existing call/cost quotas.
  Cheaper discovery does not increase source or operation ceilings.
- Ambiguous dispatches retain reservations; timeout is not nonexecution proof.
- No network wait holds an admission/reservation database transaction.
- Existing private artifacts, ProviderCall, reservations, ExtractionSlot and
  checkpoints suffice for this bounded slice; no new table/migration is required.

## 2. Adapter contract and request identity

SerperAdapter exposes search_request, search and aclose. It uses ProviderRequest
with an explicit Serper request schema version, not Tavily's default version.

Database and telemetry use provider=serper, operation=search. Fingerprints use
the namespace serper:search:v1 plus canonical validated request parameters.
Existing Tavily identities stay unchanged. Response extras never enter hashes.

- Strip and validate queries: nonempty, at most 1000 characters.
- Clamp max_results to 1–10. Future offsets need separate validation; do not
  describe the same parameter as both clamped and rejected.
- Fingerprint domain filters and shortlist policy parameters; do not send an
  unsupported domain parameter to Serper.
- POST only to https://google.serper.dev/search with X-API-KEY and JSON. Retrieve
  at most ten candidates. Keys never enter payloads, fingerprints or logs.
- Finite timeout/attempt bounds; close only adapter-owned clients.
- Policy/schema version changes require a new request identity.

## 3. Tolerant parsing and deterministic shortlist

Require an object envelope with an organic list. Invalid envelopes consume the
policy reservation. Drop malformed individual entries, not the entire batch.
Pydantic extra=allow retains unknown fields; it does not ignore them.

For at most ten items: validate/canonicalize HTTP(S) URLs, reject credentials,
bound title/snippet lengths, preserve provider order, canonical-deduplicate,
then domain-filter by exact host or genuine subdomain. Select the first
max_results under the versioned serper-order-v1 policy.

The normalized receipt stores discovery_candidates (canonical URL, title,
snippet and rank), shortlist_policy and selected results. Selected results have
empty content: Tavily Extract alone supplies evidence. This policy is neither
semantic ranking nor source-independence certification.

## 4. Persistence, replay and crash boundaries

| Durable record | Responsibility |
| --- | --- |
| RuntimeJob graph version | Pin Serper at enqueue as research-v5-serper; old binaries reject it instead of switching providers |
| Initial graph checkpoint | Preserve discovery_provider across pauses/recovery; legacy missing value means Tavily |
| Reservation | Tenant/run/provider/operation/fingerprint/attempt identity, quota state |
| ProviderCall | Schema versions, outcome, response-artifact reference |
| Private content-addressed receipt | Candidate catalogue and exact selected shortlist |
| ExtractionSlot | Unique run/URL admission, original extraction reservation and quota state |
| Source/Citation | Extracted artifacts and publication checks, never snippets |

Flow:

1. Commit pending ProviderCall/reservation before discovery dispatch.
2. Dispatch outside the transaction; settle policy usage regardless of subsequent
   storage failure. Successful calls are not refunded for artifact failures.
3. Store candidate/shortlist JSON privately; bind its digest reference.
4. Read through the existing tenant/run/hash-checked replay boundary.
   Do not extract until the Serper shortlist receipt is durable and readable.
5. Use existing serialized extraction admission, reservations and source ceilings.

Recovery:

- Successful trusted receipt: reuse exact candidate order/shortlist, no search,
  re-ranking or new charge. Extraction recovery reconstructs original URLs and
  verifies fingerprints/receipts.
- Missing/corrupt/cross-scope receipt or unresolved call: recovery-needed;
  never re-search or refund speculatively.
- Crash between settlement and artifact binding: consumed usage remains.
  Operator repair may be needed; this is not guaranteed completion through
  every storage outage.
- Enqueued job version and saved graph route override later flag changes. Missing Serper credentials
  fail clearly for pinned runs, rather than switching providers.
- Old Tavily receipts and fingerprints remain unchanged.

Artifacts follow existing tenant access, retention and deletion boundaries.
A future searchable candidate table needs explicit RLS/grants, deletion and
migration tests; it is not needed merely to retain a bounded receipt.

## 5. Attempt-aware accounting

One transport retry owner, with the caller's cancellation/fencing gate before
each attempt. Never multiply retries with an outer SDK wrapper.

| History | Terminal outcome |
| --- | --- |
| No HTTP dispatch, or only proven connect/pool failures | released |
| Successful HTTP but invalid JSON/envelope | consumed estimate, no evidence |
| Dispatched timeout, write/read failure, in-flight cancellation, 5xx | uncertain; do not redispatch automatically |
| 429 | Bounded retry permitted; preserve uncertainty until success |
| Cancellation/connect failure after a prior 429 | uncertain, not refunded |
| 400/401/403/404/422 without previous uncertainty | released under explicit rejection policy |

Retry-After handles finite seconds and HTTP dates; cap through
DISCOVERY_RETRY_AFTER_MAX_SECONDS. Invalid/missing values use existing jitter.
Sleep cancellation must retain prior-attempt uncertainty. A retryable 429 is not
proof of no vendor usage; exact transport-attempt billing requires a provider
receipt contract.

SERPER_SEARCH_POLICY_COST is a named $0.001 policy estimate, not verified current
pricing. Search and extraction each consume one logical call quota. Estimated
usage is not an invoice. No fourfold saving is established.

This slice does not claim an existing global Redis limiter or circuit breaker.
Graph fan-out remains bounded; cross-replica rate coordination needs separate
validation before broad enablement.

## 6. Flag and rollout

- Default Tavily Search/Extract; no Serper traffic while disabled.
- Newly enqueued jobs with SERPER_DISCOVERY_ENABLED=true pin Serper; configure
  SERPER_API_KEY privately. Tavily Extract remains required.
- Old checkpoints without discovery_provider stay Tavily.
- Both routes retain mode ceilings and evidence/accounting rules.
- Disable for newly enqueued jobs to roll back; retain support/key for pinned Serper jobs.
  Do not roll those jobs back to an old binary: it rejects their graph version.
- Hosted enablement is not implied by passing fixture tests.

## 7. Academic adapters: future corrected contracts

OpenAlex should support api_key and current budget/usage metadata. A free
allowance is not unlimited/unmetered access. Article retrieval uses a readable
best_oa_location landing_page_url/pdf_url, then other work locations, then DOI.
primary_location.source is a journal/repository object, not an article URL.
Keep landing pages distinct from downloadable PDFs.

Semantic Scholar must request every field it consumes, including citationCount
when ranking uses it, and specify auth/rate behavior. Normalize DOI values, not
arbitrary case-sensitive IDs/URLs. Citation count is not independence or relevance.

Official references checked 2026-10-16:

- [Serper](https://serper.dev/)
- [OpenAlex authentication](https://help.openalex.org/api/authentication/)
- [OpenAlex locations](https://help.openalex.org/data/locations/)
- [Semantic Scholar Graph API](https://api.semanticscholar.org/api-docs/)

## 8. Acceptance and matched measurement

- MockTransport: headers/body/fingerprint, canonical dedup/domain filtering,
  malformed items/envelopes, bounded retries and cancellation histories.
- Local PostgreSQL: durable shortlist replay without redispatch, missing artifact
  blocks extraction without refund, tenant isolation, source ceilings.
- Reproduce concurrency claims before changing locks or pool sizes.
- Matched offline fixtures: same question, extracted evidence, writer candidates
  and verification decisions. Assert no snippet citations and consistent quotas.
  Fixture timing is not provider latency; fixtures cannot establish answer quality.
- Live comparison needs configured Serper credentials and explicit bounded paid
  authorization. Hold model/mode/requirements fixed; measure total/first-source
  time, verified findings, addressed requirements/questions, distinct hosts and
  publishers, and estimated cost. Host/publisher counts do not establish source
  independence. Separate errors, cold/warm runs and human approval waits. Two
  runs are not p95.

### First local matched Focused pair (2026-10-16)

One pair ran against a fresh local database migrated through `0011`, with the
same question, requirements, six-operation budget, 180-second wall limit, and
persisted model routes (`openai/gpt-6-luna`). Tavily completed; Serper reached
the synthesizer and failed with `graph_execution_failed`. The exact model error
was not persisted, so its cause remains unconfirmed.

| Route | Outcome | Time to first source | Total until terminal | Sources / distinct hosts | Verified findings | Requirement / question coverage | Estimated cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Tavily | Completed, partial | 16.8s | 50.5s | 5 / 5 | 9 | 2/3 / 2/3 | $0.050594 |
| Serper | Failed during synthesis | 10.1s | 41.3s | 4 / 4 | unavailable | unavailable | $0.027286 |

Both used six provider operations. Tavily's five sources had no publisher names;
Serper's four sources had none. Distinct hosts are only a diversity signal, not
proof of independent evidence. The Serper terminal time is a failed-run duration,
not a comparable completed-answer latency. This pair shows a faster first-source
observation for Serper in this one workload, but cannot establish a speedup or
answer-quality parity. The Serper run preserved its four collected sources.

Opt-in pair, from services/research-api with explicitly configured loopback test
persistence and live credentials (only after paid approval):

    uv run python scripts/benchmark_focused.py --confirm-paid --runs 1 --compare-discovery --question "Compare Kafka durability and Temporal recovery"

Feed its JSONL output to scripts/compare_discovery.py via standard input. Preserve
the benchmark JSONL (including a failed arm) for diagnosis. Both
arms include a workload fingerprint binding question, Focused mode, requirements,
budgets and actual pinned model routes; the comparator rejects mismatches,
duplicate routes and missing measurements. It reports partial results for failed
arms, latency, evidence, coverage, source diversity and estimated-cost deltas
without claiming completeness or source independence, or promoting a single pair
into a latency percentile. Keep raw logs private.
