"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { WorkspaceShell } from "../../../components/workspace-shell";
import { Alert, Button, Empty } from "../../../components/workbench-ui";
import { safeUrl } from "../../../components/ui";
import {
  addEvidence, createReview, getFlow, getReview, importDoi, importPdf,
  importRecords, listReviews, saveDecision, saveRetrieval,
  type Decision, type Flow, type RecordRow, type Review, type ReviewDetail,
} from "./scholarly-client";
import "./review.css";

const REASONS = [
  "out_of_scope", "wrong_population", "wrong_intervention", "wrong_outcome",
  "wrong_study_design", "wrong_publication_type", "outside_date_range", "non_primary_source",
];
const COUNTS = [
  ["records_identified", "Records identified"], ["duplicates_removed", "Duplicates removed"],
  ["records_screened", "Title/abstract screened"], ["records_excluded", "Title/abstract excluded"],
  ["records_maybe", "Title/abstract maybe"], ["records_awaiting_screening", "Awaiting screening"],
  ["reports_sought", "Full texts sought"], ["reports_retrieved", "Full texts retrieved"],
  ["reports_not_retrieved", "Not retrieved"], ["reports_awaiting_retrieval", "Awaiting retrieval"],
  ["reports_assessed", "Full texts assessed"], ["reports_excluded", "Full texts excluded"],
  ["reports_maybe", "Full text maybe"], ["reports_awaiting_assessment", "Awaiting assessment"],
  ["studies_included", "Studies included"],
] as const;

function message(cause: unknown) {
  return cause instanceof Error ? cause.message : "Request failed. Please try again.";
}

