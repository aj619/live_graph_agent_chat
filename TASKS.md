# TASKS: Live Graph Agent Chat

Source of truth: `PLAN_OF_ACTION.md`. Every task here maps to a section of that plan.

Rules for every task:
- Changes exactly **one file** (named in the "File" column). Tests are separate tasks with their own file.
- Does not start until its "Depends on" tasks are done.
- Is done only when its "Done when" check passes and the result is written into the phase report (plan §14).
- **The implementing agent must not run any `docker` or `docker compose` command.** Tasks marked **[OWNER]** are run by the owner.
- Tasks marked **[BLOCKED-O2]** / **[BLOCKED-O3]** wait for their open decision.

Status key: `[ ]` not started, `[x]` done.

---

## Phase 0: Decisions

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [x] T0.1 | **[OWNER]** Decide `.doc` support (O2: DOCX only, or add LibreOffice). Record in plan §2.2 | `PLAN_OF_ACTION.md` | none | O2 marked resolved |
| [ ] T0.2 | **[OWNER]** Give the concrete LLM, embedding, and agent endpoints and keys (O3). Fill them into `.env` after T1.2 exists | `.env` (owner-created) | T1.2 | `.env` contains all §5.5 and §5.6 values |
| [x] T0.3 | **[OWNER]** Say "go" to start implementation | none | T0.1 | Written instruction in chat |

---

## Phase 1: Scaffold and dependency setup

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [x] T1.0 | **[DRIVER]** Initialise the git repository on branch `main`. First commit: `PLAN_OF_ACTION.md`, `TASKS.md`, `AGENT.md`, `.claude/`. Do not commit `.claude/state/` | repository | T0.3 | `git log` shows one commit on `main` |
| [x] T1.1 | Create root ignore rules: `.env`, `.env.test`, `data/`, `.venv/`, `node_modules/`, `frontend/dist/`, `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.claude/state/`, `STATUS.md`, `FINAL_REPORT.md` | `.gitignore` | T1.0 | Patterns present; no other file touched |
| [x] T1.2 | Create `.env.example` with every variable from plan §5.1 to §5.8, including `APP_ENV=dev`. Placeholders only, with a comment above each group | `.env.example` | T0.3 | Every required variable appears exactly once |
| [x] T1.3 | Create `backend/pyproject.toml` for uv: Python `>=3.14`, `package = false`, runtime deps: fastapi, uvicorn, pydantic-settings, python-dotenv, graphiti-core, neo4j, langgraph, langchain-core, langchain-openai, langfuse, pypdf, python-docx, python-multipart, sse-starlette, **sqlalchemy, pymysql** | `backend/pyproject.toml` | T0.3 | File parses as TOML; no build section |
| [x] T1.4 | Add dev group and tool settings (pytest, pytest-asyncio, httpx, ruff, mypy) to `backend/pyproject.toml`, registering the pytest markers `integration` and `live` | `backend/pyproject.toml` | T1.3 | Only the dev group and `[tool.*]` sections added; markers listed |
| [x] T1.5 | Generate `backend/uv.lock` on Python 3.14 | `backend/uv.lock` | T1.4 | `uv lock` succeeds |
| [x] T1.6 | Create the vulnerability check script: queries OSV (`POST https://api.osv.dev/v1/query`) for each pinned PyPI or npm package in a lock file, exits non-zero on any advisory, prints a table | `scripts/check_vulns.py` | T0.3 | Flags a canary `django==3.2.0` input; passes clean on real input |
| [x] T1.7 | Run the check on `backend/uv.lock` (includes SQLAlchemy and PyMySQL) and write the result into `SECURITY_CHECK.md` | `SECURITY_CHECK.md` | T1.5, T1.6 | Zero advisories, or each handled by changing the version |
| [x] T1.8 | Create `frontend/package.json` with React, TypeScript, Vite, `@vitejs/plugin-react`, Cytoscape.js, ESLint (`eslint`, `typescript-eslint`, `eslint-plugin-react-hooks`), Vitest, Testing Library, jsdom. No axios | `frontend/package.json` | T0.3 | `npm install` succeeds; no `axios` in the tree |
| [x] T1.9 | Create `frontend/tsconfig.json` with strict mode | `frontend/tsconfig.json` | T1.8 | `npx tsc --noEmit` runs — runs and reports TS18003 "no inputs" since `frontend/src/` doesn't exist until T7.1; config itself verified sound, real compile check deferred to T7.1 ("Compiles") |
| [x] T1.10 | Create `frontend/eslint.config.js` | `frontend/eslint.config.js` | T1.8 | `npx eslint .` runs |
| [x] T1.11 | Run the check on `frontend/package-lock.json` (and `npm audit`) and append the result to `SECURITY_CHECK.md` | `SECURITY_CHECK.md` | T1.8, T1.6 | Zero advisories, or each handled |
| [x] T1.13 | Create `.env.test.example`: the test values from plan §5.9 (separate ports, `*_test` databases, `test_` graph group, test uploads path, `APP_ENV=test`), placeholders only | `.env.test.example` | T1.2 | Every §5.9 rule is reflected; no dev value copied |
| [x] T1.14 | Create the secret scan config (gitleaks format) covering the whole repository, including `.env.example` and `.env.test.example` | `.gitleaks.toml` | T1.1 | Config parses; placeholders are not flagged as findings |
| [x] T1.12 | List every container base image tag (Python 3.14, Node, nginx, neo4j 5, mysql 8.4, postgres, clickhouse, redis, minio, langfuse 4) in `SECURITY_CHECK.md`. Pinned tags, no `latest` | `SECURITY_CHECK.md` | T1.7 | Table complete |

