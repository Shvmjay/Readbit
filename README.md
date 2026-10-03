# Readbit

**Read more. Learn better. Make every minute count.**

Readbit turns a book you own (PDF or EPUB) into two complementary experiences:

- **Summarizer** — chapter and whole-book summaries at three depths (concise, balanced, comprehensive). Every
  claim is linked to the passage of *your* book that supports it; citations open the source text at the right place.
  A book assistant answers questions **only from the uploaded book** and says so when the book doesn't cover a question.
- **Quizzer** — chapter lessons of four-option questions with immediate feedback, the correct answer, a grounded
  explanation and the supporting passage. Questions come from a validated, de-duplicated question bank topped up by
  controlled dynamic generation; difficulty adapts to your answers; weak concepts come back in revision sessions.

It works for guests (temporary sessions) and registered users (private library), in English and Hindi.

> Status: MVP. See [`PROJECT_STATE.md`](PROJECT_STATE.md) for what is verified, what is not, and known limitations.

---

## Features

| Area | What is implemented |
|---|---|
| Accounts | Guest sessions (hashed tokens, automatic expiry), email + password accounts (argon2id), server-side sessions, password reset by email (SMTP), guest → account migration, account deletion, data export |
| Library | Upload (drag & drop, progress), validation (magic bytes, size, zip-bomb and path checks, encryption/DRM detection), optional ClamAV scanning, duplicate detection, persistent processing status, retry, deletion |
| Ingestion | PDF (pypdf: outline, page labels, header/footer removal, font-size headings, OCR adapter) and EPUB 2/3 (spine, nav/NCX, sanitized XHTML); chapter detection with confidence and disclosed fallbacks; chunking with stable source locations; embeddings |
| Summarizer | Chapter + book summaries, 3 depths, hierarchical map → reduce for long chapters, book synthesis over *every* chapter, evidence resolution + citation checks, coverage and known-gap disclosure, caching, Markdown export |
| Book Q&A | Hybrid retrieval (BM25 + embeddings, RRF), grounded answers with citations, explicit abstention |
| Quizzer | Generation → structural checks → **blind** semantic validation → explanation repair → 4-way deduplication; adaptive difficulty; mastery (EWMA) + spaced review; revision sessions; achievements; idempotent answer submission |
| Reading | Source reader with highlights, notes and bookmarks; reading position; progress |
| i18n | English and Hindi UI (347 keys, parity-tested), localized landing/legal pages, language-aware summaries |
| AI platform | Provider abstraction, per-task model routing, versioned prompts, JSON-schema outputs, retries/backoff, escalation, daily budget, rate limits, cost tracking, offline extractive engine |
| Quality | 86 backend tests (82% coverage, SQLite + PostgreSQL), 6 frontend unit tests, 8 Playwright E2E tests (journeys A–E, i18n, axe accessibility, mobile), AI evaluation suite with release gates |
| Ops | Docker images (API, worker with OCR, web), Docker Compose (Postgres+pgvector, Redis, MinIO), GitHub Actions CI, opt-in live-provider evaluation workflow, health/readiness endpoints, structured logs |

## Architecture at a glance

```
Browser ──► Next.js (apps/web) ──/api/v1 proxy──► FastAPI (services/api) ──► PostgreSQL + pgvector
                                                        │                    Object storage (S3 / MinIO / local)
                                                        └── enqueue ──► Celery workers (Redis) ──► AI provider router
```

A modular monolith: one API with clear modules (auth, books, ingestion, retrieval, AI router, summaries, Q&A, quiz,
learning, annotations, analytics, retention) and independently scalable workers. Details:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### The AI engine

`DEFAULT_LLM_PROVIDER` selects the engine:

- **`extractive`** (default, no API key): a deterministic offline engine. Summaries are *selected sentences* from the
  book (labelled as such in the UI), answers quote the best-supported sentences, and quiz questions are cloze, numeric
  and statement-verification items whose answer keys are mechanically checkable. It cannot paraphrase, translate or write
  application/inference questions — the UI and API say so rather than faking it.
- **`anthropic`**: Claude models via the official SDK with JSON-schema structured outputs (`SUMMARY_MODEL`,
  `QA_MODEL`, `QUIZ_MODEL`, `VALIDATION_MODEL`, `ESCALATION_MODEL`, …). Enables generative summaries, translation
  and all four question types. Requires `LLM_API_KEY`.

See [`docs/AI_GROUNDING.md`](docs/AI_GROUNDING.md).

## Repository layout

