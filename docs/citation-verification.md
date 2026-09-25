# Citation Verification

How the system prevents citation hallucination and ensures every claim the
writer uses is actually supported. See [evidence-system.md](./evidence-system.md)
for the upstream distillation pipeline and
[state-management.md](./state-management.md#citation) for the full
`Citation` schema.

## Why exact-span verification matters

An LLM can produce a plausible-sounding citation that does not actually
appear in the source. Exact-span verification is a deterministic,
non-LLM check that the cited text genuinely occurs in the normalized
source content at the claimed location — this is the first line of
defense against citation hallucination, independent of how confident the
extraction model sounded.

## Verification checks

| Check | Type | What it confirms |
|---|---|---|
| Exact-span check | Deterministic | The cited passage occurs verbatim (or within tolerance) in the normalized source text at the claimed offset |
| Source identity check | Deterministic | The citation's `sourceId` and URL match a stored, canonicalized `Source` record |
| Semantic support classification | Model-assisted | Whether the span actually supports, contradicts, or is unrelated to the claim (not just present nearby) |
| Publication date check | Deterministic | `publishedAt` is captured and reasonable for freshness-sensitive claims |
| Retrieval date check | Deterministic | `retrievedAt` is captured for every source |
| Contradiction detection | Model-assisted | Cross-source disagreement on the same proposition is flagged, not silently dropped |
| Source-quality scoring | Model-assisted + heuristics | `qualityScore` reflects source class, domain reputation, and corroboration |

## Citation contract

```typescript
export const CitationSchema = z.object({
  id: z.string().uuid(),
  sourceId: z.string().uuid(),
  quote: z.string().min(1).max(600),
  locator: z.object({
    heading: z.string().max(300).nullable(),
    startChar: z.number().int().nonnegative().nullable(),
    endChar: z.number().int().nonnegative().nullable(),
  }),
  verified: z.boolean(),
  verificationMethod: z.enum(["exact_span", "semantic_entailment", "manual"]),
});
```

`verified` is `true` only once the applicable checks for its
`verificationMethod` have passed. `manual` exists for a human-reviewed
override path (e.g., during evaluation or audit) — see
[evaluation.md](./evaluation.md).

## Citation mapping

The writer references claims by **claim ID**, not by raw citation text. A
deterministic post-processing step (part of `quality_gate`) converts
claim IDs into rendered citation markers (`[12]`) and resolves each marker
back to its `Citation`/`Source` pair for the frontend's citation popover
(see [ui-ux.md](./ui-ux.md#citation-interaction)). If a claim ID does not
resolve, the report is rejected — never silently dropped or
auto-corrected.

## What happens when evidence is insufficient

- A candidate claim that fails exact-span or semantic verification is
  classified `support: "insufficient"` and **retained for audit** but
  excluded from writer context.
- A sub-question with no supported claims becomes a `ResearchGap` (see
  [state-management.md](./state-management.md#researchgap)), surfaced to
  the reflector.
- If the run ultimately produces a report with unresolved gaps, the report
  must acknowledge them explicitly rather than presenting a falsely
  complete picture (see [research-workflow.md](./research-workflow.md#incomplete-research)).

## Citation hallucination prevention — defense in depth

1. Distiller can only emit claims with an evidence span (cannot invent a
   claim with no source).
2. Verifier's exact-span check is deterministic, not model-judged.
3. Verifier's semantic check independently confirms support (a span
   existing nearby is not enough).
4. Writer operates only on the verified claim ledger — it cannot see or
   cite anything the verifier rejected.
5. Quality gate re-resolves every citation ID against the stored ledger
   before the report is allowed to complete.
6. Search-result snippets are explicitly disallowed as primary-source
   citations — the underlying page must be fetched and verified (see
   [provider-routing.md](./provider-routing.md), Serper/Tavily rows).

## Source-type validation

The quality gate specifically checks that no citation treats a
search-result snippet (Serper/Tavily "answer" field) as if it were a
primary source — the original page must have been fetched, normalized, and
verified per the pipeline in [evidence-system.md](./evidence-system.md).