---

## Phase 2: Backend core

### 2a. Configuration and cross-cutting modules

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [x] T2.1 | `Settings` class with every required variable from plan §5, including `APP_ENV`, MySQL, and `GRAPH_SNAPSHOT_LIMIT`. Required fields have no default. When `APP_ENV=test`, reads only `.env.test`; otherwise reads only `.env`. Never falls back from one file to the other. Exports the loaded file to `os.environ` for the Langfuse SDK | `backend/app/config.py` | T1.5 | Missing required variable raises an error naming it; a test-mode run cannot read a dev value |
| [x] T2.2 | Logging setup: key=value lines, and a filter that redacts any value equal to a secret from `Settings` | `backend/app/logging_setup.py` | T2.1 | A logged `API_TOKEN` value shows as `***` |
| [x] T2.3 | Chunking: split on paragraph boundaries, hard-split oversize paragraphs, never exceed the limit | `backend/app/chunking.py` | T1.5 | Pure function, no I/O |
| [x] T2.4 | Text extraction for PDF, TXT, DOCX with magic-byte and parser checks. Raises `UnsupportedDocument`. DOC handling follows T0.1 | `backend/app/extract.py` | T1.5, T0.1 | Each supported type extracts; wrong bytes raise |
| [x] T2.5 | Database engine: SQLAlchemy 2 engine with PyMySQL, `utf8mb4`, pooled connections, session factory built from `Settings` | `backend/app/db.py` | T2.1 | Engine URL built from settings with the password not logged |
| [x] T2.6 | Registry tables and operations: `documents` and `insertion_chunks` (plan §6.5). Methods: create document, set status and progress, record pending chunk, mark chunk inserted, list documents, list tracked chunks by document, delete document with cascade, count documents. `create_all` at startup | `backend/app/registry.py` | T2.5 | Schema created on first start; methods covered by T2.T6 |
| [x] T2.7 | Event bus: publish to all subscribers, per-subscriber bounded queue, drop a stalled subscriber without raising, keep-alive comment every 15 s | `backend/app/events.py` | T1.5 | Stream yields connected comment, events, keep-alive |
| [x] T2.8 | In-memory rate limiter keyed by API token, used for chat only | `backend/app/ratelimit.py` | T1.5 | Allows N per window, then refuses |
| [x] T2.9 | Auth dependency: compare `X-API-Token` to `API_TOKEN` with constant-time compare; 401 otherwise. Health excluded | `backend/app/auth.py` | T2.1 | Wrong or missing token returns 401 |
| [x] T2.10 | Tracing helpers: Langfuse `CallbackHandler` when `LANGFUSE_ENABLED=true`, otherwise an empty list. An `observe` wrapper that is a no-op when disabled | `backend/app/tracing.py` | T2.1 | Disabled mode attaches no callbacks |

