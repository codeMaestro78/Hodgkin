# Multi-Agent Deep Research Assistant — Documentation

> **Source of truth:** This documentation set is derived from the project's
> *Multi Agent Deep Research Assistant Technical Architecture Blueprint*
> ("the blueprint"). Where this documentation and the blueprint appear to
> disagree, the blueprint wins — file an issue rather than silently
> reconciling.
>
> **Repository status:** No source repository was available for inspection
> when this documentation was generated. Every repository-specific path,
> command, or configuration value below is therefore marked `PROPOSED`,
> `PLANNED`, or `TODO: verify repository path` rather than presented as
> confirmed fact. See [agent.md](./agent.md) for the full policy on how to
> resolve these markers as the real repository comes online.

## What this system does

The Multi-Agent Deep Research Assistant is a research command center: a user
submits a difficult question, watches a bounded team of research agents work
in real time, inspects every source and claim, and receives a
citation-grounded report with a transparent evidence trail.

It is **not** a chatbot with search tool calls bolted on. It is a
supervisor/worker execution graph with bounded reflection, an evidence
pipeline that turns untrusted web content into verified atomic claims, and a
console-style UI that exposes the system's reasoning process rather than
hiding it behind a single streaming text box.

## Core architecture (one paragraph)

[LangGraph](./langgraph.md) owns lifecycle orchestration end to end —
checkpointing, retries, budgets, interruption, and streaming. An
orchestrator (`planner`) decomposes a question into bounded sub-questions,
which are fanned out to `research_worker` nodes that call a
[provider router](./provider-routing.md) (Serper, Tavily, Parallel, or a
browser fallback). Raw provider output is never placed in shared graph
state — it is [distilled](./evidence-system.md) into atomic claims and
[verified](./citation-verification.md) before a bounded
[reflector](./reflection.md) decides whether to continue, synthesize, or
declare the research incomplete. A `writer` node produces a report from
verified evidence only, and a `quality_gate` rejects anything with
unsupported citations before the [event stream](./events-and-sse.md)
notifies the [frontend](./frontend.md) that the run is complete. CrewAI, if
used, is an optional in-node worker implementation — it never becomes a
second parent orchestrator.

## Documentation map

| Area | File | Audience |
|---|---|---|
| Start here | [README.md](./README.md) | Everyone |
| System design | [architecture.md](./architecture.md) | Engineers, architects |
| **AI coding agent instructions** | [agent.md](./agent.md) | AI coding agents (Claude Code, Codex, etc.) |
| End-to-end lifecycle | [research-workflow.md](./research-workflow.md) | Engineers, QA |
| Orchestration engine | [langgraph.md](./langgraph.md) | Backend engineers |
| Node/agent roles | [agents.md](./agents.md) | Backend engineers |
| Search/browser routing | [provider-routing.md](./provider-routing.md) | Backend engineers |
| Worker specialization | [research-workers.md](./research-workers.md) | Backend engineers |
| Evidence pipeline | [evidence-system.md](./evidence-system.md) | Backend engineers |
| Citation correctness | [citation-verification.md](./citation-verification.md) | Backend engineers, QA |
| Bounded reflection loop | [reflection.md](./reflection.md) | Backend engineers |
| State & contracts | [state-management.md](./state-management.md) | Backend/frontend engineers |
| HTTP API | [api.md](./api.md) | Frontend/backend engineers |
| Event streaming | [events-and-sse.md](./events-and-sse.md) | Frontend/backend engineers |
| PostgreSQL schema | [database.md](./database.md) | Backend engineers, DevOps |
| Redis usage | [redis.md](./redis.md) | Backend engineers, DevOps |
| Raw content storage | [artifact-storage.md](./artifact-storage.md) | Backend engineers, DevOps |
| Next.js app | [frontend.md](./frontend.md) | Frontend engineers |
| Visual/UX spec | [ui-ux.md](./ui-ux.md) | Frontend engineers, designers |
| Auth/tenancy/secrets | [security.md](./security.md) | Security engineers |
| Untrusted web content | [prompt-injection.md](./prompt-injection.md) | Security engineers |
| Failure handling | [reliability.md](./reliability.md) | Backend engineers, DevOps |
| Tracing & metrics | [observability.md](./observability.md) | DevOps, QA |
| Quality benchmark | [evaluation.md](./evaluation.md) | QA, ML engineers |
| Test strategy | [testing.md](./testing.md) | QA, engineers |
| Production rollout | [deployment.md](./deployment.md) | DevOps |
| All config values | [configuration.md](./configuration.md) | DevOps, engineers |
| Local dev setup | [development.md](./development.md) | New engineers |

## Recommended reading order

1. **README.md** (this file) — orientation.
2. **[architecture.md](./architecture.md)** — the system as a whole.
3. **[research-workflow.md](./research-workflow.md)** — what happens during one run.
4. **[langgraph.md](./langgraph.md)** + **[agents.md](./agents.md)** — how the graph is built.
5. **[evidence-system.md](./evidence-system.md)** + **[citation-verification.md](./citation-verification.md)** + **[reflection.md](./reflection.md)** — why the system is trustworthy.
6. **[state-management.md](./state-management.md)** + **[api.md](./api.md)** + **[events-and-sse.md](./events-and-sse.md)** — the contracts everything else depends on.
7. Everything else, as needed for your role.
8. If you are an AI coding agent about to modify code: read **[agent.md](./agent.md)** in full before touching anything.

## Local development entry point

See [development.md](./development.md) for prerequisites, environment setup,
and run commands. **No commands in that file have been verified against a
real repository** — treat them as a proposed starting point (`PROPOSED`)
until confirmed against `package.json` / `pyproject.toml` / a Makefile in
the actual codebase.

## Architecture principles

These are load-bearing and must not be silently changed by any future
implementation work (see [agent.md](./agent.md) for the enforceable version
of this list):

- LangGraph is the only lifecycle orchestrator.
- The primary topology is orchestrator-worker with **bounded** reflection.
- CrewAI, if used, is an optional bounded worker implementation — never a
  second parent orchestrator.
- TypeSafe AI Jev makes typed probabilistic judgments; it does not replace
  Zod/Pydantic validation and does not enforce safety by itself.
- Raw web content never enters global graph state — only compact, verified
  projections do.
- Research is evidence-first: claims must be verified before the writer can
  use them.
- Reflection is bounded by hard, deterministic limits.
- Provider routing is explicit and rule-driven, not "call everything."
- PostgreSQL is the durable state store; Redis is ephemeral coordination
  only.
- Large raw artifacts (HTML, PDFs, provider payloads) live outside
  PostgreSQL, in object storage.
- SSE events are persisted before they are published, and are replayable.
- The system is multi-tenant end to end.
- Web content is always treated as untrusted data, never as instructions.
- The writer operates only on verified evidence.
- The whole system must be bounded, evidence-first, and replayable.

## Important constraints

- Do not remove the bounded-reflection hard limits (`maxReflectionRounds`,
  `maxSearchCalls`, etc.) — see [reflection.md](./reflection.md).
- Do not let a worker (LangGraph or CrewAI) write directly to global
  `ResearchState` — see [state-management.md](./state-management.md).
- Do not let the writer consume unverified `EvidenceClaim` records — see
  [citation-verification.md](./citation-verification.md).
- Do not treat retrieved web content as instructions — see
  [prompt-injection.md](./prompt-injection.md).
- Do not use Redis as the source of truth for run state — see
  [redis.md](./redis.md).