function DecisionForm({ reviewId, record, stage, sourceId, onSaved }: {
  reviewId: string; record: RecordRow; stage: "title_abstract" | "full_text";
  sourceId?: string | null; onSaved: () => Promise<void>;
}) {
  const [outcome, setOutcome] = useState<Decision["outcome"]>("include");
  const [reason, setReason] = useState(REASONS[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await saveDecision(reviewId, {
        record_id: record.record_id, stage, outcome,
        exclusion_reason: outcome === "exclude" ? reason || null : null,
        source_id: stage === "full_text" ? sourceId || null : null,
      });
      await onSaved();
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }
  return <form className="scholarly-inline-form" onSubmit={submit}>
    <label>{stage === "full_text" ? "Full-text decision" : "Title/abstract decision"}
      <select value={outcome} onChange={(event) => setOutcome(event.target.value as Decision["outcome"])}>
        <option value="include">Include</option><option value="exclude">Exclude</option><option value="maybe">Maybe</option>
      </select>
    </label>
    {outcome === "exclude" ? <label>Reason
      <select value={reason} onChange={(event) => setReason(event.target.value)}>
        {REASONS.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
      </select>
    </label> : null}
    <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save decision"}</Button>
    {error ? <Alert>{error}</Alert> : null}
  </form>;
}

function RetrievalForm({ reviewId, recordId, onSaved }: {
  reviewId: string; recordId: string; onSaved: () => Promise<void>;
}) {
  const [status, setStatus] = useState("retrieved");
  const [sourceId, setSourceId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await saveRetrieval(reviewId, {
        record_id: recordId, status: status as "retrieved" | "not_retrieved",
        source_id: status === "retrieved" ? sourceId.trim() : null,
      });
      await onSaved();
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }
  return <form className="scholarly-inline-form" onSubmit={submit}>
    <label>Full-text retrieval
      <select value={status} onChange={(event) => setStatus(event.target.value)}>
        <option value="retrieved">Retrieved</option><option value="not_retrieved">Not retrieved</option>
      </select>
    </label>
    {status === "retrieved" ? <label>Retrieved source ID
      <input required value={sourceId} onChange={(event) => setSourceId(event.target.value)} placeholder="ID from the retrieved source" />
    </label> : null}
    <Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save retrieval"}</Button>
    {error ? <Alert>{error}</Alert> : null}
  </form>;
}

export default function ScholarlyReviewPage() {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [reviewId, setReviewId] = useState("");
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [flow, setFlow] = useState<Flow | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [notice, setNotice] = useState("");
  const [title, setTitle] = useState("");
  const [question, setQuestion] = useState("");
  const [doi, setDoi] = useState("");
  const [pdfTitle, setPdfTitle] = useState("");
  const [pdf, setPdf] = useState<File | null>(null);
  const [database, setDatabase] = useState("");
  const [query, setQuery] = useState("");
  const [recordJson, setRecordJson] = useState("");
  const [evidenceRecord, setEvidenceRecord] = useState("");
  const [artifactId, setArtifactId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [claim, setClaim] = useState("");
  const [quote, setQuote] = useState("");
  const [pageNumber, setPageNumber] = useState("1");
  const [quoteStart, setQuoteStart] = useState("0");
  const [quoteEnd, setQuoteEnd] = useState("");

  const refresh = useCallback(async (id: string) => {
    setDetailLoading(true); setDetailError("");
    try {
      const [nextDetail, nextFlow] = await Promise.all([getReview(id), getFlow(id)]);
      setDetail(nextDetail); setFlow(nextFlow);
    } catch (cause) { setDetailError(message(cause)); }
    finally { setDetailLoading(false); }
  }, []);

  useEffect(() => {
    let active = true;
    listReviews().then((items) => {
      if (active) { setReviews(items); setReviewId((current) => current || items[0]?.reviewId || ""); }
    }).catch((cause) => { if (active) setError(message(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!reviewId) { setDetail(null); setFlow(null); return; }
    void refresh(reviewId);
  }, [reviewId, refresh]);

  async function run(action: () => Promise<void>, success: string) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); setNotice(success); if (reviewId) await refresh(reviewId); }
    catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }

  async function addReview(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const created = await createReview(title.trim(), question.trim());
      setReviews((current) => [created, ...current]); setReviewId(created.reviewId);
      setTitle(""); setQuestion(""); setNotice("Review created.");
    } catch (cause) { setError(message(cause)); }
    finally { setBusy(false); }
  }

  function parseManualRecords() {
    if (recordJson.length > 180_000) throw new Error("Record list is too large for this form.");
    let parsed: unknown;
    try { parsed = JSON.parse(recordJson); } catch { throw new Error("Enter a valid JSON array of records."); }
    if (!Array.isArray(parsed) || parsed.length < 1 || parsed.length > 50)
      throw new Error("Enter 1 to 50 records in a JSON array.");
    const searchId = crypto.randomUUID();
    const records = parsed.map((item, index) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error(`Record ${index + 1} must be an object.`);
      const row = item as Record<string, unknown>;
      if (typeof row.title !== "string" || !row.title.trim() || typeof row.providerRecordId !== "string" || !row.providerRecordId.trim())
        throw new Error(`Record ${index + 1} needs title and providerRecordId.`);
      return {
        recordId: crypto.randomUUID(), searchId,
        provider: database.trim(), providerRecordId: row.providerRecordId.trim(),
        title: row.title.trim(), abstract: typeof row.abstract === "string" ? row.abstract : null,
        doi: typeof row.doi === "string" ? row.doi : null,
        locatorUrl: typeof row.locatorUrl === "string" ? row.locatorUrl : null,
      };
    });
    return { execution: { searchId, query: query.trim(), executedAt: new Date().toISOString(),
      database: database.trim(), filters: [], resultRecordIds: records.map((row) => row.recordId),
      reportedResultCount: records.length }, records };
  }

  const decisionFor = (recordId: string, stage: Decision["stage"]) => detail?.decisions.find((item) => item.record_id === recordId && item.stage === stage);
  return <WorkspaceShell title="Scholarly review">
    <main className="scholarly-review">
      <header className="scholarly-header"><p className="scholarly-kicker">Research / Review</p>
        <h1>Scholarly review</h1>
        <p>Import observed records and documents, record your decisions, and follow the review flow. Metadata alone is not full-text evidence.</p>
      </header>

      {error ? <Alert>{error}</Alert> : null}
      {notice ? <p className="scholarly-notice" role="status">{notice}</p> : null}

      <section className="scholarly-panel" aria-labelledby="review-heading">
        <h2 id="review-heading">Your reviews</h2>
        <form className="scholarly-form scholarly-create" onSubmit={addReview}>
          <label>Review title<input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="e.g. Interventions for sleep quality" /></label>
          <label>Review question<input required maxLength={10000} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What are you investigating?" /></label>
          <Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create review"}</Button>
        </form>
        {loading ? <p role="status">Loading reviews…</p> : reviews.length ?
          <label className="scholarly-picker">Open review
            <select value={reviewId} onChange={(event) => setReviewId(event.target.value)}>
              {reviews.map((item) => <option key={item.reviewId} value={item.reviewId}>{item.title}</option>)}
            </select>
          </label> : <Empty title="No reviews yet">Create one to begin collecting records.</Empty>}
      </section>

      {reviewId ? <>
        {detailLoading ? <p role="status">Loading review and counts…</p> : null}
        {detailError ? <Alert>{detailError} <Button type="button" variant="outline" onClick={() => void refresh(reviewId)}>Retry</Button></Alert> : null}
        <section className="scholarly-panel" aria-labelledby="import-heading">
          <h2 id="import-heading">Import</h2>
          <p>DOI results add discovery metadata. A PDF import stores parsed page text; inspect the source before recording a retrieval or decision.</p>
          <div className="scholarly-import-grid">
            <form className="scholarly-form" onSubmit={(event) => { event.preventDefault(); void run(async () => { await importDoi(reviewId, doi.trim()); setDoi(""); }, "DOI metadata imported."); }}>
              <h3>DOI</h3><label>DOI<input required value={doi} onChange={(event) => setDoi(event.target.value)} placeholder="10.1000/example" /></label>
              <Button type="submit" disabled={busy}>Import DOI</Button>
            </form>
            <form className="scholarly-form" onSubmit={(event) => { event.preventDefault(); if (!pdf) return; void run(async () => { const imported = await importPdf(reviewId, pdfTitle.trim(), pdf); setEvidenceRecord(imported.recordId); setArtifactId(imported.artifactId); setSourceId(String(imported.artifactId)); setPdf(null); setPdfTitle(""); }, "PDF imported. Its artifact ID is filled in below; screen and retrieve the record before linking a passage."); }}>
              <h3>PDF document</h3><label>Document title<input required maxLength={500} value={pdfTitle} onChange={(event) => setPdfTitle(event.target.value)} /></label>
              <label>PDF, up to 4 MiB<input required type="file" accept="application/pdf,.pdf" onChange={(event) => setPdf(event.target.files?.[0] ?? null)} /></label>
              <Button type="submit" disabled={busy || !pdf}>Import PDF</Button>
            </form>
          </div>
          <details className="scholarly-manual"><summary>Import observed search records</summary>
            <form className="scholarly-form" onSubmit={(event) => { event.preventDefault(); void run(async () => { const payload = parseManualRecords(); await importRecords(reviewId, payload.execution, payload.records); setRecordJson(""); }, "Search receipt and records imported."); }}>
              <p>Enter the database and exact query used. Each JSON record needs a title and providerRecordId; optional fields are abstract, doi and locatorUrl.</p>
              <label>Database<input required value={database} onChange={(event) => setDatabase(event.target.value)} /></label>
              <label>Exact query<input required value={query} onChange={(event) => setQuery(event.target.value)} /></label>
              <label>Observed records (JSON array)<textarea required rows={5} value={recordJson} onChange={(event) => setRecordJson(event.target.value)} placeholder='[{"title":"Study title","providerRecordId":"123"}]' /></label>
              <Button type="submit" disabled={busy}>Import records</Button>
            </form>
          </details>
        </section>

        <section className="scholarly-panel" aria-labelledby="flow-heading">
          <h2 id="flow-heading">Review flow counts</h2><p>Counts reflect recorded workflow events and unresolved work. They are not a PRISMA compliance certification.</p>
          {flow ? <dl className="scholarly-counts">{COUNTS.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{typeof flow[key] === "number" ? flow[key] : "—"}</dd></div>)}</dl> : <p>No counts available yet.</p>}
        </section>

        <section className="scholarly-panel" aria-labelledby="records-heading">
          <h2 id="records-heading">Records and screening</h2>
          {detail?.records.length ? <div className="scholarly-record-list">{detail.records.map((record) => {
            const titleDecision = decisionFor(record.record_id, "title_abstract");
            const retrieval = detail.retrievals.find((item) => item.record_id === record.record_id);
            const fullDecision = decisionFor(record.record_id, "full_text");
            const url = record.locator_url ? safeUrl(record.locator_url) : undefined;
            return <article className="scholarly-record" key={record.record_id}>
              <div className="scholarly-record-head"><h3>{record.title}</h3><span>{record.provider}</span></div>
              <p className="scholarly-record-meta">{record.doi ? `DOI: ${record.doi}` : "No DOI"} · Record ID: {record.record_id}</p>
              {record.abstract ? <details><summary>Abstract</summary><p>{record.abstract}</p></details> : <p>No abstract supplied.</p>}
              {url ? <a href={url} target="_blank" rel="noopener noreferrer">Open source locator</a> : null}
              {titleDecision ? <p><strong>Title/abstract:</strong> {titleDecision.outcome}{titleDecision.exclusion_reason ? ` · ${titleDecision.exclusion_reason.replaceAll("_", " ")}` : ""}</p>
                : <DecisionForm reviewId={reviewId} record={record} stage="title_abstract" onSaved={() => refresh(reviewId)} />}
              {titleDecision?.outcome === "include" ? retrieval ? <p><strong>Retrieval:</strong> {retrieval.status}{retrieval.source_id ? ` · ${retrieval.source_id}` : ""}</p>
                : <RetrievalForm reviewId={reviewId} recordId={record.record_id} onSaved={() => refresh(reviewId)} /> : null}
              {retrieval?.status === "retrieved" && retrieval.source_id ? fullDecision ? <p><strong>Full text:</strong> {fullDecision.outcome}</p>
                : <DecisionForm reviewId={reviewId} record={record} stage="full_text" sourceId={retrieval.source_id} onSaved={() => refresh(reviewId)} /> : null}
            </article>;
          })}</div> : <Empty title="No records yet">Import a DOI, PDF, or observed search records to start screening.</Empty>}
        </section>

        <section className="scholarly-panel" aria-labelledby="evidence-heading">
          <h2 id="evidence-heading">Evidence table</h2><p>Each row links a claim to an exact source passage and locator. A matching passage does not establish that the claim is supported.</p>
          {detail?.evidence.length ? <div className="scholarly-table-wrap"><table>
            <thead><tr><th scope="col">Record</th><th scope="col">Claim</th><th scope="col">Source passage linked</th><th scope="col">Locator</th></tr></thead>
            <tbody>{detail.evidence.map((row) => <tr key={row.id}>
              <td>{detail.records.find((item) => item.record_id === row.recordId)?.title ?? row.recordId}</td>
              <td>{row.claim}</td><td><blockquote>{row.quote}</blockquote><small>Source {row.sourceId}</small></td>
              <td>{row.pageAnchor || "No page anchor"}</td>
            </tr>)}</tbody>
          </table></div> : <Empty title="No passages linked">Add evidence after recording a retrieved source and matching artifact.</Empty>}
          {detail?.records.length ? <details className="scholarly-manual"><summary>Add a source passage</summary>
            <form className="scholarly-form" onSubmit={(event) => { event.preventDefault(); void run(async () => {
              await addEvidence(reviewId, evidenceRecord, { artifactId: artifactId.trim(), sourceId: sourceId.trim(), claim: claim.trim(), quote: quote.trim(), pageNumber: Number(pageNumber), start: Number(quoteStart), end: Number(quoteEnd) });
              setClaim(""); setQuote(""); setQuoteStart("0"); setQuoteEnd("");
            }, "Source passage linked. Claim support has not been assessed."); }}>
              <p>The quote must occur in the stored artifact text and the source ID must match a retrieved source.</p>
              <label>Record<select required value={evidenceRecord} onChange={(event) => setEvidenceRecord(event.target.value)}><option value="">Select record</option>{detail.records.map((record) => <option key={record.record_id} value={record.record_id}>{record.title}</option>)}</select></label>
              <label>Artifact ID<input required value={artifactId} onChange={(event) => setArtifactId(event.target.value)} /></label>
              <label>Retrieved source ID<input required value={sourceId} onChange={(event) => setSourceId(event.target.value)} /></label>
              <label>Claim<input required value={claim} onChange={(event) => setClaim(event.target.value)} /></label>
              <label>Exact quote<textarea required rows={3} value={quote} onChange={(event) => setQuote(event.target.value)} /></label>
              <label>PDF page number<input required type="number" min="1" max="100" value={pageNumber} onChange={(event) => setPageNumber(event.target.value)} /></label>
              <label>Quote start offset on page<input required type="number" min="0" value={quoteStart} onChange={(event) => setQuoteStart(event.target.value)} /></label>
              <label>Quote end offset on page<input required type="number" min="1" value={quoteEnd} onChange={(event) => setQuoteEnd(event.target.value)} /></label>
              <Button type="submit" disabled={busy}>Link passage</Button>
            </form>
          </details> : null}
        </section>
      </> : null}
    </main>
  </WorkspaceShell>;
}