### 2b. Graph and model clients

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [x] T2.11 | Model client factory: Graphiti's LLM client, embedder, and reranker built from `Settings`, all through OpenAI-compatible base URLs. Accepts an injected override for tests | `backend/app/models.py` | T2.1 | Returns three clients; no provider name in code |
| [x] T2.12 | `GraphService` lifecycle: construct Graphiti with `Neo4jDriver(database=...)`, `build_indices_and_constraints()` on start, `close()` on stop | `backend/app/graph.py` | T2.11 | Start and close run against a live Neo4j (T3.2) |
| [x] T2.13 | `GraphService.insert_episode(episode_uuid, name, body, source_description)`: calls `add_episode` with the caller-provided UUID, `group_id` from settings | `backend/app/graph.py` | T2.12 | Episode appears with that UUID (integration, T3.2) |
| [x] T2.14 | `GraphService.remove_episode(episode_uuid)`: calls Graphiti `remove_episode`; a missing episode is logged and treated as success | `backend/app/graph.py` | T2.12 | Missing UUID does not raise |
| [x] T2.15 | `GraphService.retrieve`: hybrid search with the cross-encoder recipe, limit from `RETRIEVAL_LIMIT`, group filter. Returns node IDs, edge IDs, facts, and the episode UUIDs of each edge | `backend/app/graph.py` | T2.13 | Returns the IDs described |
| [x] T2.16 | `GraphService.snapshot`: Cypher for `Entity` nodes and `RELATES_TO` edges filtered by group, limit from `GRAPH_SNAPSHOT_LIMIT` | `backend/app/graph.py` | T2.12, T2.1 | Returns `{nodes, edges}` with IDs matching retrieve output |

### 2c. Insertion, recovery, and document rules

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T2.17 | Insert service: one background task per upload, no queue. For each chunk: write a `pending` tracking row, call `insert_episode`, mark `inserted`, increment progress, emit `document.status` with `chunks_done` and `chunks_total`. Status `done` only when all chunks are inserted. Retries the failing chunk up to `INGEST_RETRIES`. `UnsupportedDocument` fails without retry. `@observe` on the insert function | `backend/app/insert.py` | T2.4, T2.3, T2.6, T2.7, T2.10, T2.13 | Failure on chunk 3 of 5 leaves chunks 1 and 2 `inserted` and status `failed` |
| [ ] T2.18 | Startup recovery: find documents with status `processing`; for each, remove every tracked episode (`pending` and `inserted`), delete its tracking rows, set status `interrupted` with the safe message. Idempotent; logs IDs and counts, never text | `backend/app/recovery.py` | T2.6, T2.14 | Second run is a no-op; a missing episode is skipped |
| [ ] T2.19 | Document deletion path used by the API: remove tracked episodes, delete rows, delete the stored file. Lives with recovery's removal logic but is a separate function | `backend/app/recovery.py` | T2.18 | Removes episodes, rows, and file |

Note: T2.19 changes the same file as T2.18. It runs after T2.18.

### 2d. Agent

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T2.20 | Agent state, agent LLM factory (`ChatOpenAI` from `AGENT_LLM_*`), and the `retrieve` and `grade` nodes with YES/NO parsing | `backend/app/agent.py` | T2.15, T2.10 | Grade returns False when there are no facts |
| [ ] T2.21 | Agent `rewrite` node (bounded by `AGENT_MAX_REWRITES`) and the conditional route `grade → answer | rewrite` | `backend/app/agent.py` | T2.20 | Loop stops at the limit |
| [ ] T2.22 | Agent `answer` node: publish `chat.sources` before any token, then stream `chat.token` events, answer restricted to supplied facts | `backend/app/agent.py` | T2.21, T2.7 | `chat.sources` precedes the first `chat.token` |
| [ ] T2.23 | Agent `run`: compile the LangGraph, attach callbacks from T2.10, publish `chat.done`, or `chat.error` with a generic message on failure | `backend/app/agent.py` | T2.22 | Failure publishes `chat.error` and logs the traceback |

