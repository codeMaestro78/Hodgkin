"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { WorkspaceShell } from "../../../components/workspace-shell";
import { Alert, Button, Empty } from "../../../components/workbench-ui";
import { safeUrl } from "../../../components/ui";
import {
  addEvidence, createReview, evidenceSourceForRecord, getArtifactPage, getFlow, getReview, importDoi, importPdf,
  importRecords, listReviews, saveDecision, saveRetrieval,
  type Decision, type Flow, type RecordRow, type Review, type ReviewDetail, type StudyArtifact,
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
  ["studies_included", "Unique included papers (exact matches)"],
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

function RetrievalForm({ reviewId, recordId, artifacts, onSaved }: {
  reviewId: string; recordId: string; artifacts: StudyArtifact[]; onSaved: () => Promise<void>;
}) {
  const [status, setStatus] = useState("retrieved");
  const [sourceId, setSourceId] = useState("");
  const selectedSourceId = sourceId || artifacts[0]?.artifactId || "";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await saveRetrieval(reviewId, {
        record_id: recordId, status: status as "retrieved" | "not_retrieved",
        source_id: status === "retrieved" ? selectedSourceId : null,
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
    {status === "retrieved" ? artifacts.length ? <label>Uploaded PDF
      <select value={selectedSourceId} onChange={(event) => setSourceId(event.target.value)}>
        {artifacts.map((artifact) => <option key={artifact.artifactId} value={artifact.artifactId}>
          PDF · {artifact.pageNumbers.length} pages
        </option>)}
      </select>
    </label> : <p>No PDF is attached to this record. A DOI or search result alone cannot be marked retrieved.</p> : null}
    <Button type="submit" disabled={busy || (status === "retrieved" && !selectedSourceId)}>{busy ? "Saving…" : "Save retrieval"}</Button>
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
  const [doiError, setDoiError] = useState("");
  const [pdfTitle, setPdfTitle] = useState("");
  const [pdf, setPdf] = useState<File | null>(null);
  const [database, setDatabase] = useState("");
  const [query, setQuery] = useState("");
  const [recordJson, setRecordJson] = useState("");
  const [evidenceRecord, setEvidenceRecord] = useState("");
  const [claim, setClaim] = useState("");
  const [quote, setQuote] = useState("");
  const [pageNumber, setPageNumber] = useState("1");
  const [showImport, setShowImport] = useState(false);
  const [pendingRecordFocus, setPendingRecordFocus] = useState("");
  const [showEvidenceForm, setShowEvidenceForm] = useState(false);
  const [readerText, setReaderText] = useState("");
  const [readerLoading, setReaderLoading] = useState(false);
  const [readerError, setReaderError] = useState("");
  const [selectionError, setSelectionError] = useState("");
  const [readerRetry, setReaderRetry] = useState(0);
  const pageTextRef = useRef<HTMLDivElement>(null);

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
  useEffect(() => {
    if (!pendingRecordFocus || !detail?.records.some((record) => record.record_id === pendingRecordFocus)) return;
    const frame = requestAnimationFrame(() => {
      document.getElementById(`record-${pendingRecordFocus}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      setPendingRecordFocus("");
    });
    return () => cancelAnimationFrame(frame);
  }, [detail, pendingRecordFocus]);

  async function run(action: () => Promise<void>, success: string | (() => string), onError?: (message: string) => void) {
    setBusy(true); setError(""); setNotice("");
    try { await action(); setNotice(typeof success === "string" ? success : success()); if (reviewId) await refresh(reviewId); }
    catch (cause) { setError(message(cause)); onError?.(message(cause)); }
    finally { setBusy(false); }
  }

  async function addReview(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const created = await createReview(title.trim(), question.trim());
      setReviews((current) => [created, ...current]); setReviewId(created.reviewId);
      setShowImport(true);
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
  const eligibleEvidenceRecords = detail?.records.filter((record) => evidenceSourceForRecord(detail, record.record_id)) ?? [];
  const selectedEvidenceRecord = eligibleEvidenceRecords.some((record) => record.record_id === evidenceRecord)
    ? evidenceRecord : eligibleEvidenceRecords[0]?.record_id ?? "";
  const selectedEvidenceArtifact = detail && selectedEvidenceRecord ? evidenceSourceForRecord(detail, selectedEvidenceRecord) : null;
  const availablePages = selectedEvidenceArtifact?.pageNumbers ?? [];
  const selectedPage = availablePages.includes(Number(pageNumber)) ? Number(pageNumber) : availablePages[0];
  useEffect(() => {
    if (!showEvidenceForm || !reviewId || !selectedEvidenceArtifact || !selectedPage) return;
    let active = true;
    getArtifactPage(reviewId, selectedEvidenceArtifact.artifactId, selectedPage).then((page) => {
      if (active) { setReaderText(page.text); setReaderError(""); }
    }).catch((cause) => { if (active) { setReaderText(""); setReaderError(message(cause)); } })
      .finally(() => { if (active) setReaderLoading(false); });
    return () => { active = false; };
  }, [showEvidenceForm, reviewId, selectedEvidenceArtifact?.artifactId, selectedPage, readerRetry]);

  function openEvidence(recordId: string) {
    setEvidenceRecord(recordId);
    setPageNumber("1");
    setReaderText("");
    setReaderLoading(true);
    setShowEvidenceForm(true);
    requestAnimationFrame(() => document.getElementById("evidence-heading")?.scrollIntoView({ behavior: "smooth", block: "start" }));
  }

  function selectPassage() {
    const selection = window.getSelection();
    const root = pageTextRef.current;
    if (!selection || selection.isCollapsed || !root?.contains(selection.anchorNode) || !root.contains(selection.focusNode)) return;
    const selected = selection.toString().trim();
    if (selected.length < 1 || selected.length > 600) {
      setSelectionError("Select a passage between 1 and 600 characters.");
      return;
    }
    if (!readerText.includes(selected)) {
      setSelectionError("The selected text could not be matched exactly. Choose a continuous passage on one page.");
      return;
    }
    setQuote(selected);
    setSelectionError("");
  }
  return <WorkspaceShell title="Scholarly review">
    <div className="scholarly-review">
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
            <select value={reviewId} onChange={(event) => { setReviewId(event.target.value); setShowImport(false); setShowEvidenceForm(false); }}>
              {reviews.map((item) => <option key={item.reviewId} value={item.reviewId}>{item.title}</option>)}
            </select>
          </label> : <Empty title="No reviews yet">Create one to begin collecting records.</Empty>}
      </section>

      {reviewId ? <>
        {detailLoading ? <p role="status">Loading review and counts…</p> : null}
        {detailError ? <Alert>{detailError} <Button type="button" variant="outline" onClick={() => void refresh(reviewId)}>Retry</Button></Alert> : null}
        <section className="scholarly-panel" aria-labelledby="import-heading">
          <div className="scholarly-section-heading"><h2 id="import-heading">Add papers</h2><Button type="button" variant="outline" onClick={() => setShowImport((value) => !value)} aria-expanded={showImport} aria-controls={showImport ? "scholarly-import-content" : undefined}>{showImport ? "Hide import options" : "Import DOI or PDF"}</Button></div>
          {showImport ? <div id="scholarly-import-content">
          <p>A DOI is a published paper’s identifier, often shown near its title or in a doi.org link. It is optional. If you have a PDF instead, use the PDF form. DOI import adds bibliographic details only; a PDF is needed to link exact source passages.</p>
          <div className="scholarly-import-grid">
            <form className="scholarly-form" onSubmit={(event) => { event.preventDefault(); setDoiError(""); void run(async () => { await importDoi(reviewId, doi.trim()); setDoi(""); }, "DOI metadata imported.", setDoiError); }}>
              <h3>Import a paper by DOI</h3><label>DOI or doi.org link<input required value={doi} onChange={(event) => { setDoi(event.target.value); setDoiError(""); }} placeholder="10.1038/s41586-020-2649-2" /></label>
              <p>Example: 10.1038/s41586-020-2649-2. A title, search phrase, or ordinary webpage URL will not work here.</p>
              <Button type="submit" disabled={busy}>Import DOI</Button>
              {doiError ? <Alert>{doiError}</Alert> : null}
            </form>
            <form className="scholarly-form" onSubmit={(event) => { event.preventDefault(); if (!pdf) return; let duplicate = false; void run(async () => { const imported = await importPdf(reviewId, pdfTitle.trim(), pdf); duplicate = imported.alreadyImported; setEvidenceRecord(imported.recordId); setPendingRecordFocus(imported.recordId); setPdf(null); setPdfTitle(""); setShowImport(false); }, () => duplicate ? "This PDF is already in this review. No new record was created." : "PDF imported. Screen the paper to continue."); }}>
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
          </div> : !detail?.records.length ? <p>No papers yet. Import a DOI or PDF to start this review.</p> : null}
        </section>

        <section className="scholarly-panel" aria-labelledby="flow-heading">
          <h2 id="flow-heading">Where your review stands</h2>
          {flow ? <>
            <dl className="scholarly-counts scholarly-counts-focus">
              {([ ["records_awaiting_screening", "To screen"], ["reports_awaiting_assessment", "To assess"], ["studies_included", "Included papers"] ] as const).map(([key, label]) =>
                <div key={key}><dt>{label}</dt><dd>{typeof flow[key] === "number" ? flow[key] : "—"}</dd></div>)}
            </dl>
            <details className="scholarly-manual"><summary>View all review flow counts</summary>
              <p>“Retrieved” means a PDF was marked available, not that it was fetched automatically. Identical PDF files or matching DOIs count once as an included paper; other duplicates may still need review. These counts are not a PRISMA compliance certification.</p>
              <dl className="scholarly-counts">{COUNTS.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{typeof flow[key] === "number" ? flow[key] : "—"}</dd></div>)}</dl>
            </details>
          </> : <p>No counts available yet.</p>}
        </section>

        <section className="scholarly-panel" aria-labelledby="records-heading">
          <h2 id="records-heading">Records and screening</h2>
          {detail?.records.length ? <div className="scholarly-record-list">{detail.records.map((record) => {
            const titleDecision = decisionFor(record.record_id, "title_abstract");
            const retrieval = detail.retrievals.find((item) => item.record_id === record.record_id);
            const fullDecision = decisionFor(record.record_id, "full_text");
            const artifacts = detail.artifacts.filter((item) => item.recordId === record.record_id);
            const url = record.locator_url ? safeUrl(record.locator_url) : undefined;
            const evidenceCount = detail.evidence.filter((row) => row.recordId === record.record_id).length;
            const firstPdfCopy = record.provider === "user_pdf_upload"
              ? detail.records.find((item) => item.provider === "user_pdf_upload" && item.provider_record_id === record.provider_record_id)
              : undefined;
            return <article className="scholarly-record" id={`record-${record.record_id}`} key={record.record_id}>
              <div className="scholarly-record-head"><h3>{record.title}</h3><span>{artifacts.length ? "Uploaded PDF" : "Search record"}</span></div>
              {firstPdfCopy && firstPdfCopy.record_id !== record.record_id ? <p className="scholarly-duplicate-note">This is the same PDF as <a href={`#record-${firstPdfCopy.record_id}`}>{firstPdfCopy.title}</a>. Earlier screening decisions remain in the audit; the included-paper count groups exact copies.</p> : null}
              {record.abstract ? <details><summary>Abstract</summary><p>{record.abstract}</p></details> : <p>{artifacts.length ? "Abstract details were not imported; assess the uploaded paper itself." : "No abstract supplied."}</p>}
              {artifacts[0] ? <p className="scholarly-document-status">You uploaded this PDF. Text was extracted from {artifacts[0].pageNumbers.length} {artifacts[0].pageNumbers.length === 1 ? "page" : "pages"}.</p> : null}
              {url ? <a href={url} target="_blank" rel="noopener noreferrer">Open source locator</a> : null}
              <p className="scholarly-stage-line">Screening: {titleDecision?.outcome ?? "Needs decision"} · PDF: {retrieval?.status === "retrieved" ? "Available" : artifacts.length ? "Uploaded, not yet recorded" : "Not attached"} · Full text: {fullDecision?.outcome ?? "Needs decision"} · Passages: {evidenceCount}</p>
              {titleDecision ? <p><strong>Title/abstract:</strong> {titleDecision.outcome}{titleDecision.exclusion_reason ? ` · ${titleDecision.exclusion_reason.replaceAll("_", " ")}` : ""}</p>
                : <DecisionForm reviewId={reviewId} record={record} stage="title_abstract" onSaved={() => refresh(reviewId)} />}
              {titleDecision?.outcome === "include" ? retrieval ? <p><strong>PDF availability:</strong> {retrieval.status === "retrieved" ? "Recorded for full-text assessment" : "Full text not retrieved"}</p>
                : artifacts.length === 1 ? <div className="scholarly-next-action"><p>Next: confirm that your uploaded PDF is available for full-text assessment. This does not fetch or assess the paper.</p><Button type="button" onClick={() => void run(() => saveRetrieval(reviewId, { record_id: record.record_id, status: "retrieved", source_id: artifacts[0]?.artifactId ?? null }), "Uploaded PDF recorded as available.")} disabled={busy}>Use uploaded PDF</Button></div>
                : <RetrievalForm reviewId={reviewId} recordId={record.record_id} artifacts={artifacts} onSaved={() => refresh(reviewId)} /> : null}
              {retrieval?.status === "retrieved" && !fullDecision ? <p>Next: assess the full text below. Evidence can be linked after you include it.</p> : null}
              {retrieval?.status === "retrieved" && retrieval.source_id ? fullDecision ? <p><strong>Full text:</strong> {fullDecision.outcome}</p>
                : <DecisionForm reviewId={reviewId} record={record} stage="full_text" sourceId={retrieval.source_id} onSaved={() => refresh(reviewId)} /> : null}
              {fullDecision?.outcome === "include" && retrieval?.status === "retrieved" && artifacts.some((item) => item.artifactId === retrieval.source_id) ?
                <div className="scholarly-next-action"><p>{evidenceCount ? `${evidenceCount} passage${evidenceCount === 1 ? "" : "s"} linked. Add another if needed; a matching quote is not proof that a claim is supported.` : "No passages linked yet. Read a page and select an exact passage to support your review."}</p>
                  <Button type="button" onClick={() => openEvidence(record.record_id)}>{evidenceCount ? "Add another passage" : "Add a passage"}</Button></div> : null}
              <details className="scholarly-record-details"><summary>Details</summary><p>{record.doi ? `DOI: ${record.doi}` : "DOI not linked"}</p><p>Source: {record.provider} · Record ID: {record.record_id}</p></details>
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
          {eligibleEvidenceRecords.length ? <div className="scholarly-manual">
            {!showEvidenceForm ? <Button type="button" variant="outline" onClick={() => { const first = eligibleEvidenceRecords[0]; if (first) openEvidence(first.record_id); }}>Add a source passage</Button> : null}
            {showEvidenceForm ? <>
            <h3>Read and link a passage</h3>
            <form className="scholarly-form" onSubmit={(event) => { event.preventDefault(); void run(async () => {
              if (!selectedEvidenceArtifact || !selectedPage) throw new Error("Select a retrieved PDF page first.");
              await addEvidence(reviewId, selectedEvidenceRecord, { artifactId: selectedEvidenceArtifact.artifactId, sourceId: selectedEvidenceArtifact.artifactId, claim: claim.trim(), quote: quote.trim(), pageNumber: selectedPage });
              setClaim(""); setQuote("");
            }, "Source passage linked. Claim support has not been assessed."); }}>
              <p>Read the extracted text, select an exact passage, then write the claim it relates to. A matching passage confirms the locator, not whether the claim is supported.</p>
              <label>Paper<select required value={selectedEvidenceRecord} onChange={(event) => { setEvidenceRecord(event.target.value); setPageNumber("1"); setQuote(""); setReaderText(""); setReaderLoading(true); }}>{eligibleEvidenceRecords.map((record) => <option key={record.record_id} value={record.record_id}>{record.title} ({record.record_id.slice(0, 8)})</option>)}</select></label>
              {selectedEvidenceArtifact ? <>
                <label>Extracted PDF page<select value={selectedPage ?? ""} onChange={(event) => { setPageNumber(event.target.value); setQuote(""); setReaderText(""); setReaderLoading(true); }}>
                  {availablePages.map((page) => <option key={page} value={page}>Page {page}</option>)}
                </select></label>
                <div className="scholarly-reader" role="region" aria-label={`Extracted text from PDF page ${selectedPage}`}>
                  <div className="scholarly-reader-head"><strong>Page {selectedPage}</strong><span>Extracted text, not a visual PDF</span></div>
                  {readerLoading ? <p role="status">Checking the stored PDF…</p> : readerError ? <div><Alert>{readerError}</Alert><Button type="button" variant="outline" onClick={() => { setReaderLoading(true); setReaderRetry((value) => value + 1); }}>Retry page</Button></div> : <div ref={pageTextRef} className="scholarly-page-text" onMouseUp={selectPassage} onKeyUp={selectPassage}>{readerText}</div>}
                </div>
                {selectionError ? <Alert>{selectionError}</Alert> : null}
              </> : null}
              <label>Exact quote<textarea required rows={3} maxLength={600} value={quote} onChange={(event) => setQuote(event.target.value)} placeholder="Select text above, or paste an exact passage from this page" /></label>
              <label>Claim<input required value={claim} onChange={(event) => setClaim(event.target.value)} placeholder="What does this passage help you evaluate?" /></label>
              <div className="scholarly-evidence-actions"><Button type="submit" disabled={busy || !selectedEvidenceArtifact || readerLoading || !!readerError || !readerText}>Link passage on page {selectedPage}</Button><Button type="button" variant="outline" onClick={() => setShowEvidenceForm(false)}>Close reader</Button></div>
            </form>
            </> : null}
          </div> : <p>To link a passage, include a record at title screening, mark its uploaded PDF as available, then include it at full-text assessment.</p>}
        </section>
      </> : null}
    </div>
  </WorkspaceShell>;
}
