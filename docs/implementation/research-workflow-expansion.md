# Research workflow and library delivery plan

## Decision and scope

Extend the existing Next.js BFF, FastAPI service, PostgreSQL tenant transactions,
and versioned reports. Keep LangGraph as the only research orchestrator. Use
existing run, report, source, claim, citation, job and approval identities;
introduce durable entities only where the product needs new ownership or history.

Observed before this local slice: reports had versioned IDs and structured
evidence documents, but database enforcement against post-publication edits was
missing; follow-ups reference exact parent reports. Approval currently accepts
approve or reject only. Project/library and comparison code now exists locally,
but has not passed the required PostgreSQL integration gates. There is no
conversation entity, browser adapter, or academic provider. Execution completion
and answer quality already have distinct meanings.

Assumption: a project is initially a private folder owned by a verified user in
one tenant. A saved source retains its original run and evidence provenance.
Organization-wide search must wait for explicit membership and role semantics;
being in the same tenant does not grant access to another user's private data.

## Delivery sequence and acceptance gates

| Milestone | Deliverable | Acceptance gate |
| --- | --- | --- |
| 1 — Save and compare | Private projects; saved report versions/sources; tags, notes, filters, server search, pagination; report comparison and bounded text diffs | Cross-tenant and same-tenant other-user requests denied; concurrent duplicate saves converge; exact report version retained; legacy reports compare as unassessed; comparison makes no provider calls |
| 2 — Edit before execution | Versioned replacement plans while approval is paused; explicit approve/reject for the replacement; audit original plan | Lock registry/job/run in existing order; reject stale edits; unchanged budgets; no paid dispatch before approval; checkpoint resume reads the accepted replacement; later coverage-repair approval remains intact |
| 3 — Continue with context | `threads`, ordered `thread_messages`, linked runs/report references; thread UI | Idempotent message/run creation; bounded context from authorized published evidence; private material excluded from unrelated threads; recovery/cancellation retain existing guarantees |
| 4 — Richer evidence | Citation-bound comparison cells, mode-specific sections, academic adapters and normalized DOI/author/date metadata; publisher/content correlation labels | Every factual cell resolves to admitted claims/citations; unknown cells explicitly missing; provider calls use existing admission/ledger policy; duplicates never counted as independent corroboration |
| 5 — Controlled sharing | Revocable, expiring links to one immutable report version; explicit audience; saved project collections | Token hash stored; owner creates/revokes; recipients see only the report and published evidence projection; no rejected claims/private artifacts/checkpoints; expiration/revocation checked on every read |
| 6 — Approved browsing | Read-only browser provider through routing, then explicit approvals for individual side-effect actions | Provider selected/configured; budgets/timeout/session limits; network egress checks; action scope bound to approval and state; no replay of ambiguous side effects; prompt injection/redirect/download tests |

Milestones remain planned work until their acceptance gates pass. They are not
considered complete from a navigation item or database column alone. The four
Phase 2 features (exports, library, academic metadata, private ingestion) remain
compatible with this ordering: versioned exports can proceed independently,
academic search supplies metadata for milestone 4, and ingestion must establish
private retrieval authorization before uploaded evidence is shared or threaded.

## Local implementation status

- Projects, private report/source saves, tags, notes, filters, bounded server
  search and report-version comparisons are implemented locally. Comparisons
  use literal finding matching and bounded report-text diffs; they do not claim
  semantic equivalence or source independence.
- Initial plan editing during the approval pause is implemented locally as an
  immutable replacement version. Approval binds to the replacement plan ID,
  stale versions are rejected, and graph resume reloads the accepted question
  IDs. Coverage-repair plans remain read-only in the approval panel.
- Migration 0009 is local only. Its downgrade is intentionally disabled because
  dropping project and library tables would erase user organization data.
- Published reports are now frozen by an additive local migration and exact
  content hash; legacy reports remain readable without inventing a past hash.
- Controlled links pin one report, store only a token digest, expire within 30
  days, and can be revoked. The public route returns only the shared report
  projection and checks validity on every request.
- Markdown and BibTeX exports are pinned to a report ID/version/hash and stored
  as bounded (1 MiB) Postgres bytea artifacts. Downloads are owner-authorized
  and checksum-verified. PDF remains browser print; DOCX and durable PDF remain
  pending renderer/resource-limit work.
- Acceptance integration gates have been added but require a disposable local
  Postgres run. Type/lint/unit checks are separate from that integration gate.
  Migration 0009 and the new 0010 remain local only; no hosted migration or
  deployment has run.
- Academic adapters/source relationships, claim-linked comparison snapshots,
  private ingestion, contextual threads and browser automation remain future
  milestones. Browser automation stays last pending egress containment.

## Durable persistence design for the remaining features