### 2e. HTTP routes and app assembly

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T2.24 | System routes: `GET /api/health` (no auth), `GET /api/config` (limits and allowed extensions) | `backend/app/routes_system.py` | T2.9, T2.1 | Health returns 200 without token |
| [ ] T2.25 | Document routes: `GET /api/documents`; `POST /api/documents` with validation in plan §6.3 order, stores the file, creates the row, starts the insert task, returns 201; `DELETE /api/documents/{id}` calls T2.19 and returns 204 | `backend/app/routes_documents.py` | T2.9, T2.4, T2.6, T2.17, T2.19 | Limits return 409, 415, 413 |
| [ ] T2.26 | Graph route: `GET /api/graph` returns the snapshot | `backend/app/routes_graph.py` | T2.16, T2.9 | Returns `nodes` and `edges` |
| [ ] T2.27 | Chat route: `POST /api/chat` validates the body, applies the rate limiter, returns 202 with `chat_id`, runs the agent as a background task | `backend/app/routes_chat.py` | T2.23, T2.8, T2.9 | 202 with `chat_id`; 429 when rate limited |
| [ ] T2.28 | Event route: `GET /api/events` streams the bus with `text/event-stream` and `Cache-Control: no-cache` | `backend/app/routes_events.py` | T2.7, T2.9 | Streams events in order |
| [ ] T2.29 | App factory and lifespan: create `DATA_DIR/uploads`, create the database engine and tables, start the graph service, **run startup recovery before serving**, stop the graph service on shutdown, register routers, CORS from `CORS_ORIGINS`, global exception handler returning a generic 500 and logging the traceback, logging setup | `backend/app/main.py` | T2.24 to T2.28, T2.2, T2.18 | `uvicorn app.main:app` starts with a valid `.env` and fails clearly without one |
| [ ] T2.30 | Security headers middleware for API responses: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` | `backend/app/security_headers.py` | T2.1 | Headers present on every response |
| [ ] T2.31 | Wire the security headers middleware into the app factory | `backend/app/main.py` | T2.29, T2.30 | Test T2.T16 passes |
| [x] T2.32 | Package marker | `backend/app/__init__.py` | T1.5 | File exists |

---

## Phase 2 tests (backend)

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T2.T1 | Test fakes: fake graph service (in-memory episodes, `insert_episode`, `remove_episode`, `retrieve`, `snapshot`) that can be told to fail on the Nth call; fake chat model returning fixed YES/NO and tokens | `backend/tests/fakes.py` | T2.13 to T2.16, T2.20 | Used by the tests below |
| [ ] T2.T2 | Test settings: every required variable set, missing one fails | `backend/tests/test_config.py` | T2.1 | Pass |
| [ ] T2.T3 | Test logging redaction | `backend/tests/test_logging.py` | T2.2 | Pass |
| [ ] T2.T4 | Test chunking limits and boundaries | `backend/tests/test_chunking.py` | T2.3 | Pass |
| [ ] T2.T5 | Test extraction. The test builds its own sample DOCX with python-docx and a minimal PDF in memory, so no fixture files are needed. Covers bad magic bytes and empty text | `backend/tests/test_extract.py` | T2.4 | Pass |
| [ ] T2.T6 | Test registry against MySQL: CRUD, tracking rows, the `done` rule, cascade delete. Marked `integration`, skipped without `MYSQL_HOST` | `backend/tests/test_registry.py` | T2.6 | Pass when MySQL is running |
| [ ] T2.T7 | Test event bus delivery, stalled subscriber drop, keep-alive | `backend/tests/test_events.py` | T2.7 | Pass |
| [ ] T2.T8 | Test rate limiter window | `backend/tests/test_ratelimit.py` | T2.8 | Pass |
| [ ] T2.T9 | Test auth: missing, wrong, correct token; health without token | `backend/tests/test_auth.py` | T2.9 | Pass |
| [ ] T2.T10 | Test insert service: success path; failure on chunk 3 of 5 keeps chunks 1 and 2 tracked; `UnsupportedDocument` not retried; retries stop at `INGEST_RETRIES` | `backend/tests/test_insert.py` | T2.17, T2.T1 | Pass |
| [ ] T2.T11 | Test recovery: a `processing` document with one `pending` and two `inserted` rows is cleaned (three removals, rows gone, status `interrupted`); second run safe; missing episode skipped | `backend/tests/test_recovery.py` | T2.18, T2.T1 | Pass |
| [ ] T2.T12 | Test deletion path: episodes removed, rows gone, file gone | `backend/tests/test_delete.py` | T2.19, T2.T1 | Pass |
| [ ] T2.T13 | Test agent: `chat.sources` before first token; rewrite loop stops at `AGENT_MAX_REWRITES`; failure publishes `chat.error` | `backend/tests/test_agent.py` | T2.23, T2.T1 | Pass |
| [ ] T2.T14 | Test document routes: each validation step and status code | `backend/tests/test_routes_documents.py` | T2.25, T2.T1 | Pass |
| [ ] T2.T15 | Test system, graph, and chat routes | `backend/tests/test_routes_other.py` | T2.24, T2.26, T2.27, T2.T1 | Pass |
| [ ] T2.T16 | Test security headers on API responses | `backend/tests/test_security_headers.py` | T2.31 | Pass |
| [ ] T2.T17 | Test SSE route yields events in order over an async client | `backend/tests/test_routes_events.py` | T2.28, T2.T1 | Pass |
| [ ] T2.T18 | Test app startup: missing variable fails, valid settings create `DATA_DIR/uploads`, recovery runs before the first request | `backend/tests/test_main.py` | T2.29 | Pass |
| [ ] T2.T19 | Test the global exception handler returns a generic 500 without a traceback | `backend/tests/test_main_errors.py` | T2.29 | Pass |
| [ ] T2.T20 | Test-environment guard, as a pytest fixture applied to every `integration` test: refuses to run unless `APP_ENV=test`, database names end in `_test`, and the graph group starts with `test_`. Integration tests that find no test stack are reported as "not verified" | `backend/tests/conftest.py` | T2.1, T1.13 | A run with dev settings stops with a clear error; a test-settings run proceeds |

---

## Phase 3: Integration, backend container, Neo4j and MySQL

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T3.1 | Backend Dockerfile: Python 3.14 base (tag from T1.12), install from the lock with uv, run `uvicorn app.main:app --workers 1`, non-root user | `backend/Dockerfile` | T1.7, T2.29 | Single worker enforced |
| [ ] T3.2 | Integration test for graph: insert one fixture episode with fake model clients against real Neo4j, retrieve, snapshot, remove. Marked `integration`, skipped without `NEO4J_URI` | `backend/tests/test_graph_integration.py` | T2.16, T2.T1 | Passes when Neo4j runs |
| [ ] T3.3 | Compose root: `docker-compose.yml` with `include:` for each fragment, one shared network, named volumes list | `docker-compose.yml` | T1.12 | YAML parses (checked with a YAML parser) |
| [ ] T3.4 | Compose fragment for Neo4j 5 (ports on `127.0.0.1`, data volume, healthcheck) | `compose/neo4j.yml` | T3.3 | YAML parses |
| [ ] T3.5 | Compose fragment for MySQL 8.4 (ports on `127.0.0.1`, data volume, healthcheck with `mysqladmin ping`, database and user from `.env`) | `compose/mysql.yml` | T3.3 | YAML parses |
| [ ] T3.5b | Compose fragment for Ollama (D24 default provider): pinned `ollama/ollama` tag, ports on `127.0.0.1`, data volume for pulled models, healthcheck | `compose/ollama.yml` | T3.3 | YAML parses |
| [ ] T3.6 | Compose fragment for Langfuse data services: postgres, clickhouse, redis, minio, with healthchecks and localhost-only ports | `compose/langfuse-data.yml` | T3.3 | YAML parses |
| [ ] T3.7 | Compose fragment for Langfuse app services: `langfuse-web` (port 3000) and `langfuse-worker` | `compose/langfuse-app.yml` | T3.6 | YAML parses; env names match upstream |
| [ ] T3.8 | Compose fragment for the backend: build from T3.1, `env_file: .env`, `DATA_DIR` volume, depends on Neo4j and MySQL healthy, localhost port 8000 | `compose/backend.yml` | T3.1, T3.4, T3.5 | YAML parses |
| [ ] T3.9 | **[OWNER]** Start the test stack (`docker compose -p lgac-test --env-file .env.test up -d neo4j mysql`), then run `APP_ENV=test uv run --env-file ../.env.test pytest -m integration`. Dev stack is not touched | none | T3.2, T2.T6, T2.T20, T3.4, T3.5 | Owner reports pass, with the skipped count |
| [ ] T3.10 | **[OWNER]** Confirm dev data is unchanged after the test run: document count and graph node count match the values recorded before it | none | T3.9 | Owner reports matching counts |

---

## Phase 4: Restart recovery proof

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T4.1 | **[OWNER]** Start the stack. Upload a large text file, stop the backend while it is `processing`, start the backend again | none | T8.1 | Owner reports the restart |
| [ ] T4.2 | **[OWNER]** Check that the document shows `interrupted`, that its nodes and edges are gone from the graph view, and that the MySQL tracking rows for it are gone | none | T4.1 | Owner confirms, with the log lines |
| [ ] T4.3 | **[OWNER]** Delete the interrupted document and upload it again. Confirm it completes | none | T4.2 | Owner confirms |

---

## Phase 5: Agent verification

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T5.1 | Agent test against the real agent model endpoint, marked `live` and skipped without `AGENT_LLM_BASE_URL` | `backend/tests/test_agent_live.py` | T2.23 | Pass when run with real endpoint |
| [ ] T5.2 | **[OWNER]** Ask one question in the running app and confirm an agent trace appears in Langfuse | none | T6.4 | Owner reports trace seen |

---

## Phase 6: Langfuse self-hosted

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T6.1 | **[OWNER]** Start Langfuse data services and app: `docker compose up -d postgres clickhouse redis minio langfuse-web langfuse-worker` | none | T3.6, T3.7 | Owner opens `http://localhost:3000` |
| [ ] T6.2 | **[OWNER]** Create the Langfuse account, organisation, project, and API keys in the UI. Put the public and secret keys into `.env` | `.env` | T6.1 | Keys set |
| [ ] T6.3 | **[OWNER]** Confirm Langfuse health (`/api/public/health` returns OK) | none | T6.1 | Owner reports OK |
| [ ] T6.4 | **[OWNER]** Upload one document and confirm an insertion trace appears | none | T8.1, T6.2 | Owner reports trace seen |

