# Architecture

## System context

```
                ┌──────────────────────────── Readbit ─────────────────────────────┐
 Reader ──HTTPS──► Web (Next.js)  ──/api/v1 runtime proxy──►  API (FastAPI)        │
 (browser)      │  SSR landing/legal,                        │  auth, books, AI,     │
                │  client app screens                        │  quiz, learning       │
                │                                            ├──► PostgreSQL+pgvector│
                │                                            ├──► Object storage (S3)│
                │                                            └──► Redis ──► Workers  │
                │                                                         (Celery)  │
                └──────────────────────────────────────────────────┬───────────────┘
                                                                   ▼
                                                   AI provider (Anthropic) — optional
```

The browser talks only to the web origin. `apps/web/app/api/v1/[...path]/route.ts` forwards `/api/v1/*` to
`API_URL` **at runtime** (so one image runs in any environment) and passes cookies through, keeping auth cookies
first-party (`HttpOnly`, `SameSite=Lax`, `Secure` in production).

## Modular monolith

| Module | Location | Responsibility |
|---|---|---|
| Config, DB, errors, logging, security, rate limits | `app/core` | Validated settings, SQLAlchemy engine/session, error taxonomy, JSON logs, argon2/HMAC helpers |
| Identity | `services/auth_service.py`, `models/users.py` | Guests, users, sessions, reset tokens, guest→user migration |
| Actor | `services/actors.py` | The request's user **or** guest; ownership SQL clauses |
| Library | `services/book_service.py` | Upload, dedup, ownership-checked access, retry, delete |
| Ingestion | `services/ingestion.py`, `document_processing/*` | Validation, PDF/EPUB extraction, chapters, chunks, embeddings |
| Retrieval | `ai/retrieval.py`, `ai/embeddings.py` | Per-book hybrid search, passage rendering, token windows |
| AI router | `ai/router.py`, `ai/providers/*`, `ai/prompts.py`, `ai/schemas.py` | Provider abstraction, per-task models, retries, validation, escalation, cost |
| Summaries | `services/summary_service.py`, `services/evidence.py` | Hierarchical summaries, grounding, evidence references |
| Q&A | `services/qa_service.py` | Retrieval-grounded answers, abstention |
| Quiz | `services/quiz_service.py` | Bank generation, validation, dedup, sessions, grading |
| Learning | `services/learning_service.py` | Mastery, adaptivity, spaced review, progress, achievements |
| Annotations | `services/annotation_service.py` | Highlights, notes, bookmarks, reading state, export |
| Analytics | `services/analytics.py` | Allowlisted, content-free product events |
| Retention | `services/retention.py`, `workers/celery_app.py` | Guest expiry, file cleanup, account deletion |
| Jobs | `workers/dispatch.py` | `inline` / `thread` / `celery` backends behind one `enqueue()` |

Module boundaries are plain Python packages with service functions; high-load parts (ingestion, generation) already run
in workers and can be extracted into separate services later without changing the API.

## Data flow

1. `POST /books/upload` → validate (extension, MIME, magic bytes, size, zip safety) → store under a random key →
   `Book(status=uploaded)` + `ProcessingJob(ingest)` → enqueue.
2. Worker: `validating` (checksum) → `extracting` (PDF/EPUB → blocks with page/spine locations) → `structuring`
   (chapters + confidence, language, metadata) → `chunking` (rebuild chapters/chunks idempotently) → `indexing`
   (embeddings) → `ready`. Transitions are validated by `services/state_machine.py`; status is committed per stage.
3. Summaries/question banks are generated **on demand** as jobs; results are cached per (chapter, depth, language).
4. Q&A and grading are synchronous; grading never calls a model.

## API

Versioned REST under `/api/v1`, documented by OpenAPI at `/docs` (disabled in production). 40 paths; main groups:
`auth`, `me`, `books` (+ chapters, passages, search, processing-status, retry, reading-state), `summaries`,
`questions` (Q&A), `evidence` (+ translate), `annotations`, `lessons`, `quiz-sessions`, `revision-sessions`,
`progress`, `mastery`, `users/me/achievements`, `events`, `meta`. Conventions:

- Errors: `{"error": {"code", "message", "retryable", "details"}}` with stable codes (`app/core/errors.py`).
- Ownership is resolved server-side from the session; resources owned by someone else return **404** (no IDOR oracle).
- Cursor pagination (`/books?limit=&cursor=`; opaque base64url cursor).
- Idempotency: answer submission (first submission is final), duplicate uploads (same content → existing book),
  summary requests (cached/in-flight summary returned), job handlers (rebuild derived rows).
