# Project State

_Last updated: 2026-09-27_

## Current phase

Phases 1–6 implemented and verified locally. The MVP is **not deployed**; the live AI provider path has **not** been
run against the real API. Next milestone: live-provider evaluation + calibration, then a staging deployment.

## Implementation plan and status

| Phase | Scope | Status |
|---|---|---|
| 1 Foundation | Monorepo, FastAPI + Next.js, DB + migrations, auth + guests, config validation, design system, app shell, Compose, CI, health checks, logging | Done |
| 2 Ingestion | Upload UI, secure storage, PDF + EPUB parsers, structure, chapters, chunking, source mapping, jobs, status, retry, embeddings | Done (OCR path unit-tested with a fake engine; Tesseract image not built here) |
| 3 Summarizer | Workspace, TOC, chapter + book summaries, 3 depths, schemas, evidence, citations, source navigation, Q&A, notes/bookmarks/highlights, reading position, caching, cost tracking | Done |
| 4 Quizzer | Topics, bank generation, structural + blind semantic validation, dedup, UI, feedback, explanations, adaptivity, sessions, progress, mastery, revision, achievements | Done |
| 5 Polish + i18n | English/Hindi UI, language-aware generation, responsive layout, loading/empty/error states, accessibility, dashboards, privacy/retention, legal pages, dark mode | Done |
| 6 Quality + production readiness | Test suites, evaluation framework, gates, security review, audits in CI, containers, runbook, docs | Done except items under "Outstanding" |

## Verified (commands run in this environment)

- Backend: `pytest` — 80 passed on SQLite and on PostgreSQL 16 + pgvector; coverage 82 %; `ruff check` + `ruff format --check` clean.
- Alembic: `upgrade head` → `check` (no drift) → `downgrade base` → `upgrade head` on PostgreSQL.
- Evaluation: `python -m app.evaluations.run` — 17/17 release gates passed (offline engine); baseline saved in `evals/baselines/extractive.json`.
- Frontend: ESLint, `tsc --noEmit`, Vitest (6 passed), `next build` — all clean.
- E2E: Playwright 8 passed (journeys A–E, Hindi UI, axe accessibility, mobile) against real API + web servers.
- Containers: API image and web image built; both booted together; readiness, runtime proxy and cookie pass-through verified.

## Decisions

- Modular monolith (FastAPI) + Celery workers; Next.js front end with a runtime `/api/v1` proxy (first-party cookies,
  environment-independent images).
- Built-in auth (argon2id + hashed server-side session tokens) instead of an external provider for the MVP.
- pypdf + an in-house EPUB parser (avoid AGPL dependencies).
- Offline extractive engine as the default provider so the product works and tests run without API keys; Anthropic
  adapter with JSON-schema outputs and per-task routing for generative mode.
- Deterministic hashing embeddings stored in pgvector; hybrid BM25 + embedding retrieval per book.
- Blind validation of quiz keys; answer keys authoritative at grading time.
- Rule-based adaptivity and EWMA mastery, documented and labelled as estimates.
- Web Docker image uses `WORKDIR /srv/web` (an `/app` workdir collides with the Next.js `app/` directory).

## Outstanding / known limitations

1. **Live AI provider not exercised**: the Anthropic adapter, prompts and routing are implemented and tested with scripted
   providers; run `python -m app.evaluations.run --provider anthropic` (or the `live-eval` workflow) and calibrate gates
   with a human-reviewed sample before enabling it.
2. **Embeddings are lexical** (hashing). Add a neural embedding provider for better semantic retrieval and dedup.
3. **OCR**: Tesseract adapter implemented; worker image with Tesseract not built/verified here (Docker Hub rate limit
   and no apt egress during the local build).
4. **Email**: password-reset delivery only logs in development; a mail adapter is required for production.
5. **Not implemented**: malware scanning, MFA/OAuth, billing/subscription abstraction, manual chapter-boundary
   correction UI, per-user storage quotas, Q&A history persistence, text-to-speech.
6. **Not measured**: load/performance targets (p95), cross-browser E2E beyond Chromium, long-book (500+ page)
   processing time and cost.
7. Extractive quiz questions are recall/comprehension only; application/inference questions require the generative engine.
8. Guest timestamps on SQLite are returned without timezone offset (PostgreSQL returns them correctly).

## Next actions

1. Run the live-provider evaluation; review a sample of summaries/questions by hand; set semantic gate thresholds.
2. Add a neural embedding provider behind `Embedder`; re-run evaluations.
3. Implement the mail adapter and malware scanning; build and verify the worker image with Tesseract.
4. Staging deployment per `docs/DEPLOYMENT.md`; load test common endpoints; set alerts.

## MVP acceptance criteria

Checked items were verified by automated tests or direct runs in this environment. Unchecked items are not complete.

### Product
- [x] Landing page and onboarding work
- [x] Guest mode is usable
- [x] Registered users can create and access their libraries
- [x] PDF and EPUB uploads work
- [x] Document processing status is accurate
- [x] Chapter navigation works
- [x] Summarizer supports full-book and chapter summaries
- [x] Summary depth can be changed
- [x] Source citations are visible and resolvable
- [x] Book Q&A is source-grounded
- [x] Highlights, bookmarks and notes work
- [x] Quizzer presents exactly four options per question
- [x] Immediate correct/incorrect feedback works
- [x] Correct answers and grounded explanations are displayed
- [x] Source references are provided for questions and explanations
- [x] Question deduplication and adaptive difficulty are implemented
- [x] Progress, mastery and revision work
- [x] English and Hindi interface localization works
- [x] Responsive desktop and mobile browser experiences work

### AI quality
- [x] Summaries use only uploaded book content (verified for the offline engine; live engine pending evaluation)
- [x] Missing evidence is handled transparently
- [x] Material claims have traceable evidence
- [x] Chapter and full-book summaries are generated through a coverage-aware process
- [x] Questions have validated answer keys
- [ ] Questions do not rely on unsupported external knowledge — verified for the offline engine only; generative questions need the live evaluation
- [x] Invalid questions are rejected
- [x] Question history is used to avoid unnecessary repetition
- [x] AI quality evaluations are repeatable and versioned
- [x] Release quality gates are documented and enforced (CI)

### Engineering
- [x] Application builds and starts from documented instructions
- [x] Database migrations work
- [x] API contracts are documented (OpenAPI + ARCHITECTURE.md)
- [x] Authorization is enforced server-side
- [x] Background processing is resilient and retry-safe
- [x] Storage is private and secure
- [x] Errors are handled gracefully
- [x] Automated unit, integration and end-to-end tests pass
- [ ] No critical unresolved security findings remain — no known critical findings, but no independent review/pen test and malware scanning is not implemented
- [x] Monitoring and health checks are implemented (health/readiness, structured logs, AI execution records, optional error tracking)
- [x] CI/CD and deployment instructions are complete (CI workflow written; not yet run on GitHub)

### Operational readiness
- [x] Environment variables are documented
- [x] Secrets are not committed
- [x] Usage limits and AI cost controls are implemented
- [x] Guest retention and account deletion are functional
- [x] Backup and restore procedures are documented
- [x] Known limitations are explicitly documented
- [x] Production configuration is separated from development
- [x] A new developer can set up the project from the README