---

## Phase 7: Frontend

### 7a. Typed contract and data layer

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T7.1 | TypeScript types for documents (with `chunks_done`, `chunks_total`, and status values including `interrupted`), config, graph snapshot, and each SSE payload from plan §6.2 | `frontend/src/types.ts` | T1.9 | Compiles |
| [ ] T7.2 | REST client with `fetch` and relative `/api` paths: `getConfig`, `listDocuments`, `uploadDocument`, `deleteDocument`, `getGraph`, `sendChat`. Non-2xx maps to a typed error | `frontend/src/api.ts` | T7.1 | Compiles; no axios import |
| [ ] T7.3 | SSE parser over a `ReadableStream`: handles chunks split mid-line, multiple events per chunk, comment lines | `frontend/src/sse.ts` | T7.1 | Pure over a stream |
| [ ] T7.4 | Event stream hook: opens `GET /api/events` with the fetch reader, reconnects with exponential backoff, calls a handler per event | `frontend/src/useEventStream.ts` | T7.3, T7.2 | Reconnects after a dropped stream |
| [ ] T7.5 | Pure reducer for documents (with progress), graph, chat messages, highlight IDs | `frontend/src/state.ts` | T7.1 | Covered by T7.T2 |
| [ ] T7.6 | Upload pre-check: size, extension, count against `/api/config` before any request | `frontend/src/limits.ts` | T7.1 | Rejects oversize and wrong type |
| [ ] T7.7 | Highlight selector: pure function from `chat.sources` IDs to node and edge classes | `frontend/src/graphHighlight.ts` | T7.1 | Covered by T7.T3 |