- Long operations are asynchronous with polling (`processing-status`, `summaries/{id}`, `quiz-sessions/{id}`).
- Rate limits on AI endpoints (per actor per minute), uploads, auth and guest creation.

## Database

PostgreSQL (JSONB, pgvector `vector(256)`), SQLAlchemy 2 models in `app/models`, Alembic migration `0001`.
Tables: `users`, `guest_sessions`, `auth_sessions`, `password_reset_tokens`, `source_files`, `books`, `chapters`,
`document_chunks`, `evidence_references`, `processing_jobs`, `summaries`, `summary_evidence`, `annotations`,
`reading_states`, `topics`, `questions`, `quiz_sessions`, `session_questions`, `question_attempts`, `topic_mastery`,
`achievements`, `user_achievements`, `ai_executions`, `analytics_events`.

Integrity highlights:
- UUID primary keys; FKs with `ON DELETE CASCADE` from `books` so deleting a book deletes all derived data.
- Exactly-one-owner check constraints (`owner_user_id` XOR `guest_session_id`) on books, annotations, sessions,
  mastery, achievements and reading state; NULL-safe uniqueness via an `actor_key` column.
- `questions`: type/difficulty/answer-key check constraints; four options enforced in code before insert.
- `question_attempts`: unique (session, question, attempt) → idempotent grading.
- `summaries`: scope check (book ⇔ no chapter).
- SQLite is supported for development/tests through portable types (`JSONType`, `EmbeddingType`).

## AI orchestration

`ModelRouter.generate(task, variables, context, …)`:
1. Picks the provider (`DEFAULT_LLM_PROVIDER`) and the model for the task (`SUMMARY_MODEL`, `QA_MODEL`, …).
2. Refuses unsupported output languages (no silent fallback to another language).
3. Enforces the daily AI budget.
4. Renders the versioned prompt from `/prompts` (single-pass substitution; book text is never re-expanded).
5. Calls the provider with a timeout; retries transient errors with exponential backoff; on schema-invalid output
   escalates to `ESCALATION_MODEL`; fails closed with `ai_output_invalid`.
6. Validates output against the task JSON Schema; records tokens, cost, latency and failure category in
   `ai_executions` (never prompts or book text).

## Document processing

- **PDF** (pypdf, BSD): per-page text with font sizes via the text visitor; running header/footer and page-number
  removal; hyphenation repair; paragraph reconstruction; headings by font size and patterns; outline → TOC; printed
  page labels kept separately from physical indices; scanned pages → OCR adapter or disclosed gap.
- **EPUB** (zipfile + defusedxml + BeautifulSoup): container → OPF → spine; nav (EPUB 3) or NCX (EPUB 2); XHTML
  with scripts/styles/iframes/objects removed; anchors mapped to blocks.
- **Chapters**: TOC/outline/nav → heading patterns → EPUB spine headings → numbered headings → optional
  model-assisted selection among existing lines → disclosed fallback segments ("Section 2 (pages 11–20, no chapter
  headings detected)"). Confidence stored per chapter and per book.
- **Chunks**: paragraph-aligned (~220 words, max 360), stable char offsets into the chapter text, page/spine
  locations, section titles, extraction confidence.

## Scaling strategy

- Stateless API containers behind a load balancer; workers scale independently per queue (`documents`, `summaries`,
  `questions`, `maintenance`); `worker_prefetch_multiplier=1` and `acks_late` for backpressure and safe redelivery.
- Connection pooling (`DB_POOL_SIZE`); per-book retrieval keeps vector search bounded. For very large libraries move
  scoring to SQL (`embedding <=> :q` with an HNSW index) — the column is already `vector(256)`.
- Provider rate limits handled by router retries/backoff and per-actor limits; daily budget cap.
- Object storage grows independently; lifecycle rules and the retention job remove expired guest files.

## Key decisions

| Decision | Rationale / trade-off |
|---|---|
| Modular monolith + Celery | Fast to build and operate; clear seams to extract later |
| Own EPUB parser, pypdf for PDF | Avoid AGPL dependencies (ebooklib, PyMuPDF) in a SaaS |
| Built-in auth (argon2id, server sessions) | No third-party dependency for MVP; OAuth can be added behind the same actor model |
| Runtime API proxy in Next.js | First-party cookies; images independent of API URL; build-time rewrites were rejected after they baked the URL into the image |
| Offline extractive engine | App is fully functional and testable without keys; deterministic tests and evals; honest labelling |
| Hashing embeddings by default | Deterministic and free; swap for a neural provider when quality matters more than cost |
| Blind validator for quiz keys | The validator never sees the proposed key, so agreement is meaningful |
| Answer key is authoritative | Grading is a DB comparison — fast, cheap and never "re-decided" by a model |
