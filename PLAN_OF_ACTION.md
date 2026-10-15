# Plan of Action: Live Graph Agent Chat

Status: **Planning only. No implementation is approved yet.**
Gate: do not start any phase until the owner records "go".

Scope level: **portfolio project.** Security means sensible defaults and basic hygiene (token-protected API, upload validation, no secrets in the repository or the browser, parameterised SQL). Production hardening is out of scope: no formal threat model, no compliance work, no multi-tenant isolation, no load testing.

Document purpose: this file is the specification for a sub-agent that will implement the app later. Every decision marked **Decided** is final unless the owner changes it. Every item marked **Open** must be resolved before the phase that depends on it.

---

## 1. Goal

A portfolio web app. The user uploads documents (PDF, TXT, DOCX). Each document is inserted into a temporal knowledge graph built with **Graphiti** on **Neo4j**. A chat agent answers questions by graph retrieval (GraphRAG). The UI highlights the graph nodes and edges that supplied each answer. Everything updates live with no page refresh.

---

## 2. Decisions

### 2.1 Decided

| # | Area | Decision |
|---|---|---|
| D1 | Graph engine | Graphiti (`graphiti-core`), backed by Neo4j 5. Graphiti is the only ingestion path |
| D2 | Language | Python 3.14 |
| D3 | Package manager | uv (`pyproject.toml` + `uv.lock`) |
| D4 | Agent orchestration | LangGraph |
| D5 | Tracing | Langfuse, **self-hosted** in Docker Compose |
| D6 | Backend API | FastAPI + Uvicorn, **single worker process** (in-memory event bus) |
| D7 | Frontend | React + TypeScript + Vite + Cytoscape.js |
| D8 | HTTP client in frontend | Native `fetch`. **Do not use axios** |
| D9 | Real-time channel | Server-Sent Events (SSE) over `fetch` streaming (not `EventSource`, because the token must be sent as a header) |
| D10 | Model choice | **Implementation must not change with the model.** Every LLM and embedding call goes through an OpenAI-compatible HTTP endpoint whose base URL, key and model name come from `.env` |
| D11 | Configuration | All endpoints, keys, model names, limits, and security values live in `.env`. No defaults in code for these values. The app fails fast at startup if one is missing |
| D12 | Secrets | `.env` is git-ignored. `.env.example` is committed with placeholders only. No secret is ever sent to the browser |
| D13 | Access control | Single shared `API_TOKEN` in `.env`. All `/api` routes except health require it. The browser never sees it (section 6.4) |
| D14 | Vulnerability policy | No package or version listed in a known-vulnerability database may be used. Check is mandatory before pinning (section 9) |
| D15 | Containers | Docker Compose. The sub-agent **must not run any `docker` command**. It writes the compose files and a list of commands for the owner to run |
| D16 | Live graph delta | When a document finishes inserting, the backend emits `graph.changed`. The frontend re-fetches the graph snapshot. No polling |
| D17 | Document registry | **MySQL 8.4 LTS** holds the document table and the insertion-tracking table (section 6.5) |
| D18 | Insertion model | No batching and no job queue. Each upload is inserted in-process as a background task of the server, and finishes on completion. Status is pushed to the browser as it changes |
| D19 | Restart recovery | A document whose insertion did not finish is detected at startup. Its graph data is removed on the next boot, and the document is marked `interrupted` (section 6.5) |
| D20 | Test environment | Tests never touch dev data. Test runs use a separate stack (own compose project, ports, volumes, databases, and Langfuse project) configured by `.env.test`. A guard refuses integration runs against dev settings (section 5.9) |
| D21 | Headless agents | Sub-agents run non-interactively. Each task is self-contained: the driver's brief carries the task row, the plan excerpts, the file, and the done check, so no agent needs chat history. All five worker agents are pinned to Haiku 5.5 in their definitions. The driver runs on Sonnet 5.5. Tasks are written so they do not depend on the model family |
| D22 | Secret scanning | A secret scanner runs before every push (section 9.4) |
| D23 | Legacy `.doc` support (resolves O2) | **DOCX only.** No LibreOffice, no `.doc` support |
| D24 | Default providers (resolves O3) | **Self-hosted Ollama**, run as a compose service (`ollama`, section 8.1), used for `LLM_*`, `EMBEDDING_*`, and `AGENT_LLM_*` alike. This is the documented, verified-working pattern for Graphiti against an OpenAI-compatible local server (Zep's own Ollama integration guide: `OpenAIGenericClient` + `OpenAIEmbedder`, both pointed at `http://ollama:11434/v1`), and it needs no external key. `.env.example` ships these as the working example (dummy `LLM_API_KEY`/`EMBEDDING_API_KEY`, since Ollama ignores the key field). The owner may still override any of the six endpoints in their own `.env` to point at OpenAI or another hosted OpenAI-compatible service instead — nothing in the code changes either way (D10) |

Anthropic note for D24: Anthropic has no embeddings API, and Graphiti's structured-output calls need `OpenAIGenericClient` (schema injected into the prompt) rather than the plain `OpenAIClient`, for any non-OpenAI OpenAI-compatible endpoint, Ollama included.

---

## 3. Scope

### 3.1 In scope
- Upload, list, delete documents (PDF, TXT, DOCX only — no legacy `.doc`, per D23)
- Text extraction with server-side type and size checks
- Insertion into Graphiti, with per-chunk tracking in MySQL
- Startup recovery of interrupted insertions
- Live graph view with per-answer highlighting
- LangGraph agent: retrieve, grade, rewrite (bounded), answer (streamed), cite
- Langfuse traces for every insertion and every agent run
- Docker Compose for Neo4j, MySQL, Langfuse (full self-hosted stack), backend, frontend
- Automated tests (section 10)

### 3.2 Out of scope
- Multi-user accounts or per-user graphs (one workspace)
- OCR for scanned PDFs
- Manual editing of graph nodes or edges
- Production hosting, TLS certificates, cloud deployment
- Horizontal scaling (the event bus and background tasks are in-process)
- Batch or scheduled ingestion, and job queues

---

## 4. Architecture

```
Browser (React + Vite, fetch + SSE, Cytoscape.js)
  ├─ Left panel:   file list, upload, delete
  ├─ Center panel: graph view (nodes, edges, highlight)
  └─ Right panel:  chat widget
        │  REST (JSON)           ▲  SSE stream (text/event-stream)
        ▼                        │
Nginx (frontend container)  ── injects X-API-Token, proxies /api ──► Backend
                                                                        │
FastAPI backend (Python 3.14, uv, single process)                       │
  ├─ routes     REST routes, auth dependency, SSE endpoint              │
  ├─ config     typed settings from .env (pydantic-settings)            │
  ├─ registry   MySQL: documents and insertion tracking (SQLAlchemy)   │
  ├─ extract    PDF / TXT / DOCX to text                                │
  ├─ chunking   paragraph-aware splitting                               │
  ├─ insert     in-process background insert, status events, retries    │
  ├─ recovery   startup clean-up of interrupted insertions              │
  ├─ graph      Graphiti: add_episode, remove_episode, search_, snapshot│
  ├─ agent      LangGraph: retrieve → grade → (rewrite → retrieve)* → answer
  ├─ events     in-process fan-out bus for SSE                          │
  └─ tracing    Langfuse CallbackHandler (agent) and @observe (insert)  │
        │                                                               │
        ▼                                                               ▼
Neo4j 5 (graph store)            MySQL 8.4 (registry)     Langfuse (self-hosted)
                                                          web, worker, postgres,
                                                          clickhouse, redis, minio
```

### 4.1 Repository layout (target)

```
live_graph_agent_chat/
├─ PLAN_OF_ACTION.md
├─ TASKS.md
├─ AGENT.md
├─ .claude/                 (sub-agent definitions, orchestrator playbook, settings)
│  ├─ orchestrator.md
│  ├─ settings.json
│  ├─ agents/               backend-builder, frontend-builder, infra-docs, test-author, security-reviewer
│  └─ state/                (git-ignored) cycle lock and run files
├─ STATUS.md                (git-ignored, written by the driver each cycle)
├─ FINAL_REPORT.md          (git-ignored, written by the driver at the end)
├─ SECURITY_CHECK.md
├─ README.md
├─ .env                     (owner creates from .env.example; git-ignored)
├─ .env.example
├─ .gitignore
├─ docker-compose.yml       (root; includes compose/*.yml)
├─ compose/
│  ├─ neo4j.yml
│  ├─ mysql.yml
│  ├─ ollama.yml
│  ├─ langfuse-data.yml
│  ├─ langfuse-app.yml
│  ├─ backend.yml
│  └─ frontend.yml
├─ scripts/
│  └─ check_vulns.py        (OSV check for lock files)
├─ backend/
│  ├─ pyproject.toml        (uv; package = false)
│  ├─ uv.lock
│  ├─ Dockerfile
│  ├─ app/
│  │  ├─ __init__.py
│  │  ├─ main.py              app factory, lifespan, CORS, global error handler
│  │  ├─ config.py            Settings from .env
│  │  ├─ logging_setup.py     log format and secret redaction
│  │  ├─ auth.py              token dependency
│  │  ├─ db.py                SQLAlchemy engine and session
│  │  ├─ registry.py          documents and insertion tracking tables
│  │  ├─ extract.py           PDF / TXT / DOCX to text
│  │  ├─ chunking.py          paragraph-aware chunk splitting
│  │  ├─ models.py            Graphiti LLM, embedder, reranker factory
│  │  ├─ graph.py             GraphService: insert, remove, retrieve, snapshot
│  │  ├─ insert.py            background insertion, status events, retries
│  │  ├─ recovery.py          startup clean-up of interrupted insertions
│  │  ├─ agent.py             LangGraph nodes and run
│  │  ├─ tracing.py           Langfuse callback and observe helpers
│  │  ├─ events.py            SSE fan-out bus
│  │  ├─ ratelimit.py         chat rate limiter
│  │  ├─ security_headers.py  backend response headers
│  │  ├─ routes_system.py     health, config
│  │  ├─ routes_documents.py  list, upload, delete
│  │  ├─ routes_graph.py      graph snapshot
│  │  ├─ routes_chat.py       chat start
│  │  └─ routes_events.py     SSE stream
│  └─ tests/
└─ frontend/
   ├─ package.json
   ├─ package-lock.json
   ├─ vite.config.ts
   ├─ tsconfig.json
   ├─ eslint.config.js
   ├─ Dockerfile            (build, then nginx serve)
   ├─ nginx.conf.template   (proxies /api, injects token, security headers)
   ├─ index.html
   ├─ src/
   │  ├─ main.tsx
   │  ├─ api.ts             fetch wrappers
   │  ├─ sse.ts             SSE stream parser
   │  ├─ useEventStream.ts  connection and reconnect hook
   │  ├─ types.ts
   │  ├─ state.ts           reducer
   │  ├─ limits.ts          upload pre-checks
   │  ├─ graphHighlight.ts  highlight selector
   │  ├─ App.tsx
   │  ├─ components/FileList.tsx, GraphView.tsx, ChatWidget.tsx
   │  └─ styles.css
   └─ tests/
```

---

## 5. Configuration Contract (`.env`)

Every variable below is required unless marked optional. Code must not define defaults for values in the "Required" column.

### 5.1 Security and API
| Variable | Purpose | Notes |
|---|---|---|
| `API_TOKEN` | Shared secret for all `/api` routes except health | Generate with `openssl rand -hex 32`. Never logged |
| `CORS_ORIGINS` | Comma-separated allowed origins | Example `http://localhost:5173` |
| `APP_ENV` | `dev` or `test`. Selects which env file the settings load (section 5.9) | Required. No default |

### 5.2 Limits
| Variable | Purpose |
|---|---|
| `MAX_DOCUMENTS` | Maximum stored documents |
| `MAX_FILE_SIZE_MB` | Maximum size per upload |
| `ALLOWED_EXTENSIONS` | `pdf,txt,docx` (per D23, no `doc`) |
| `INGEST_CHUNK_CHARS` | Characters per Graphiti episode |
| `INGEST_RETRIES` | Attempts per document for transient failures |
| `AGENT_MAX_REWRITES` | Maximum query rewrites per question |
| `RETRIEVAL_LIMIT` | Results per search (applies to nodes and edges) |
| `GRAPH_SNAPSHOT_LIMIT` | Maximum nodes and maximum edges returned by `/api/graph` |
| `GRAPH_GROUP_ID` | Graphiti partition for the workspace |

### 5.3 Storage
| Variable | Purpose |
|---|---|
| `DATA_DIR` | Uploaded files directory (`uploads/`) |
| `MYSQL_HOST` | e.g. `mysql` inside compose |
| `MYSQL_PORT` | e.g. `3306` |
| `MYSQL_DATABASE` | Registry database name |
| `MYSQL_USER` | Application user |
| `MYSQL_PASSWORD` | Secret |
| `MYSQL_ROOT_PASSWORD` | Secret. Used only by the MySQL container at first start |

### 5.4 Neo4j
| Variable | Purpose |
|---|---|
| `NEO4J_URI` | e.g. `bolt://neo4j:7687` inside compose |
| `NEO4J_USER` | |
| `NEO4J_PASSWORD` | Secret |
| `NEO4J_DATABASE` | e.g. `neo4j` |

### 5.5 Extraction and embedding models (Graphiti)
| Variable | Purpose | `.env.example` default (D24) |
|---|---|---|
| `LLM_BASE_URL` | OpenAI-compatible base URL | `http://ollama:11434/v1` |
| `LLM_API_KEY` | Secret. May be a dummy value for local servers that ignore it | `ollama` (ignored) |
| `LLM_MODEL` | Model name the endpoint expects | `llama3.1` |
| `LLM_SMALL_MODEL` | Cheaper model Graphiti uses for some steps | `llama3.1` |
| `LLM_TEMPERATURE` | Usually `0` for extraction | `0` |
| `EMBEDDING_BASE_URL` | OpenAI-compatible `/embeddings` base URL | `http://ollama:11434/v1` |
| `EMBEDDING_API_KEY` | Secret | `ollama` (ignored) |
| `EMBEDDING_MODEL` | Embedding model name | `nomic-embed-text` |

Warning for the owner: the embedding vector size is a fixed constant in Graphiti (`EMBEDDING_DIM`). It is not configurable from `.env`. Switching to an embedding model with a different vector size requires clearing the Neo4j database and re-inserting all documents.

### 5.6 Agent model
| Variable | Purpose | `.env.example` default (D24) |
|---|---|---|
| `AGENT_LLM_BASE_URL` | OpenAI-compatible base URL | `http://ollama:11434/v1` |
| `AGENT_LLM_API_KEY` | Secret | `ollama` (ignored) |
| `AGENT_LLM_MODEL` | | `llama3.1` |
| `AGENT_LLM_TEMPERATURE` | | `0` |

### 5.7 Langfuse (self-hosted)
| Variable | Purpose |
|---|---|
| `LANGFUSE_ENABLED` | `true` or `false`. When `false`, no callbacks are attached |
| `LANGFUSE_HOST` | Inside compose: `http://langfuse-web:3000`. From the host: `http://localhost:3000` |
| `LANGFUSE_PUBLIC_KEY` | Created in the Langfuse UI after first start |
| `LANGFUSE_SECRET_KEY` | Secret |
| `NEXTAUTH_SECRET`, `NEXTAUTH_URL` | Langfuse web session |
| `SALT`, `ENCRYPTION_KEY` | Langfuse; `ENCRYPTION_KEY` is 64 hex characters from `openssl rand -hex 32` |
| `LANGFUSE_INIT_*` | Optional bootstrap of org, project, and admin user |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_VERSION` | Langfuse Postgres |
| `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD` | Langfuse ClickHouse |
| `REDIS_AUTH` | Langfuse Redis |
| `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Langfuse object storage |

### 5.8 Frontend (build-time, non-secret)
| Variable | Purpose |
|---|---|
| `VITE_APP_TITLE` | Browser title. Optional |

The frontend build must not read `API_TOKEN`.

---

### 5.9 Test environment (`.env.test`)

Test runs load `.env.test` instead of `.env`. The two files never share a value for any stateful service.

| Variable group | Dev (`.env`) | Test (`.env.test`) |
|---|---|---|
| Compose project | default | `lgac-test` (passed with `-p`) |
| Published host ports | defaults in `.env` | Different ports for every service (for example, Neo4j 17687, MySQL 13306, Langfuse 13000) |
| Neo4j database | `NEO4J_DATABASE` (dev name) | `NEO4J_DATABASE` set to a database whose name ends in `_test` |
| MySQL database | `MYSQL_DATABASE` (dev name) | `MYSQL_DATABASE` ending in `_test` |
| Graph group | `GRAPH_GROUP_ID` (dev value) | `GRAPH_GROUP_ID` starting with `test_` |
| Uploads directory | `DATA_DIR` (dev path) | `DATA_DIR` set to a separate test path |
| Langfuse | Dev project keys | Separate project and keys, host on the test port |
| Model endpoints | Dev values | May point at the same endpoints, since tests use fakes. Test code never calls them |

Rules:
- Every container name and every published port comes from `.env`, so the test stack can run beside the dev stack.
- Settings read only one file. `APP_ENV=test` reads `.env.test` and never reads `.env`. `APP_ENV=dev` reads `.env` and never reads `.env.test`. There is no fallback between them, so a missing test value fails loudly instead of using a dev value.
- Each stateful service uses its own named volume in each compose project, so the test stack never mounts dev data.
- Integration tests run a guard first. The guard refuses to run unless `APP_ENV=test`, the database names end in `_test`, and the graph group starts with `test_`. Any other value stops the run with a clear error. Dev data is never touched by a test run.
- Tests that need a live service skip only when the test stack is not running, and the report counts them as "not verified", not as passed.

## 6. Backend Specification

### 6.1 Endpoints

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/health` | none | Liveness |
| GET | `/api/config` | token | Limits for the UI: max documents, max size, allowed extensions |
| GET | `/api/documents` | token | List documents with status |
| POST | `/api/documents` | token | Multipart upload. Validates count, size, extension, and content. Returns 201 with the document. Insertion runs in the background of the same process |
| DELETE | `/api/documents/{id}` | token | Remove graph episodes, then file and registry rows. Returns 204 |
| GET | `/api/graph` | token | Snapshot of nodes and edges for `GRAPH_GROUP_ID` |
| POST | `/api/chat` | token | Body `{message}`. Returns 202 with `{chat_id}`. Answer streams over SSE |
| GET | `/api/events` | token | SSE stream of all events for this server |

### 6.2 SSE event types

| Event | Payload |
|---|---|
| `document.status` | `{id, status, error, chunks_done, chunks_total}`. Status values: `processing`, `done`, `failed`, `interrupted` |
| `graph.changed` | `{doc_id}`. Frontend re-fetches `/api/graph` |
| `chat.sources` | `{chat_id, node_ids, edge_ids, doc_ids, nodes, facts}` |
| `chat.token` | `{chat_id, token}` |
| `chat.done` | `{chat_id}` |
| `chat.error` | `{chat_id, message}`. Message is generic; details go to logs |

Keep-alive: send a comment line every 15 seconds.

### 6.3 Upload validation (server side, in this order)
1. Token valid
2. Document count below `MAX_DOCUMENTS` (else 409)
3. Extension in `ALLOWED_EXTENSIONS` (else 415)
4. Size: read at most `MAX_FILE_SIZE_MB` + 1 byte; reject above the limit (else 413)
5. Content check: PDF must start with `%PDF`; DOCX must open with the parser; TXT must decode as UTF-8 with replacement
6. Filename is never used as a path. Stored name is a generated UUID plus the validated extension. Original name is kept as data only

### 6.4 Token handling
- The browser never receives `API_TOKEN`.
- In production (compose), the frontend nginx container injects the header `X-API-Token` when proxying `/api`. The value comes from its environment at container start, via the official nginx template mechanism.
- In development, `vite.config.ts` proxies `/api` and injects the same header, reading the value from the repo `.env` through `loadEnv`.
- Known limitation, to be stated in the README: anyone who can reach the frontend can use the API. This is acceptable for a local portfolio app. Do not expose it publicly.

### 6.5 Insertion pipeline and tracking

**MySQL tables** (created at startup if missing):

`documents`
| Column | Notes |
|---|---|
| `id` | UUID, primary key |
| `filename` | Original name, data only |
| `stored_name` | Generated name under `DATA_DIR/uploads/` |
| `size_bytes` | |
| `status` | `processing`, `done`, `failed`, `interrupted` |
| `error` | Safe message, nullable |
| `chunks_total` | Set when chunking completes |
| `chunks_done` | Incremented after each confirmed chunk |
| `created_at` | |

`insertion_chunks` (the tracking table)
| Column | Notes |
|---|---|
| `episode_uuid` | UUID, primary key. Generated **before** the Graphiti call |
| `doc_id` | Foreign key to `documents.id`, cascade delete |
| `chunk_index` | Position in the document |
| `state` | `pending` (intent recorded, insert not confirmed) or `inserted` |

Rule: a document is `done` only when every chunk row is `inserted` and `chunks_done = chunks_total`. Anything else found at startup is an interrupted insertion.

**Insertion steps** (per upload, one background task, no queue):
1. Save the file under `DATA_DIR/uploads/<stored_name>`. Insert the `documents` row with status `processing`. Emit `document.status`.
2. Extract text (`extract.py`). Split into chunks (`chunking.py`). Set `chunks_total`.
3. For each chunk, in order:
   a. Generate `episode_uuid`. Insert an `insertion_chunks` row with state `pending`. **This row is written before the Graphiti call**, so a crash between the two steps leaves a record to clean up.
   b. Call Graphiti `add_episode` with that UUID.
   c. Set the row to `inserted`. Increment `chunks_done`. Emit `document.status` with progress.
4. When all chunks are inserted, set status `done`, emit `document.status` and `graph.changed`.
5. Content errors (`UnsupportedDocument`) set status `failed` with the safe message and stop.
6. Other errors retry the failing chunk, up to `INGEST_RETRIES` attempts. When attempts run out, status becomes `failed` with a generic message including the exception class name. Chunks already inserted stay tracked, so the user can delete the document to remove them.

**Startup recovery** (`recovery.py`, run in the app lifespan before the server accepts requests):
1. Find every document with status `processing`. These were cut off by a restart.
2. For each, call Graphiti `remove_episode` for every `insertion_chunks` row of that document, both `pending` and `inserted`. Missing episodes are logged and skipped, since a `pending` episode may never have been written.
3. Delete the `insertion_chunks` rows for that document.
4. Set the document status to `interrupted`, with error "Insertion was interrupted by a restart. Delete and upload again." It stays visible so the owner can delete it.
5. Log each cleaned document with its ID and episode count. Never log text content.

The recovery step runs on every boot, so a crash during recovery is also repaired on the next boot. Rows are only deleted after the graph removal for them has been attempted, so an interrupted recovery is retried.

Deletion via the API follows the same removal path: remove each episode, then delete the document and its tracking rows, then delete the stored file.

### 6.6 Graph operations (Graphiti)
- Startup: `build_indices_and_constraints()`
- Model clients, all OpenAI-compatible:
  - LLM: `OpenAIGenericClient` with `LLMConfig(api_key, base_url, model, small_model, temperature)`
  - Embeddings: `OpenAIEmbedder` with `OpenAIEmbedderConfig(api_key, base_url, embedding_model)`
  - Reranker: `OpenAIRerankerClient` with the same `LLMConfig`
  - Driver: `Neo4jDriver(uri, user, password, database)` passed as `graph_driver`
- `add_episode` accepts the caller's `uuid`, which is what makes the tracking in 6.5 possible.
- Retrieval: `search_` with `COMBINED_HYBRID_SEARCH_CROSS_ENCODER` copied with `limit = RETRIEVAL_LIMIT`, filtered by `group_ids=[GRAPH_GROUP_ID]`.
- Highlight mapping: each returned edge lists its source episode UUIDs. Map them to document IDs through `insertion_chunks`. Nodes are returned by ID with their names.
- Snapshot: Cypher on `Entity` nodes and `RELATES_TO` edges filtered by `group_id`, with `GRAPH_SNAPSHOT_LIMIT`.
- Deletion: `remove_episode` for every tracked episode of the document.

Verify these signatures against the installed `graphiti-core` version when implementing. They were checked against `graphiti-core` 0.31.1 during planning.

### 6.7 MySQL access
- SQLAlchemy 2.x engine with the PyMySQL driver, one connection pool, `utf8mb4` character set.
- Schema is created by the app at startup with `create_all` for these two tables. No migration tool in this scope; a schema change means dropping the MySQL volume.
- All queries use bound parameters through SQLAlchemy. No string-built SQL.

### 6.8 Agent (LangGraph)
State: `chat_id`, `question`, `query`, `rewrites`, `retrieved`, `grounded`.

Graph:
```
START → retrieve → grade ─┬─ grounded or rewrites ≥ AGENT_MAX_REWRITES → answer → END
                          └─ otherwise → rewrite → retrieve (loop)
```
- `retrieve`: graph search, as in 6.6.
- `grade`: agent LLM returns YES or NO. No facts means NO.
- `rewrite`: agent LLM returns a short search query.
- `answer`: publish `chat.sources` first, then stream tokens with `chat.token`. The system prompt tells the model to answer only from the supplied facts and to say so when they are insufficient.
- Tracing: `langfuse.langchain.CallbackHandler` in every LLM call's config, only when `LANGFUSE_ENABLED=true`.
- Failures publish `chat.error` with a generic message.

### 6.9 Tracing (Langfuse)
- Langfuse SDK reads `LANGFUSE_*` from the environment. `config.py` loads `.env` into the process environment before the SDK is first used.
- Insertion: `@observe` on the per-document insert function.
- Agent: callback handler on the graph run.
- Metadata to attach: document ID for insertion, chat ID for agent runs. No raw document text in trace metadata beyond what Langfuse records from inputs and outputs.

### 6.10 Logging and errors
- Structured log lines, no secrets. Never log `API_TOKEN`, keys, or raw uploaded content.
- Client-facing error messages are generic. Full tracebacks go to logs only.

---

## 7. Frontend Specification

### 7.1 Layout
Three columns, full viewport height.
- **Left: FileList.** Upload button (file input with `accept` set from `/api/config`). Table of documents with name, size, status badge, progress (`chunks_done / chunks_total`), delete action. Client-side pre-checks mirror the server limits, but the server is authoritative.
- **Center: GraphView.** Cytoscape.js canvas. Nodes labelled with entity name. Edges labelled with relation name, with the fact on hover or selection. Toolbar: fit, re-layout, reload snapshot.
- **Right: ChatWidget.** Message list, input box, send. Streams the assistant reply token by token. Lists the source facts under each answer. Clicking a source highlights it.

### 7.2 Real-time behaviour
- One SSE connection per browser tab, opened on load, reconnects with backoff on failure.
- `document.status` updates the file list in place, including progress.
- `graph.changed` re-fetches `/api/graph`. Cytoscape updates with the new elements and keeps the current positions of existing nodes.
- `chat.sources` marks the matching nodes and edges with a highlight class and dims the rest.
- `chat.token` appends to the in-progress assistant message.
- `chat.done` and `chat.error` close the message.
- On reconnect: re-fetch the document list and graph snapshot, since events may have been missed.

### 7.3 Highlighting rules
- Highlight style: high-contrast border and colour on matched nodes and edges. Others reduced opacity. Highlight persists until the next question or until cleared.
- Highlight uses IDs only. The frontend does not infer sources from text.

### 7.4 Client rules
- Use `fetch` for all REST calls. Do not add axios.
- SSE: `fetch` with a streaming body reader and a small line parser. No `EventSource`.
- Types for all event payloads live in `types.ts`.
- No secrets in the bundle. No backend URLs hard-coded: use relative `/api` paths.

### 7.5 Dependencies
Runtime: `react`, `react-dom`, `cytoscape`.
Dev: `vite`, `@vitejs/plugin-react`, `typescript`, `eslint`, `typescript-eslint`, `eslint-plugin-react-hooks`, `@types/react`, `@types/react-dom`, `vitest`, `@testing-library/react`, `jsdom`.
Pick the latest stable release of each, then run the vulnerability check (section 9) before pinning.

---

## 8. Docker Compose

The compose setup is split into one fragment per service group so each change touches one file. The root `docker-compose.yml` lists the fragments with `include:` (requires Docker Compose 2.20 or newer). Fragments live in `compose/`: `neo4j.yml`, `mysql.yml`, `ollama.yml`, `langfuse-data.yml`, `langfuse-app.yml`, `backend.yml`, `frontend.yml`.

The sub-agent writes these files, plus `backend/Dockerfile`, `frontend/Dockerfile`, and `frontend/nginx.conf.template`. The sub-agent does **not** run any `docker` or `docker compose` command. It may check YAML syntax with a parser.

### 8.1 Services

| Service | Image (verify tag at implementation time) | Notes |
|---|---|---|
| `neo4j` | `neo4j:5` | Ports bound to `127.0.0.1` only. Data volume |
| `mysql` | `mysql:8.4` (LTS) | Ports bound to `127.0.0.1`. Data volume. Healthcheck with `mysqladmin ping`. Creates `MYSQL_DATABASE` and `MYSQL_USER` on first start |
| `ollama` | `ollama/ollama:0.x.x` (pin exact tag at implementation time, like `neo4j`/`mysql`) | Default LLM/embedding/agent provider (D24). Ports bound to `127.0.0.1`. Data volume for pulled models. A one-shot init command (listed in 8.2) pulls `LLM_MODEL` and `EMBEDDING_MODEL` after first start — the compose file itself does not pull models |
| `postgres` | `postgres:${POSTGRES_VERSION}` (17 in upstream Langfuse) | Langfuse database. Healthcheck `pg_isready` |
| `clickhouse` | `clickhouse/clickhouse-server:25.12` (upstream Langfuse tag) | Healthcheck on `/ping`. Ports bound to localhost |
| `redis` | `redis:7` | `--requirepass ${REDIS_AUTH}`. Ports bound to localhost |
| `minio` | `cgr.dev/chainguard/minio` (upstream Langfuse image) | Healthcheck `mc ready local`. Creates the `langfuse` bucket at start |
| `langfuse-web` | `docker.langfuse.com/langfuse/langfuse:4` (upstream image host) | Port 3000 published. Depends on all data services being healthy |
| `langfuse-worker` | `docker.langfuse.com/langfuse/langfuse-worker:4` | Same env as web. Port 3030 bound to localhost |
| `backend` | Built from `backend/Dockerfile` | Port 8000 bound to localhost. Reads `.env`. Depends on Neo4j and MySQL healthy |
| `frontend` | Built from `frontend/Dockerfile` (multi-stage: Node build, then nginx) | Port 5173 mapped to nginx port 8080. Injects `API_TOKEN` into nginx template |

Notes for the implementer:
- Use the upstream Langfuse compose file (`langfuse/langfuse` on GitHub, `docker-compose.yml`) as the reference for the Langfuse block. Copy its environment variable names and healthchecks. Re-check tags at implementation time.
- All host ports bound to `127.0.0.1` except the frontend and Langfuse web UI.
- Every published port and container name is read from `.env` (or `.env.test` for the test stack), so the two stacks can run at the same time (section 5.9).
- Named volumes for every stateful service.
- Restart policy `unless-stopped`.

### 8.2 Commands for the owner (to be written into README)

The owner runs these. The sub-agent prints them in its final report.

```bash
# 1. Create your env file and fill every value
cp .env.example .env
# edit .env, then generate secrets:
openssl rand -hex 32   # use for API_TOKEN, SALT, ENCRYPTION_KEY, NEXTAUTH_SECRET, passwords as needed

# 2. Start infrastructure first
docker compose up -d neo4j mysql ollama postgres clickhouse redis minio langfuse-web langfuse-worker

# 2b. Pull the Ollama models named in .env (default example: llama3.1, nomic-embed-text)
docker compose exec ollama ollama pull llama3.1
docker compose exec ollama ollama pull nomic-embed-text

# 3. Open Langfuse at http://localhost:3000, create a project,
#    copy its public and secret keys into .env (LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)

# 4. Start the app
docker compose up -d --build backend frontend

# 5. Check status
docker compose ps
docker compose logs -f backend

# 6. Open the app
#    http://localhost:8080
```

Test stack (separate project, separate data, never shares volumes with dev):
```bash
# start the test stack with test settings
docker compose -p lgac-test --env-file .env.test up -d neo4j mysql postgres clickhouse redis minio langfuse-web langfuse-worker

# run the integration suite from the backend folder, against the test stack only
APP_ENV=test uv run --env-file ../.env.test pytest -m integration

# stop and delete test data only
docker compose -p lgac-test --env-file .env.test down -v
```

Stop and reset (dev stack):
```bash
docker compose down              # stop, keep data
docker compose down -v           # stop and delete all data (Neo4j, MySQL, Langfuse, uploads)
```

---

## 9. Security and Vulnerability Policy (mandatory)

Applies to every dependency, every container image tag, and every base image.

### 9.1 Before pinning any version
1. Resolve the candidate version.
2. Query the OSV database (`https://api.osv.dev/v1/query`) for each package and version, for both ecosystems (PyPI, npm). Use `POST` with `{"package": {"name", "ecosystem"}, "version"}`.
3. Also run `npm audit` for the frontend lock file.
4. Any advisory for the chosen version means choose another version. If no safe version exists, stop and report to the owner. Do not use the package.
5. Record the result (package, version, date, advisories found = 0) in `SECURITY_CHECK.md`.

No vulnerability result is recorded yet. The first check happens when the lock files exist (T1.7, T1.11).

### 9.2 Container images
- Use official or vendor-published images only. Pin to a version tag, not `latest`.
- Run a scanner on the base image tags if one is installed (e.g. `docker scout` or `trivy`). Otherwise list the tags in `SECURITY_CHECK.md` so the owner can scan them.

### 9.3 Application security
- Upload checks as in 6.3. Path traversal prevented by generated storage names.
- CORS allow-list from `.env`.
- Rate limit `/api/chat` per token (simple in-memory limiter is acceptable, documented as single-process only).
- Security headers on nginx: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, a strict `Content-Security-Policy` for the SPA. The backend sends the same two headers for API responses.
- No `eval`, no `dangerouslySetInnerHTML` for model output. Render chat text as plain text.
- Model output and document text are untrusted input to the UI. Escape on render.
- Keep Neo4j, MySQL, Langfuse, ClickHouse, Redis, MinIO and Postgres on the internal Docker network. Only publish the ports listed in 8.1, bound to localhost.

---

### 9.4 Secret scanning
- A secret scanner (gitleaks, or an equivalent maintained scanner) runs over the repository before every push. Its rules live in a committed config file.
- A finding stops the push. The finding is removed from the history before pushing, not only from the latest commit.
- The scan covers `.env.example` as well, so placeholders can't be mistaken for real values.

## 10. Testing Strategy

Integration tests run only against the test stack (section 5.9), and the guard enforces it.

Tests must not require paid model calls. Use fake LLM and embedding clients that return fixed values, behind the same interfaces.

### 10.1 Backend (pytest)
- `config`: missing required variable fails with a clear message; limits parse correctly.
- `extract`: sample PDF, TXT, DOCX produce expected text; wrong magic bytes rejected; empty text rejected.
- `chunking`: no chunk exceeds the limit; paragraph boundaries preserved where possible; long single paragraphs split.
- `registry` (integration, MySQL): document CRUD; tracking rows; the `done` rule (all chunks inserted, counts match); cascade delete.
- `events`: publish reaches all subscribers; full queue drops the slow subscriber without raising.
- `ratelimit`: window behaviour.
- `insert` (fake graph): success path; a failure on chunk 3 of 5 leaves chunks 1 and 2 tracked as `inserted` and marks the document `failed`; `UnsupportedDocument` fails without retry; retries stop at `INGEST_RETRIES`.
- `recovery` (fake graph and real MySQL): a document left `processing` with a `pending` row and two `inserted` rows is cleaned: all three episodes removed, rows deleted, status `interrupted`; running recovery twice is safe; a `remove_episode` that raises for a missing episode is skipped.
- `auth`: missing, wrong, and correct token; health without token.
- `agent` (fake model): `chat.sources` before the first token; rewrite loop stops at `AGENT_MAX_REWRITES`; failure publishes `chat.error`.
- `routes`: each upload validation step and its status code; delete path; graph, chat, events, and system routes; SSE order.
- `main`: missing variable fails startup; valid settings start and create `DATA_DIR/uploads`; recovery runs before serving; global error handler returns a generic 500 without a traceback.
- `graph` (integration, Neo4j, fake model clients): insert one fixture document, then retrieve, snapshot, and remove.

### 10.2 Frontend (Vitest + Testing Library)
- SSE parser handles split chunks and multiple events per chunk.
- Reducer updates on each event type, including progress.
- Highlight class applied only to IDs in `chat.sources`.
- Upload pre-check rejects oversize and wrong-type files before sending.
- `ChatWidget` renders injected HTML as text.

### 10.3 End-to-end (manual, owner-run)
Listed in section 13.

---

## 11. Phases

Each phase ends with a verification step. A phase is not complete until its verification passes and the result is written in the final report.

| Phase | Work | Verification | Depends on |
|---|---|---|---|
| 0. Decisions | Owner resolves O2, O3 and records "go" | Decision recorded in this file | none |
| 1. Scaffold | Initialise git on `main` with the planning documents and `.claude/` as the first commit (T1.0). Then repo layout, `.gitignore`, `.env.example`, `backend/pyproject.toml` (uv, Python 3.14, `package = false`), `frontend/` package setup. Vulnerability check (9.1) | `uv lock` succeeds; `npm install` succeeds; check report written | 0 |
| 2. Backend core | `config`, `db`, `registry`, `extract`, `chunking`, `events`, `ratelimit`, `auth`, `tracing`, `models`, `graph`, `insert`, `recovery`, `agent`, routes, `main`. Unit tests (10.1, excluding integration) | `uv run pytest` passes; `uv run ruff check` and `uv run mypy app` clean | 1 |
| 3. Integration | Compose for Neo4j and MySQL, backend Dockerfile. Integration tests against Neo4j and MySQL | Integration tests pass when the owner starts Neo4j and MySQL | 2 |
| 4. Recovery proof | Owner interrupts a running insertion (stop backend mid-upload), restarts, and checks that graph data for that document is removed and status is `interrupted` | Owner reports the outcome; no orphan nodes or edges remain for that document | 3 |
| 5. Agent | Full LangGraph loop, Langfuse callbacks, streaming | Agent tests pass; owner sees a trace in Langfuse | 3 |
| 6. Langfuse self-hosted | Full Langfuse compose block; owner creates project and keys | Owner opens `http://localhost:3000` and sees an insertion trace | 3 |
| 7. Frontend | Three panels, fetch client, SSE reader, Cytoscape, highlight | Frontend tests pass; `npm run build` clean; `npx tsc --noEmit` and `npx eslint .` clean | 2 (API contract) |
| 8. Frontend container and proxy | Multi-stage Dockerfile, nginx template with token injection and headers | Owner loads `http://localhost:8080` and the file list appears | 7 |
| 9. Hardening | Limits from `.env` enforced server and client; rate limit; security headers; error messages reviewed | Limit tests pass; owner tries oversize and wrong-type uploads | 2, 8 |
| 10. Documentation | README: architecture diagram, `.env` table, commands from 8.2, known limitations (single process, shared token, embedding dimension, restart behaviour) | A clean machine can follow the README | all |

---

## 12. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Restart in the middle of an insertion | Partial data in the graph | Tracking rows written before each insert; cleaned on next boot (6.5). Owner test in Phase 4 |
| Crash during the cleanup itself | Leftover data | Cleanup is idempotent and runs on every boot until the rows are gone |
| Model returns output that Graphiti cannot parse | Insertion fails | Use a model the owner has verified supports JSON schema output. Retries, then `failed` with a clear message |
| Embedding dimension mismatch after a model change | Search errors or nothing | Documented in 5.5. Require a clean Neo4j volume on change |
| Extraction cost and time on large documents | Slow insertion, high bills | `INGEST_CHUNK_CHARS`, `MAX_FILE_SIZE_MB`, a visible progress counter |
| Uploads run in the same process as the API | A slow insertion can slow other requests | Acceptable for one owner. Uvicorn runs the insertion on the event loop, so keep graph calls async |
| Duplicate or noisy entities | Messy graph | Graphiti's resolution; source document shown on each node |
| In-memory event bus and rate limiter | Single process only | Run one backend worker. Stated in README |
| Shared token reachable through the frontend | Anyone who reaches the UI can call the API | Local use only. Stated in README |
| Langfuse self-hosted resource use | Many containers, heavy on laptops | Owner may start only the needed services in 8.2 |
| Cytoscape performance with many elements | Slow redraw | Cap snapshot with `GRAPH_SNAPSHOT_LIMIT`; incremental updates instead of full re-layout |
| Dependency vulnerabilities after time passes | Unsafe versions | Re-run 9.1 before each release and at the end of each phase |

---

## 13. Acceptance Criteria (owner-verified)

- [ ] `.env.example` lists every variable in section 5. The app refuses to start when a required variable is missing.
- [ ] No model name, endpoint, key, limit, or endpoint URL is hard-coded in source.
- [ ] Changing `LLM_MODEL`, `EMBEDDING_MODEL`, or `AGENT_LLM_MODEL` in `.env` and restarting the backend changes behaviour, with no code change.
- [ ] Upload PDF, TXT, and DOCX from the browser. Each appears in the left panel with status and progress updating live.
- [ ] Nodes and edges from the upload appear in the centre panel without a page refresh.
- [ ] Ask a question. The answer streams token by token.
- [ ] The nodes and edges that supplied the answer are highlighted in the centre panel.
- [ ] Oversized, wrong-type, and over-count uploads are rejected by the server with the right status code.
- [ ] Delete a document. Its nodes and edges disappear from the graph view without a refresh.
- [ ] Stop the backend during an upload, restart it, and confirm the partial document's graph data is removed and its status is `interrupted`.
- [ ] Each insertion and each agent run appears as a trace in the self-hosted Langfuse.
- [ ] `API_TOKEN` does not appear in the frontend bundle or in browser network responses.
- [ ] The vulnerability check (9.1) is recorded with zero advisories for every pinned version.
- [ ] `docker compose up` with the commands in 8.2 starts the stack on a clean machine with a filled `.env`.

---

## 14. Final Report Requirements (for the implementing sub-agent)

Every phase ends with a report containing:
1. Files created or changed, with paths.
2. Commands the sub-agent ran, and their results. Docker commands are never run by the sub-agent. List the ones the owner should run.
3. Vulnerability check results: package, version, advisories found.
4. Any deviation from this plan, with the reason.
5. Open questions that surfaced during the phase.
