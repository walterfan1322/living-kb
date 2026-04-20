# Living KB

`Living KB` is a local-first knowledge-base platform for an agentic knowledge architecture:

- `Ingestion layer`: URLs, PDFs, text, and image assets
- `RAW layer`: normalized raw documents stored in Postgres or SQLite plus filesystem snapshots
- `Compilation layer`: turns raw content into structured Markdown wiki pages
- `Knowledge layer`: frontmatter, summaries, tags, and graph links
- `Maintenance layer`: health checks for thin pages, stale pages, orphan pages, and contradiction candidates
- `Interaction layer`: natural-language query with citations and follow-up recommendations

## Tech stack

- Python 3.13
- FastAPI
- SQLAlchemy
- Alembic
- Postgres + `pgvector` for the primary path
- SQLite for lightweight fallback development
- Filesystem storage for raw files and generated pages

The app is still local-first, but the primary runtime path now targets Postgres + `pgvector`. SQLite remains available as a fallback for smoke tests and quick local experiments.

- `S3 / R2`
- real LLM compilation providers
- background workers such as `Temporal`, `Celery`, or `Inngest`

## LLM mode

By default, the project runs in deterministic fallback mode.

To enable OpenAI-backed compilation and query answering:

```bash
setx OPENAI_API_KEY "your-key"
setx LKB_LLM_PROVIDER "openai"
setx LKB_OPENAI_MODEL "gpt-5-mini"
```

Then restart your shell and run the app again.

When the API key is missing, the app automatically falls back to the local heuristic pipeline.

To enable MiniMax-backed compilation and query answering with the official OpenAI-compatible endpoint:

```bash
setx MINIMAX_API_KEY "your-key"
setx LKB_LLM_PROVIDER "minimax"
setx LKB_MINIMAX_MODEL "MiniMax-M2.7"
setx LKB_MINIMAX_BASE_URL "https://api.minimax.io/v1"
```

MiniMax is currently used for `compile` and `query`. Embeddings still fall back to the local deterministic provider unless you separately enable an embeddings provider the app supports.

## Worker mode

The web app no longer owns the scheduler loop. Background work now runs in a separate worker process:

- jobs are persisted in the configured database
- the worker polls for due jobs
- health checks can be auto-scheduled
- pending pages and open findings appear in a review queue

Optional settings:

```bash
setx LKB_SCHEDULER_ENABLED "true"
setx LKB_SCHEDULER_POLL_SECONDS "5"
setx LKB_HEALTH_CHECK_INTERVAL_SECONDS "300"
```

## Quickstart

### 1. Start Postgres + pgvector

```bash
cd E:\project\living-kb
docker compose up -d
```

### 2. Install dependencies and migrate

```bash
cd E:\project\living-kb
uv sync --extra dev
set LKB_DATABASE_URL=postgresql+psycopg2://app_user:app_password@127.0.0.1:5432/living_kb
uv run alembic upgrade head
```

### 3. Run the API

```bash
cd E:\project\living-kb
set LKB_DATABASE_URL=postgresql+psycopg2://app_user:app_password@127.0.0.1:5432/living_kb
uv run uvicorn living_kb.main:app --reload
```

### 4. Run the worker

```bash
cd E:\project\living-kb
set LKB_DATABASE_URL=postgresql+psycopg2://app_user:app_password@127.0.0.1:5432/living_kb
uv run living-kb-worker
```

Open `http://127.0.0.1:8000/docs`.
Open `http://127.0.0.1:8000/app` for the control-room UI.

### SQLite fallback

If you want the original lightweight path, keep the default SQLite URL and skip Docker/Alembic. The test suite still uses this path.

The control-room UI now supports:

- text ingestion
- URL ingestion
- file upload ingestion for text, PDF, and image inputs
- raw source preview with metadata, linked page tracking, and queue/compile actions

## Main API surface

- `POST /api/ingest/text`
- `POST /api/ingest/url`
- `POST /api/ingest/file`
- `POST /api/compile/{raw_id}`
- `POST /api/query`
- `POST /api/health-check`
- `GET /api/pages/{slug}`
- `GET /api/pages/{slug}/revisions`
- `GET /api/pages/{slug}/diff`
- `GET /api/pages/{slug}/lineage`
- `GET /api/raw-documents/{raw_id}`
- `GET /api/compile-runs`
- `GET /api/review-events`
- `GET /api/query-events`
- `GET /api/dashboard`

### Job queue

- `POST /api/jobs/compile/{raw_id}`
- `POST /api/jobs/health-check`
- `POST /api/jobs/run-once`
- `POST /api/jobs/{job_id}/run`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`

### Review queue

- `GET /api/review-queue`
- `POST /api/review/pages/{page_id}/approve`
- `POST /api/review/pages/{page_id}/reject`
- `POST /api/review/findings/{finding_id}/resolve`
- `POST /api/review/findings/{finding_id}/dismiss`

## Suggested workflow

1. Ingest raw material.
2. Queue a compile job for the new raw document.
3. Let the worker poll, or call `POST /api/jobs/run-once` while testing locally.
4. Open `GET /api/review-queue` and approve or reject pending pages.
5. Review health findings and resolve or dismiss them.

## Hybrid retrieval

With Postgres enabled, query ranking uses:

- Postgres full-text search via `tsvector` and `ts_rank_cd`
- `pgvector` cosine similarity over compiled page embeddings
- weighted score fusion controlled by:
  - `LKB_RETRIEVAL_LEXICAL_WEIGHT`
  - `LKB_RETRIEVAL_VECTOR_WEIGHT`

When Postgres is unavailable, the app falls back to in-process lexical ranking plus deterministic embeddings.