### 7b. Components

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T7.8 | `FileList`: upload with `accept` from config, table with name, size, status badge, progress, delete | `frontend/src/components/FileList.tsx` | T7.6, T7.5 | Renders each status including `interrupted` |
| [ ] T7.9 | `GraphView`: Cytoscape canvas, incremental updates keeping positions, fit and re-layout, highlight classes | `frontend/src/components/GraphView.tsx` | T7.7, T7.5 | Existing node positions unchanged after an update |
| [ ] T7.10 | `ChatWidget`: messages, input, streamed tokens, source list, click-to-highlight. Plain-text rendering only | `frontend/src/components/ChatWidget.tsx` | T7.2, T7.5, T7.7 | Injected `<script>` renders as text |
| [ ] T7.11 | `App` layout: three columns, wires the event hook, reducer, and components. Reloads documents and graph on reconnect | `frontend/src/App.tsx` | T7.4, T7.8, T7.9, T7.10 | Three panels rendered |
| [ ] T7.12 | Entry point mounting `App` | `frontend/src/main.tsx` | T7.11 | `npm run build` succeeds |
| [ ] T7.13 | HTML shell: title from `VITE_APP_TITLE`, strict CSP meta tag | `frontend/index.html` | T1.8 | Build output contains the CSP |
| [ ] T7.14 | Styles: three columns collapsing at phone width, 16px gutter, no horizontal page scroll, status and highlight colour tokens | `frontend/src/styles.css` | T7.11 | Usable at 390px width |

### 7c. Dev proxy and frontend container

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T7.15 | Vite config: dev server 5173, `/api` proxy to `http://localhost:8000` injecting `X-API-Token` from the repo `.env` via `loadEnv`. Build does not read the token | `frontend/vite.config.ts` | T1.8 | Dev proxy forwards with header |
| [ ] T7.16 | Nginx template: serve `dist`, proxy `/api` to `backend:8000`, inject `X-API-Token: ${API_TOKEN}`, security headers (nosniff, no-referrer, CSP), SPA fallback | `frontend/nginx.conf.template` | T7.12 | Renders with the official nginx template mechanism (owner checks in T8.1) |
| [ ] T7.17 | Frontend multi-stage Dockerfile: Node build, nginx serve, template copied to `/etc/nginx/templates/` | `frontend/Dockerfile` | T7.16, T1.12 | Base tags pinned |
| [ ] T7.18 | Compose fragment for the frontend: build from T7.17, port 5173 to nginx 8080, `API_TOKEN` via `env_file` | `compose/frontend.yml` | T7.17, T3.3 | YAML parses |