PostgreSQL remains authoritative for ownership, lifecycle state, report identity,
approvals, access revocation, and the bounded Markdown/BibTeX export bytes.
Private object storage is reserved for uploaded source bytes and larger future
artifacts. Do not claim a transaction spans the database and object store: persist a
database intent first, perform storage I/O idempotently, finalize in PostgreSQL,
and reconcile stale intents/orphan objects. Keep each feature owner-scoped, with
`tenant_id`, `user_id`, composite foreign keys, explicit API predicates, forced
RLS, and least-privilege `research_app` grants. Do not introduce a general queue
or another orchestration framework; extend the existing dispatcher/outbox only
where durable asynchronous work is required.

| Feature | Durable records and source of truth | Commit/retry/recovery rule |
| --- | --- | --- |
| Controlled report sharing | Implemented locally as `report_shares`: owner, tenant, exact published `report_id`, unique token digest, created/expiry/revoked timestamps. PostgreSQL RLS has a token-specific lookup policy; report access is then restricted to that exact share row. | Generate a high-entropy secret once; store only its digest and return a fragment-based link once. Resolve token, expiry, revocation, and exact report on every access. Invalid/revoked/expired tokens return generic not-found; responses are `no-store` and no-referrer. No storage URL is issued. |
| Academic metadata and source relationships | `academic_works` / provider identifiers / append-only metadata snapshots; `source_work_links`; `source_relationships` with relation, evidence, method/version, confidence, and timestamp. Source observations remain separate from the underlying scholarly work. | Normalize DOI and provider IDs for exact identity; uniqueness handles races. Title/author/year similarity proposes a match only. Provider outage or conflicting metadata never deletes or invalidates a source; persist an enrichment outcome and retain both snapshots. Deduplicate/relationship calculations are bounded to a run and reproducible by algorithm version. |
| Claim-linked comparison | `report_comparisons` pins ordered immutable report IDs, their document hashes, algorithm/verifier versions, output digest, and status; `comparison_items` link nullable left/right claim IDs and verified citations, relation, and review state. | Build only from persisted claims/citations. Deterministic literal matches can be confirmed; semantic matches begin as candidates and must be verified before being shown as agreement/conflict. Unique key on report pair + algorithm version makes retries idempotent. Each claim FK must be constrained to its side's report. |
| Version-bound exports | Implemented locally for Markdown/BibTeX as `report_exports`: exact report ID/version/hash, owner, renderer version, output hash/size and bounded bytes in Postgres. PDF/DOCX renderers are not yet implemented as durable exports. | Rendering is deterministic and capped at 1 MiB. Unique report/format/renderer keys make request retries idempotent; a single SQL transaction persists metadata and bytes. Downloads reauthorize the owner and verify stored size/hash. No object-store crash window exists for these two formats. |
| Private ingestion | `uploads` pins owner/project, random object key, filename for display only, declared/detected MIME, size/hash, parser version, status, job lease/attempt, extracted-text artifact reference/hash, safe error, retention/deletion timestamps. `sources`/claims link back to the upload. | State path: `initiated → uploaded/quarantined → processing → ready`, with `failed` and `deleting → deleted`. Verify actual length/checksum/file signature, not client headers. Parsing is bounded and isolated; outputs are committed with source/evidence rows and outbox event atomically. Reconciliation handles interrupted upload, parse, and deletion; tombstone retrieval before object deletion. |
| Browser actions | `browser_action_approvals` binds run/task/job generation to a canonical action payload hash, origin/URL, bounded preview, state, expiry, decision actor/time, and consumption result. Browser runtime state/checkpoints remain separate and tenant-fenced. | Approval is for one exact action, not a blanket grant. Lock the current job/run/action in established order; atomically decide once and append outbox event. On resume, recheck payload hash, expiry, cancellation, and generation before consuming. An uncertain external side effect is not automatically replayed. Persist no cookies or credentials. |

### Cross-system and concurrency invariants

- **Immutable reports first:** before sharing or exporting, prevent mutation of a
  published report in every write path and enforce it at the database boundary
  where practical. A report ID must always mean the same report bytes/document.
- **Outbox is durable; notifications are hints:** state transition and outbox
  record commit together. Publish after commit, tolerate missed notifications,
  and recover by scanning/replaying PostgreSQL state. Do not use Redis Pub/Sub as
  the only work record.
- **Object store is not transactional:** persist storage intent, use opaque
  server-generated keys, checksum and size, and make repeated puts/deletes
  idempotent. Reconcile the crash windows before calling any artifact immutable.
- **No secret bearer material in SQL or logs:** share/upload capabilities are
  high entropy, time bounded, stored hashed where they must be looked up, and
  redacted from request logs/traces. Revoke or expire access through database
  state; a previously downloaded copy cannot be recalled.
- **Private-source policy follows the report:** a report built from private
  uploads must not expose their original object, file name, or extracted text
  through a public share unless the owner explicitly opts in to a safe published
  projection. Owner-private project membership is not organization sharing.
- **Retain deletion state:** deletion is a resumable workflow—mark inaccessible,
  delete object and derived artifacts, then mark complete. Define what backups
  retain and the expiry/restore behavior before promising erasure.

### Security and correctness gates before enabling each feature

- Sharing: owner-only create/list/revoke; exact report version; token hash never
  logged; same-tenant other-owner and cross-tenant access denied; revoke/expiry
  checked on the next request; no-store/referrer headers; report update blocked.