```
apps/web/                 Next.js 15 (App Router, TypeScript strict, Tailwind, TanStack Query, RHF + Zod)
  app/                    routes (landing, onboarding, auth, /app/* product screens, legal, API proxy)
  components/ features/   UI primitives and feature modules (summarizer, quizzer, annotations, upload, library)
  locales/                en.json, hi.json
  tests/unit, tests/e2e   Vitest and Playwright
services/api/             FastAPI + SQLAlchemy 2 + Alembic + Celery
  app/api/                routes, dependencies, serializers
  app/services/           business logic (books, ingestion, summaries, Q&A, quiz, learning, auth, retention…)
  app/document_processing PDF/EPUB extraction, validation, chapter detection, chunking, OCR adapter
  app/ai/                 provider interface, Anthropic + extractive providers, router, prompts, schemas, retrieval
  app/evaluations/        evaluation runner
  migrations/             Alembic
  tests/                  pytest suites
prompts/                  version-controlled prompt templates (+ shared source/safety rules)
evals/                    datasets (CC0 synthetic books + annotations), fixtures, gates, baselines, reports
infra/docker/             Dockerfiles
scripts/                  fixture generator, E2E API launcher
docs/                     PRD, architecture, AI grounding, security, testing, deployment
```

## Prerequisites

- Python 3.11+, Node.js 22+
- For the full stack: PostgreSQL 16 with pgvector, Redis 7, S3-compatible storage — or just Docker

## Quick start (no services required)

SQLite, filesystem storage, in-process background jobs, offline AI engine:

```bash
# API
cd services/api
pip install -e ".[dev]"
python ../../scripts/generate_fixtures.py        # sample books in evals/fixtures
DATABASE_URL=sqlite:///./readbit-dev.db JOB_BACKEND=thread uvicorn app.main:app --reload --port 8000

# Web (new terminal)
cd apps/web
npm install
API_URL=http://localhost:8000 npm run dev         # http://localhost:3000
```

Upload `evals/fixtures/attentive_mind.pdf` to try it. API docs: http://localhost:8000/docs.

## Full stack with Docker Compose

```bash
cp .env.example .env          # set SECRET_KEY; optionally DEFAULT_LLM_PROVIDER=anthropic + LLM_API_KEY
docker compose up --build
```

Web http://localhost:3000 · API http://localhost:8000 · MinIO console http://localhost:9001. The API container runs
`alembic upgrade head` on start; the `worker` service runs Celery (with Tesseract OCR) and `beat` runs retention cleanup.

## Configuration

All settings are environment variables, documented in [`.env.example`](.env.example) and validated at startup
(`services/api/app/core/config.py`). Production (`APP_ENV=production`) refuses to start with the development secret,
SQLite, local storage or non-Celery jobs.

## Database

```bash
cd services/api
DATABASE_URL=postgresql+psycopg://readbit:...@localhost:5432/readbit alembic upgrade head
```

The initial migration enables the `vector` extension. For SQLite development the schema is created automatically.

## Running workers

```bash
cd services/api
JOB_BACKEND=celery REDIS_URL=redis://localhost:6379/0 \
  celery -A app.workers.celery_app worker -Q documents,summaries,questions,maintenance,default --concurrency 2
celery -A app.workers.celery_app beat          # hourly guest-retention cleanup
```

## Tests

```bash
# Backend (SQLite by default; set TEST_DATABASE_URL for PostgreSQL)
cd services/api && pytest --cov=app
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/readbit_test pytest

# AI evaluation + release gates (offline, deterministic; used in CI)
python -m app.evaluations.run
# Live provider (opt-in, costs money)
LLM_API_KEY=... python -m app.evaluations.run --provider anthropic

# Frontend
cd apps/web && npm run lint && npm run typecheck && npm test && npm run build
npx playwright test          # starts a throwaway API + web server itself
# (in environments with a pre-installed Chromium: PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome npx playwright test)
```

See [`docs/TESTING.md`](docs/TESTING.md).

## Deployment

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md): managed Postgres (pgvector) + Redis + private S3 bucket, the API
and worker containers, the web container, secrets, migrations, backups, monitoring and rollback. **This repository has
not been deployed to a hosted environment**; container images were built and smoke-tested locally.

## Known limitations

Summarized here; the authoritative list is in [`PROJECT_STATE.md`](PROJECT_STATE.md).

- The live Anthropic path is implemented and unit-tested with scripted providers, but **has not been exercised against
  the real API in this environment** (no key was available). Run the live evaluation before enabling it.
- The default embedding is a lexical hashing embedder (deterministic, no key); semantic retrieval quality will improve
  with a neural embedding provider.
- OCR requires Tesseract in the worker image (`OCR_PROVIDER=tesseract`); the worker image build was not validated here.
- Billing/subscriptions, native apps, text-to-speech and social features are out of scope for the MVP.

## Documentation

- [Product requirements](docs/PRD.md)
- [Architecture](docs/ARCHITECTURE.md)
- [AI grounding and evaluation](docs/AI_GROUNDING.md)
- [Security, privacy and copyright](docs/SECURITY.md)
- [Testing](docs/TESTING.md)
- [Deployment and operations](docs/DEPLOYMENT.md)
- [Project state](PROJECT_STATE.md)