### 7d. Frontend tests

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T7.T1 | Test `api.ts` error mapping and paths with mocked fetch | `frontend/tests/api.test.ts` | T7.2 | Pass |
| [ ] T7.T2 | Test the reducer for each event type, including progress | `frontend/tests/state.test.ts` | T7.5 | Pass |
| [ ] T7.T3 | Test the highlight selector: only IDs in `chat.sources` marked | `frontend/tests/graphHighlight.test.ts` | T7.7 | Pass |
| [ ] T7.T4 | Test the SSE parser: split chunks, multiple events, comments | `frontend/tests/sse.test.ts` | T7.3 | Pass |
| [ ] T7.T5 | Test the upload pre-check against each limit | `frontend/tests/limits.test.ts` | T7.6 | Pass |
| [ ] T7.T6 | Test `ChatWidget` renders injected HTML as text | `frontend/tests/ChatWidget.test.tsx` | T7.10 | Pass |

---

## Phase 8: Full stack assembly

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T8.1 | **[OWNER]** Start backend and frontend: `docker compose up -d --build backend frontend`, open `http://localhost:8080`, confirm the file list loads | none | T7.18, T3.8, T3.5, T3.4 | Owner reports the page loads |
| [ ] T8.2 | Confirm the `API_TOKEN` value does not appear in `frontend/dist` (read-only check) | none | T7.15 | Zero matches |

---

## Phase 9: Hardening

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T9.1 | Server-side upload limit tests with real sizes (one byte over, exact limit, count at max) | `backend/tests/test_upload_limits.py` | T2.25 | Pass |
| [ ] T9.2 | **[OWNER]** Upload oversize, wrong-type, and over-count files in the browser, confirm rejections | none | T8.1 | Owner reports rejections |
| [ ] T9.3 | Read-only check: after a full run, grep the backend logs for `API_TOKEN`, key values, and document text | none | T8.1 | Zero matches |
| [ ] T9.4 | Secret scan over the full repository history with the config from T1.14, before any push. Any finding stops the push | none | T1.14 | Zero findings |

---

## Phase 10: Documentation

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T10.1 | README: overview, architecture diagram, repository layout | `README.md` | T8.1 | Sections present |
| [ ] T10.2 | README: `.env` variable table with required and optional flags | `README.md` | T10.1 | Matches `.env.example` |
| [ ] T10.3 | README: owner command sequence from plan §8.2, reset commands | `README.md` | T10.1 | Matches plan §8.2 |
| [ ] T10.4 | README: known limitations (single process, shared token reachable through the UI, embedding dimension fixed, restart behaviour: interrupted documents are cleaned on next boot and must be re-uploaded) | `README.md` | T10.1 | Each limitation listed |

---

## Phase 11: Acceptance (owner-verified, plan §13)

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T11.1 | **[OWNER]** `.env.example` covers every variable; the app refuses to start with a required variable missing | none | T1.2, T2.1 | Owner confirms |
| [ ] T11.2 | Read-only check: grep source for hard-coded model names, endpoint URLs, and numeric limits outside tests and `config.py` | none | T2.29 | Zero matches |
| [ ] T11.3 | **[OWNER]** Change `LLM_MODEL` in `.env`, restart backend, confirm behaviour changes with no code edit | none | T8.1 | Owner confirms |
| [ ] T11.4 | **[OWNER]** Upload PDF, TXT, DOCX; each shows live status and progress, nodes appear without refresh | none | T8.1 | Owner confirms |
| [ ] T11.5 | **[OWNER]** Ask a question; answer streams token by token | none | T8.1 | Owner confirms |
| [ ] T11.6 | **[OWNER]** Source nodes and edges for that answer are highlighted | none | T11.5 | Owner confirms |
| [ ] T11.7 | **[OWNER]** Delete a document; its nodes and edges disappear without refresh | none | T11.4 | Owner confirms |
| [ ] T11.8 | **[OWNER]** Restart during an upload: document shows `interrupted`, partial graph data gone | none | T4.2 | Owner confirms |
| [ ] T11.9 | **[OWNER]** Insertion and agent traces visible in Langfuse | none | T6.4, T5.2 | Owner confirms |
| [ ] T11.10 | Re-run the vulnerability check on the final `backend/uv.lock` and `frontend/package-lock.json`, update `SECURITY_CHECK.md` | `SECURITY_CHECK.md` | all dependency tasks | Zero advisories |
| [ ] T11.11 | **[OWNER]** Clean machine: follow the README only, confirm the stack starts | none | T10.4 | Owner confirms |

