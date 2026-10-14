# Focused synthesis, persistence and feedback — 2026-10-14

Historical slice: the later [mode-specific reports](./mode-specific-research-reports.md)
supersede the eight-candidate Focused ceiling and Balanced/Deep draft/audit path.

## Evidence and reproduction

The supplied trace for run `1fa8dec9-4fe3-4d5e-98ab-6ed038f38e68` reports
`RuntimeError` at `builder.py:407`, the explicit "no report assertions could be
located" guard. Collection completed in 53.46 seconds; synthesis failed after
28.46 seconds. This was not the previous wall-clock exception. The trace alone
does not reveal the private model output, so it cannot establish whether every
rejected assertion was paraphrased or merely reformatted.

Two deterministic tests reproduced that exception: a verbatim assertion whose
Markdown emphasis/line breaks differed, and an entirely invented assertion.
The latter must never be admitted as a finding.

The attachment contains 415 structured records, including 211 slow SQL records
and 125 transaction records. Many statements took approximately 280–300 ms.
This is measured driver round-trip latency, not proof of expensive query plans.

## Bounded implementation

- Focused (3–6 provider-call allowance) uses one claim-candidate drafting call,
  capped at eight atomic claims, followed by deterministic exact passage checks
  and a semantic review of surviving quotes. It does not first write unchecked
  prose and then pay for assertion extraction. Balanced/Deep retain draft/audit.
  Quick explanations retain their existing path. No mode deadline or usage cap
  was raised in this change.
- Report-location checks accept only whitespace and inline emphasis/code-marker
  changes and retain the original report slice. Case, punctuation and meaning
  are not fuzzy matched. Source quotations remain exact; no source proof was
  relaxed.
- No located assertions produces an explicit limited evidence record with an
  open gap, not a generic execution crash or an invented answer. Provider/network
  exceptions and malformed output still fail. Contradicted/unsupported claims
  remain auditable and are excluded from published findings.
- Claim IDs are assigned before insertion. Parent claims flush once as a batch,
  then citations are added; one question query supplies both fallback attribution
  and coverage checks. Local integration tests assert one claim INSERT and one
  citation INSERT for two assertions, including durable execution. Run locks,
  tenant scope, FK order and lease fencing are unchanged.
- Routine SSE snapshots coalesce over 1.5 seconds; terminal events update the
  status immediately and request an immediate final snapshot. The existing
  single-in-flight guard and stale-terminal protection remain. Twenty injected
  source events produced one snapshot request in the browser regression.
- INFO retains important lifecycle/failure/provider records and synthesis counts.
  Routine database/auth/header diagnostics move to DEBUG. Slow SQL warnings
  default to 1,000 ms rather than flagging every normal hosted round trip.
  `RESEARCH_LOG_LEVEL=DEBUG` and `DATABASE_SLOW_STATEMENT_MS` enable investigation.
  Browser navigation aborts no longer masquerade as upstream service failures.
- Working runs show a thin transform-only indeterminate activity line. It is
  not a completion percentage and stops during approval, terminal states and
  reduced motion. Reports without any published claim show "Evidence record
  ready" and prominently explain that this is not a full answer.

## Verification and remaining limits

Tests use loopback PostgreSQL and mocked model/provider/artifact boundaries.
Browser fixtures intercept all API calls. Validation includes formatting and
assertion rejection, full-graph Focused verification, limited-result persistence,
batched inserts, cancellation/tenant isolation, replay accounting, burst
coalescing, reduced motion and mobile failure feedback.

Final checks passed: 363 backend tests, 59 web tests, 41 browser checks (11 failure,
24 automation, 6 synthesis/loading), Ruff, Python/TypeScript type checks, the
production web build, and `git diff --check`. Browser screenshots were inspected.

No paid live run was dispatched, no failed hosted run was reset, and no migration
is required. Restart/update the API and frontend to use these changes. Completion
and production latency are not guaranteed by local mocked tests. Significant
remaining speed work is measuring pool wait/SQL execution versus network RTT and
running the API near PostgreSQL; deployment is not part of this change.