- Academic: DOI normalization and provider-ID concurrent insert races; duplicate
  preprint/publisher copies; malformed or conflicting metadata; timeouts/rate
  limits; provider failure does not fail the research run; no fabricated
  independence claim.
- Comparisons: report IDs remain pinned across new versions; claim references
  belong to their designated report; uncertain alignment never appears as a
  verified conflict; idempotent compare retries return the same digest.
- Exports: each format is generated from the same persisted report snapshot;
  old reports without structured status say “not assessed”; crash between
  object write and SQL finalization is reconciled; only owner can download; size,
  MIME, filename, citations, and checksum are verified. PDF generation must not
  fetch arbitrary URLs or read host files.
- Uploads: cap enforced at proxy and API/storage boundary; MIME spoof, path
  tricks, malformed PDF, DOCX ZIP/XML bombs, duplicate upload, parser timeout,
  worker crash, unauthorized retrieval, and retryable deletion covered. The UI
  distinguishes uploaded, processing, ready, and failed states.
- Browser: no private/loopback/link-local/reserved/metadata destination over
  IPv4 or IPv6; redirect, DNS-rebinding, subresource, popup, WebSocket, and
  download paths blocked; isolated ephemeral context, no ambient cookies, strict
  per-run request/time/byte budgets; repeated or timed-out side-effect action
  cannot be silently replayed.

### Recommended delivery order

1. **Validate migrations 0009 and 0010 plus the dirty slice** with a disposable
   local database integration run. Do not apply either to hosted Supabase as
   part of implementation work without separate rollout approval.
2. **PDF/DOCX exports** with pinned renderers, isolated resource limits, and
   version/checksum tests. Markdown/BibTeX are already available locally.
3. **Academic work identity + persisted relationship evidence**, starting with
   OpenAlex metadata and keeping provider calls under the existing reservation,
   budget, timeout, and provider-call ledger. Add Semantic Scholar only after
   duplicate and provider-outage cases pass.
4. **Claim-linked comparison v2** as a deterministic persisted snapshot first;
   defer model-generated semantic alignment until candidate/verified states and
   calibration gates exist.
5. **Version-bound export jobs**, first Markdown/BibTeX, then PDF/DOCX with pinned
   renderers and bounded worker resource use.
6. **Private upload/ingestion**, after the storage bucket, enforced size limit,
   parser isolation, retention, and resumable deletion are specified. The first
   release should support a narrow file allowlist and a conservative size/page
   cap rather than general document import.
7. **Approved browser capability** last: read-only provider first; only then
   action-specific approvals and side-effecting actions after network-level
   egress controls and uncertain-outcome handling are operationally proven.

For each migration use expand/contract, run against a fresh database and an
existing snapshot, keep the migration additive, validate runtime-role grants
and forced RLS, and prefer forward repair to destructive downgrade after user
data exists. Do not claim production-ready until crash/retry, concurrent writes,
tenant isolation, backup restore, and worker-restart tests pass.

## First implementation: contracts and data

- `projects`: UUID, tenant, owner, name, timestamps. A project is a folder;
  nested trees are deferred to avoid recursive ACLs and ambiguous moves.
- `library_items`: UUID, tenant, owner, optional project, exactly one report or
  source reference, bounded tags/notes, timestamps. Unique per owner/target.
  Saves reference immutable content rather than copying entire reports/artifacts.
- Composite tenant foreign keys preserve references. Forced RLS, explicit runtime
  grants, and revoked browser-role access follow the current BFF-only model.
- Library API also filters by verified owner. Search is bounded, literal,
  case-insensitive, and server-side. Keyset pagination avoids unbounded lists.
- Report comparisons authorize both published report IDs through their runs.
  Structured finding deltas compare normalized literal text, with both original
  claim IDs retained; they do not infer semantic equivalence or causality.
  Evidence URLs/content hashes identify overlap, never source independence.
- Text diffs use line-based deterministic comparison inside explicit size/work
  limits. Oversized documents return a clear unavailable state instead of
  blocking the event loop or returning silently truncated comparisons.
- Existing report documents remain immutable; comparison is a read projection.
  New shared Zod contracts and generated Python models validate boundaries.

## Operation, performance and rollback

No added provider/model call is needed for saving, searching, or comparing.
Search/compare requests release database connections before presentation work;
bounded CPU diff work runs outside the event loop. UI loads independent lists
concurrently, cancels stale search requests, and exposes failures with retry.
Existing brand tokens, keyboard focus and reduced-motion behavior are reused.

Migration 0009 is additive and must pass on loopback PostgreSQL, including a
fresh full migration chain, before any hosted application. Update the restricted
runtime role's explicit table grants in the same migration. A rollback to earlier
application code leaves private library rows intact; destructive downgrade is
not the default rollback. No hosted migration, deployment or paid research is
part of this local implementation.

Security reference checked: [Supabase RLS and grants](https://supabase.com/docs/guides/database/postgres/row-level-security).
The repository uses Alembic; retain that migration authority rather than adding
a second Supabase CLI migration history.
