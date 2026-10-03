# Testing

## Test architecture

| Layer | Tool | Location | Needs paid APIs? |
|---|---|---|---|
| Backend unit | pytest | `services/api/tests/test_unit_*.py` | No |
| Backend integration (API + DB + storage + jobs) | pytest + FastAPI TestClient | `services/api/tests/test_integration_*.py`, `test_smoke_flow.py` | No |
| AI evaluation + release gates | `app.evaluations.run` | `evals/` | No (offline); opt-in live run |
| Frontend unit | Vitest + Testing Library | `apps/web/tests/unit` | No |
| End-to-end | Playwright (+ axe-core) | `apps/web/tests/e2e` | No |

Standard suites use the offline extractive engine as a deterministic provider, `JOB_BACKEND=inline` (jobs run
synchronously) and a fresh database + storage directory per test. Router behaviour with a paid provider (retries,
escalation, budgets, language refusal) is tested with a scripted fake provider (`ScriptedProvider`).

## Commands

```bash
# one-off: generate deterministic fixture documents (PDF/EPUB) from the CC0 corpus
python scripts/generate_fixtures.py

cd services/api
pytest                                   # SQLite
pytest --cov=app --cov-report=term       # with coverage
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/readbit_test pytest   # PostgreSQL + pgvector
ruff check app tests && ruff format --check app tests migrations
python -m app.evaluations.run            # AI evaluation + gates (writes evals/reports/latest-extractive.*)

cd apps/web
npm run lint && npm run typecheck && npm test && npm run build
npx playwright test                      # boots its own API (port 8001) and web (port 3001)
```

The Playwright config starts `scripts/e2e-api.sh` (fresh SQLite DB, thread jobs, offline engine) and `next start`
(requires `npm run build`). Set `PLAYWRIGHT_CHROMIUM_PATH` to use a pre-installed Chromium.

## Fixtures

`evals/datasets/books/*.json` hold original CC0 texts; `scripts/generate_fixtures.py` renders them into
`evals/fixtures/`:

| Fixture | Purpose |
|---|---|
| `attentive_mind.pdf` | PDF with outline/bookmarks, running headers, page numbers, wrapped headings |
| `attentive_mind_no_outline.pdf` | Chapter detection from headings only |
| `attentive_mind.epub` | EPUB 3 with nav document |
| `backyard_compost.epub` / `.pdf` | Technical text with section headings, numbers and units |
| `hindi_reading.epub` | Devanagari text, EPUB 2 with NCX |
| `injection_test.pdf` | Embedded prompt-injection text |
| `no_structure.pdf` | No headings → disclosed fallback segmentation |
| `scanned.pdf` | Image-only pages → OCR path / disclosed gap |
| `encrypted.pdf`, `malformed.pdf`, `fake_pdf.pdf`, `notes.txt` | Failure handling |

## Coverage of the required areas

- Unit: validation (sizes, MIME, magic bytes, zip bombs, traversal, XXE), PDF/EPUB extraction, chapter detection
  (5 structural paths), chunk offsets/locations, prompts (presence, versions, safety rules, no re-expansion), router
  (retry, escalation, fail-closed, outage, budget, language), extractive engine (verbatim summaries, injection filtering,
  abstention, blind validation), structural question checks, fingerprints/embedding similarity, adaptive difficulty,
  weakness detection.
- Integration: upload → processing lifecycle for PDF and EPUB; unsupported/fake/malformed/encrypted/scanned files;
  no-structure disclosure; duplicate uploads; idempotent retry; deletion of file and derived data; guest retention
  cleanup; pagination; search; summaries at three depths with resolvable citations and caching; book summary
  coverage; language refusal; Hindi summaries; Q&A grounding and abstention; injection resistance; full lesson with
  feedback, progress, mastery, achievements and non-repetition across lessons (dynamic top-up); idempotent answers;
  revision; only-approved questions; annotations and reading state; registration/login/logout; hashing; validation;
  enumeration resistance; guest migration; password reset; account deletion; CSRF; security headers/cookies;
  cross-user and cross-guest isolation on every book-scoped endpoint.
- E2E: Journeys A (guest summarization), B (registered library persistence), C (quizzer with correct and incorrect
  answers, completion, mastery, revision, achievements), D (failure handling), E (security isolation), Hindi
  interface, axe accessibility scan (landing, dashboard, overview, summary, quiz — no serious/critical WCAG 2.2 A/AA
  violations), mobile viewport (navigation, upload, summary, no horizontal overflow).

The Journey C quiz helper answers using only information visible to the reader (question, options, source text); it
never reads the answer key.

## Latest results (2026-09-27, this environment)

| Suite | Result |
|---|---|
| Backend, SQLite | 86 passed |
| Backend, PostgreSQL 16 + pgvector 0.6 | 86 passed |
| Backend coverage | 82 % of `app` lines |
| Alembic | upgrade → check (no drift) → downgrade → upgrade OK on PostgreSQL |
| Evaluation (offline) | 17/17 gates passed (see AI_GROUNDING.md) |
| Frontend lint / typecheck / build | clean |
| Frontend unit | 6 passed |
| Playwright | 8 passed (desktop Chromium + Pixel 7 profile) |
| Containers | API and web images built and smoke-tested (readiness, proxy, cookies); worker image not built here |

## Quality thresholds and regression procedure

Release gates live in `evals/gates.json` and fail CI when violated. When changing prompts, models, chunking,
retrieval, embeddings, parsers, schemas or validation rules: run the offline suite, run the live suite when generative
behaviour changes, review `regression` in the report against `evals/baselines/`, and update the baseline only for
accepted changes.

## Not yet covered

Load/performance testing, a live-provider evaluation run, visual regression, cross-browser E2E (Firefox/WebKit), and
Celery-broker integration tests (jobs are tested through the inline/thread backends that share the same handlers).
