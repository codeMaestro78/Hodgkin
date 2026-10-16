"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { WorkspaceShell } from "../../../components/workspace-shell";
import { Alert, Button, Empty } from "../../../components/workbench-ui";
import { dateLabel, safeUrl } from "../../../components/ui";
import {
  libraryError,
  libraryQuery,
  libraryRequest,
  LibraryItemSchema,
  LibraryListSchema,
  mergeLibraryItems,
  parseLibraryTags,
  ProjectListSchema,
  ProjectSchema,
  RemovedItemSchema,
  CreateProjectRequestSchema,
  OrganizeLibraryItemRequestSchema,
  type LibraryItem,
  type Project,
} from "../../../../lib/library-client";
import "../../../library.css";

function OrganizeForm({
  item,
  projects,
  onSaved,
  onCancel,
}: {
  item: LibraryItem;
  projects: Project[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [projectId, setProjectId] = useState(item.projectId ?? "");
  const [tags, setTags] = useState(item.tags.join(", "));
  const [notes, setNotes] = useState(item.notes);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    const parsed = OrganizeLibraryItemRequestSchema.safeParse({
      projectId: projectId || null,
      tags: parseLibraryTags(tags),
      notes,
    });
    if (!parsed.success) {
      setError(
        "Use up to 10 tags (40 characters each) and notes up to 2,000 characters.",
      );
      setBusy(false);
      return;
    }
    try {
      await libraryRequest(
        `/library/items/${item.id}/organize`,
        LibraryItemSchema,
        {
          method: "POST",
          body: JSON.stringify(parsed.data),
        },
      );
      onSaved();
    } catch (cause) {
      setError(libraryError(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="library-editor"
      onSubmit={save}
      aria-label={`Organize ${item.title}`}
    >
      <label>
        Project
        <select
          value={projectId}
          onChange={(event) => setProjectId(event.target.value)}
        >
          <option value="">No project</option>
          {item.projectId &&
          !projects.some((project) => project.id === item.projectId) ? (
            <option value={item.projectId}>Current project</option>
          ) : null}
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Tags
        <input
          value={tags}
          onChange={(event) => setTags(event.target.value)}
          aria-describedby={`tags-help-${item.id}`}
        />
        <small id={`tags-help-${item.id}`}>Separate tags with commas.</small>
      </label>
      <label className="library-notes">
        Notes
        <textarea
          rows={3}
          maxLength={2000}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
        />
      </label>
      {error ? <Alert>{error}</Alert> : null}
      <div className="library-actions">
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save changes"}
        </Button>
        <Button
          type="button"
          variant="quiet"
          disabled={busy}
          onClick={onCancel}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}

export default function LibraryPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectLoading, setProjectLoading] = useState(true);
  const [projectError, setProjectError] = useState("");
  const [projectRevision, setProjectRevision] = useState(0);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");
  const [projectId, setProjectId] = useState("");
  const [kind, setKind] = useState("");
  const [tag, setTag] = useState("");
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [moreLoading, setMoreLoading] = useState(false);
  const [error, setError] = useState("");
  const [moreError, setMoreError] = useState("");
  const [revision, setRevision] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const pageRequest = useRef<AbortController | null>(null);
  const filters = { query, projectId, kind, tag };
  const requestKey = `${libraryQuery(filters)}&revision=${revision}`;
  const latestKey = useRef(requestKey);
  latestKey.current = requestKey;

  useEffect(() => {
    const controller = new AbortController();
    setProjectLoading(true);
    setProjectError("");
    libraryRequest("/projects", ProjectListSchema, {
      signal: controller.signal,
    })
      .then((body) => {
        if (!controller.signal.aborted) setProjects(body.projects);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setProjectError(libraryError(cause));
      })
      .finally(() => {
        if (!controller.signal.aborted) setProjectLoading(false);
      });
    return () => controller.abort();
  }, [projectRevision]);

  useEffect(() => {
    const controller = new AbortController();
    pageRequest.current?.abort();
    setLoading(true);
    setMoreLoading(false);
    setError("");
    setMoreError("");
    setNextCursor(null);
    setEditing(null);
    const timer = setTimeout(
      () => {
        libraryRequest(
          libraryQuery({ query, projectId, kind, tag }),
          LibraryListSchema,
          { signal: controller.signal },
        )
          .then((body) => {
            if (controller.signal.aborted || latestKey.current !== requestKey)
              return;
            setItems(body.items);
            setNextCursor(body.nextCursor);
          })
          .catch((cause) => {
            if (!controller.signal.aborted && latestKey.current === requestKey)
              setError(libraryError(cause));
          })
          .finally(() => {
            if (!controller.signal.aborted && latestKey.current === requestKey)
              setLoading(false);
          });
      },
      query || tag ? 300 : 0,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
      pageRequest.current?.abort();
    };
  }, [query, projectId, kind, tag, revision, requestKey]);

  async function loadMore() {
    if (!nextCursor || moreLoading || loading) return;
    const controller = new AbortController();
    pageRequest.current = controller;
    setMoreLoading(true);
    setMoreError("");
    try {
      const body = await libraryRequest(
        libraryQuery(filters, nextCursor),
        LibraryListSchema,
        { signal: controller.signal },
      );
      if (controller.signal.aborted || latestKey.current !== requestKey) return;
      setItems((current) => mergeLibraryItems(current, body.items));
      setNextCursor(body.nextCursor === nextCursor ? null : body.nextCursor);
    } catch (cause) {
      if (!controller.signal.aborted && latestKey.current === requestKey)
        setMoreError(libraryError(cause));
    } finally {
      if (!controller.signal.aborted && latestKey.current === requestKey)
        setMoreLoading(false);
    }
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (creating || !name.trim()) return;
    setCreating(true);
    setProjectError("");
    const parsed = CreateProjectRequestSchema.safeParse({ name: name.trim() });
    if (!parsed.success) {
      setProjectError("Use a project name between 1 and 100 characters.");
      setCreating(false);
      return;
    }
    try {
      const project = await libraryRequest("/projects", ProjectSchema, {
        method: "POST",
        body: JSON.stringify(parsed.data),
      });
      setProjects((current) => [
        ...current.filter((entry) => entry.id !== project.id),
        project,
      ]);
      // Abort a project list started before this creation and reconcile from the server.
      setProjectRevision((value) => value + 1);
      setName("");
      setProjectId(project.id);
      setNotice(`Created project: ${project.name}`);
    } catch (cause) {
      setProjectError(libraryError(cause));
    } finally {
      setCreating(false);
    }
  }

  async function remove(item: LibraryItem) {
    if (removing) return;
    setRemoving(item.id);
    setNotice("");
    try {
      await libraryRequest(
        `/library/items/${item.id}/remove`,
        RemovedItemSchema,
        { method: "POST", body: "{}" },
      );
      setRevision((value) => value + 1);
      setNotice(`Removed from library: ${item.title}`);
    } catch (cause) {
      setNotice(libraryError(cause));
    } finally {
      setRemoving(null);
    }
  }

  const activeProject = projects.find((project) => project.id === projectId);
  const filtered = Boolean(query.trim() || tag.trim() || kind || projectId);
  return (
    <WorkspaceShell title="Library">
      <div className="research-library">
        <header className="library-heading">
          <h1>Library</h1>
          <p>Keep reports and sources together, organized by project.</p>
        </header>
        <div className="library-workspace">
          <aside className="library-projects" aria-label="Library projects">
            <h2>Projects</h2>
            <nav aria-label="Select a project">
              <button
                type="button"
                aria-current={!projectId ? "page" : undefined}
                onClick={() => setProjectId("")}
              >
                All saved items
              </button>
              {projects.map((project) => (
                <button
                  key={project.id}
                  type="button"
                  aria-current={projectId === project.id ? "page" : undefined}
                  onClick={() => setProjectId(project.id)}
                >
                  {project.name}
                </button>
              ))}
            </nav>
            {projectLoading ? <p role="status">Loading projects…</p> : null}
            {projectError ? (
              <Alert>
                {projectError}
                <Button
                  variant="quiet"
                  onClick={() => setProjectRevision((value) => value + 1)}
                >
                  Reload projects
                </Button>
              </Alert>
            ) : null}
            <form className="library-project-form" onSubmit={createProject}>
              <label htmlFor="library-project-name">New project</label>
              <input
                id="library-project-name"
                required
                maxLength={100}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Project name"
              />
              <Button
                type="submit"
                variant="outline"
                disabled={creating || !name.trim()}
              >
                {creating ? "Creating…" : "Create project"}
              </Button>
            </form>
          </aside>
          <section
            className="library-results"
            aria-labelledby="library-results-title"
          >
            <div className="library-results-heading">
              <h2 id="library-results-title">
                {activeProject?.name ?? "All saved items"}
              </h2>
              <Button
                variant="quiet"
                disabled={loading}
                onClick={() => setRevision((value) => value + 1)}
              >
                Refresh
              </Button>
            </div>
            <div className="library-filters">
              <label className="library-search">
                Search library
                <input
                  type="search"
                  maxLength={200}
                  value={query}
                  placeholder="Search titles and notes…"
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <label>
                Kind
                <select
                  value={kind}
                  onChange={(event) => setKind(event.target.value)}
                >
                  <option value="">Reports and sources</option>
                  <option value="report">Reports</option>
                  <option value="source">Sources</option>
                </select>
              </label>
              <label>
                Tag
                <input
                  maxLength={40}
                  value={tag}
                  placeholder="Filter by tag"
                  onChange={(event) => setTag(event.target.value)}
                />
              </label>
            </div>
            {filtered ? (
              <Button
                variant="quiet"
                onClick={() => {
                  setQuery("");
                  setTag("");
                  setKind("");
                  setProjectId("");
                }}
              >
                Clear filters
              </Button>
            ) : null}
            <p className="library-notice" role="status">
              {notice}
            </p>
            {error ? (
              <Alert>
                {error}
                <Button
                  variant="outline"
                  onClick={() => setRevision((value) => value + 1)}
                >
                  Try again
                </Button>
              </Alert>
            ) : loading ? (
              <p className="library-state" role="status">
                Loading library…
              </p>
            ) : items.length === 0 ? (
              <Empty
                title={
                  filtered ? "No matching saved items" : "Your library is ready"
                }
              >
                {filtered
                  ? "Try a different search or clear the filters."
                  : "Save a report or source from a research run to find it here."}
              </Empty>
            ) : (
              <>
                <p className="library-count">
                  {items.length} saved {items.length === 1 ? "item" : "items"}{" "}
                  shown{nextCursor ? " · More available" : ""}
                </p>
                <ul className="library-item-list">
                  {items.map((item) => {
                    const url = item.url ? safeUrl(item.url) : undefined;
                    const researchHref = `/research/${item.runId}${item.kind === "report" && item.reportVersion !== null ? `?reportVersion=${item.reportVersion}` : ""}`;
                    return (
                      <li key={item.id} className="library-item">
                        <div className="library-item-kind">
                          {item.kind === "report" ? "Report" : "Source"}
                          {item.reportVersion !== null
                            ? ` · v${item.reportVersion}`
                            : ""}
                        </div>
                        <h3>
                          <Link href={researchHref}>{item.title}</Link>
                        </h3>
                        <div className="library-item-meta">
                          <span>Saved {dateLabel(item.createdAt)}</span>
                          <span>
                            {projects.find(
                              (project) => project.id === item.projectId,
                            )?.name ??
                              (item.projectId ? "Project" : "No project")}
                          </span>
                        </div>
                        {item.tags.length ? (
                          <ul className="library-tags" aria-label="Tags">
                            {item.tags.map((value, index) => (
                              <li key={`${value}-${index}`}>{value}</li>
                            ))}
                          </ul>
                        ) : null}
                        {item.notes ? (
                          <p className="library-item-notes">{item.notes}</p>
                        ) : null}
                        <div className="library-actions">
                          <Link
                            href={
                              item.kind === "source"
                                ? `${researchHref}?sourceId=${encodeURIComponent(item.sourceId ?? "")}`
                                : researchHref
                            }
                          >
                            Open research
                          </Link>
                          {url ? (
                            <a
                              href={url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              Open source ↗
                            </a>
                          ) : null}
                          {item.kind === "report" && item.reportId ? (
                            <Link
                              href={`/research/compare?leftReportId=${item.reportId}`}
                            >
                              Compare report
                            </Link>
                          ) : null}
                          <Button
                            variant="quiet"
                            aria-expanded={editing === item.id}
                            onClick={() =>
                              setEditing(editing === item.id ? null : item.id)
                            }
                          >
                            Organize
                          </Button>
                          <Button
                            variant="quiet"
                            disabled={removing !== null}
                            onClick={() => void remove(item)}
                          >
                            {removing === item.id
                              ? "Removing…"
                              : "Remove from library"}
                          </Button>
                        </div>
                        {editing === item.id ? (
                          <OrganizeForm
                            item={item}
                            projects={projects}
                            onCancel={() => setEditing(null)}
                            onSaved={() => {
                              setEditing(null);
                              setRevision((value) => value + 1);
                              setNotice("Library changes saved.");
                            }}
                          />
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
                {moreError ? <Alert>{moreError}</Alert> : null}
                {nextCursor ? (
                  <Button
                    className="library-load-more"
                    variant="outline"
                    disabled={moreLoading}
                    onClick={() => void loadMore()}
                  >
                    {moreLoading
                      ? "Loading more…"
                      : moreError
                        ? "Retry loading more"
                        : "Load more"}
                  </Button>
                ) : null}
              </>
            )}
          </section>
        </div>
      </div>
    </WorkspaceShell>
  );
}