---

## Phase 12: Final report

| ID | Task | File | Depends on | Done when |
|---|---|---|---|---|
| [ ] T12.1 | Final report: files changed, owner commands, vulnerability results, deviations, open questions | `FINAL_REPORT.md` | T11.1 to T11.11 | Covers plan §14 items |

---

## Phase checks (assigned by the driver at each phase boundary)

These are not built by a worker. The driver assigns them when the phase's buildable tasks are merged, as the orchestrator playbook says.

| ID | Check | Agent | Scope | Depends on | Done when |
|---|---|---|---|---|---|
| [ ] C2.1 | Backend coverage check against plan §10.1 and §13 | test-author | `backend/tests/` and `backend/app/` | all Phase 2 tasks merged | Use-case table written to the run file, with no silent gaps |
| [ ] C2.2 | Security review of the backend core | security-reviewer | `backend/app/` | all Phase 2 tasks merged | Findings written to the run file |
| [ ] C7.1 | Frontend coverage check against plan §10.2 | test-author | `frontend/tests/` and `frontend/src/` | all Phase 7 tasks merged | Use-case table written to the run file |
| [ ] C7.2 | Security review of the frontend | security-reviewer | `frontend/` | all Phase 7 tasks merged | Findings written to the run file |
| [ ] C8.1 | Security review of container and proxy config | security-reviewer | `compose/`, `frontend/nginx.conf.template`, `frontend/Dockerfile`, `backend/Dockerfile` | Phase 8 tasks merged | Findings written to the run file |

Phase-check findings become new tasks for the owning builder, listed in `STATUS.md`.

## Critic review of this task list

Checked against the revised plan. Gaps found and fixed:

1. **No leftover state.** The `backend/` folder created during planning and all scratch files were deleted. The project now holds only the planning documents and `.claude/`.
2. **Crash between a Graphiti write and its record.** Fixed by writing the `pending` tracking row before the Graphiti call, using a UUID the app generates (plan §6.5, T2.17). Without this, a crash after the write but before recording would leave untracked data.
3. **Recovery itself can crash.** Fixed: recovery is idempotent and runs on every boot, and rows are deleted only after removal is attempted (plan §6.5, T2.18).
4. **Missing-episode errors on removal.** Fixed: `remove_episode` treats a missing episode as success (T2.14).
5. **Recovery ordering.** Fixed: recovery runs in lifespan before the server accepts requests (T2.29, T2.T18).
6. **Concurrency setting removed.** `INGEST_CONCURRENCY` was dropped with the queue. Uploads run as background tasks, as you asked (plan D18, §5.2).
7. **Status values changed.** `queued` is removed. `interrupted` is added, and progress fields are included in events and the UI (T7.1, T7.8).
8. **MySQL dependencies and containers.** Added SQLAlchemy and PyMySQL (T1.3, T1.7), the database engine and registry modules (T2.5, T2.6), and the MySQL compose fragment (T3.5). Stop and reset commands now remove the MySQL volume too.
9. **Owner recovery proof.** Added Phase 4 (T4.1 to T4.3) and acceptance item T11.8. The plan's Phase 4 is now the recovery proof.
10. **Security headers task.** Plan §9.3 says the backend sends `nosniff` and `no-referrer`, so T2.30 and T2.31 cover this, separately from nginx.
11. **Test coverage.** Each module in the plan has a test task, and the recovery and insertion rules have tests of their own (T2.T10 to T2.T12).

Resolved, carried into the plan as decisions (no longer open):
- **O2 → D23 (`.doc` support)**: DOCX only. T2.4 extracts PDF/TXT/DOCX and raises on anything else; no DOC branch.
- **O3 → D24 (provider endpoints and keys)**: self-hosted Ollama is the `.env.example` default (T1.2), with an `ollama` compose service (T3.5b). The owner can still override to a hosted provider in their own `.env`; T0.2 (copying `.env.example` to `.env`) is still an owner action.

Still open, not solved by tasks:
- **Embedding dimension** is fixed by Graphiti. Changing the embedding model needs a fresh Neo4j volume. Listed as a limitation in T10.4.
- **MySQL schema changes** have no migration path in this scope. A change means dropping the MySQL volume, as stated in plan §6.7.
