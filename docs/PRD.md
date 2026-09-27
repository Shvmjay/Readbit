# Readbit — Product Requirements (MVP)

## 1. Vision

Readbit is a source-grounded reading and learning companion. A reader uploads their own book and gets two
complementary experiences: a **Summarizer** that preserves the author's reasoning with verifiable citations, and a
**Quizzer** that turns chapters into short, adaptive lessons. Readbit is not a generic PDF summarizer, a chatbot with a
reader attached, a trivia app, or a replacement for the book.

Principles: **faithfulness over fluency**, **learning over superficial engagement**, **efficiency without loss of
context**, **simplicity over feature bloat**, **trust and transparency**.

## 2. Audience and personas

| Persona | Need | What Readbit gives them |
|---|---|---|
| Priya, product manager, 20 min/day | Get through a non-fiction backlog without losing the argument | Chapter summaries at a chosen depth, resume where she left off |
| Arjun, university student (Hindi UI) | Understand and remember assigned reading | Lessons with explanations and the supporting passage, revision of weak topics |
| Sam, lifelong learner | Trust what a summary says | Citations to page/section, explicit “not in this book” answers, visible extraction gaps |

International, multilingual audience; launch UI languages English and Hindi.

## 3. User journeys

1. **First visit** → landing → “Start reading” → onboarding (language, privacy and retention notice, guest or account).
2. **Upload** → drag & drop / file picker → upload progress → persistent processing status (validating → extracting →
   detecting chapters → organising passages → indexing → ready) → open book. Failures show a plain-language reason and
   a retry where it makes sense.
3. **Summarize** → workspace overview (metadata, table of contents, warnings) → choose chapter or whole book and depth →
   read structured summary → open a citation → jump to the source passage → bookmark / note → ask the book a question.
4. **Learn** → lessons per chapter → four-option question → submit → correct/incorrect, correct answer, explanation,
   misconception, supporting passage → next → lesson result → mastery and weak concepts → revision session.
5. **Return** → dashboard: continue reading, continue learning, weak concepts, daily goal, streak, recent books.
6. **Account** → register (guest books migrate) → sign in on another device → library and progress persist.
   Settings: language, theme, daily goal, export data, delete account.

## 4. Functional requirements (P0) and status

| # | Requirement | Status |
|---|---|---|
| 1 | Responsive web app | Done — desktop sidebar, mobile bottom nav; mobile E2E checks no horizontal overflow |
| 2 | Landing + onboarding | Done — no fabricated testimonials, counts or ratings |
| 3 | Guest mode | Done — hashed session token, retention notice, automatic expiry and cleanup |
| 4 | Registration, login, logout | Done — argon2id, server-side sessions, password reset (dev mail logger) |
| 5 | Secure PDF/EPUB upload | Done — see SECURITY.md |
| 6 | Validation, parsing, chapter detection, status | Done |
| 7 | Personal library (registered) | Done — cursor pagination |
| 8 | Temporary guest sessions | Done |
| 9 | Overview and table of contents | Done — unknown metadata shown as unavailable |
| 10 | Full-book and chapter summaries | Done |
| 11 | Three depths | Done — depth switch keeps chapter and scroll position |
| 12 | Source references | Done — page (and printed label) or section/passage |
| 13 | Four-option MCQs | Done — enforced structurally and in the DB |
| 14 | Chapter lessons, topic-based selection | Done |
| 15 | Immediate feedback + grounded reasoning | Done |
| 16 | Validated bank + dynamic generation | Done |
| 17 | Deduplication + answer validation | Done — exact, fingerprint, embedding, answer+evidence; blind validator |
| 18 | Adaptive difficulty | Done — documented rules |
| 19 | Progress, completion, achievements | Done |
| 20 | Weak concepts + revision | Done |
| 21 | English + Hindi UI, extensible | Done |
| 22 | Notes, highlights, bookmarks | Done |
| 23 | Analytics, logging, errors | Done — content-free analytics, JSON logs, error taxonomy |
| 24 | Unit/integration/E2E tests | Done |
| 25 | Deployment config + docs | Done (not deployed) |

P1 delivered: dark mode, notes/summary export (Markdown), data export (JSON), reading-time estimates, search within a
book, per-topic mastery view, configurable daily goal, text-to-speech-ready structure (plain structured content).
Not delivered: subscription/billing abstraction.

Out of scope: social feeds, public profiles, multiplayer, public sharing, native apps, marketplace, external
recommendations, autonomous agents.

## 5. Non-functional requirements

- **Faithfulness**: book-derived content uses only the uploaded document; claims without valid evidence are removed;
  unanswerable questions abstain. Measured by the evaluation suite (AI_GROUNDING.md).
- **Privacy**: private by default; no training on user books; deletion and retention controls.
- **Accessibility**: WCAG 2.2 AA intent — semantic landmarks, labelled controls, keyboard operation, visible focus,
  reduced motion, contrast; axe scans in E2E.
- **Performance targets** (engineering targets, not guarantees): common API reads p95 < 500 ms; dashboard p95 < 1 s;
  quiz grading without model round-trips (verified: grading is a DB lookup). Not yet load-tested.
- **Cost**: per-task model routing, budgets, caching of summaries and question banks, on-demand generation.

## 6. Success metrics

- Activation: upload→ready conversion; first summary; first lesson completed; time to first learning interaction.
- Engagement: weekly active readers; chapters summarized; lessons completed; return sessions.
- Learning: question accuracy (labelled as such — not retention), chapter completion, mastery progression on weak topics.
- Quality: summary faithfulness, citation precision/coverage, chapter coverage, quiz validity, duplicate rate,
  abstention accuracy, extraction success, user-reported errors.
- Cost/ops: AI cost per book and per active user, processing duration, failure rate by stage, provider error rate.

All product events are captured in `analytics_events` (see `app/services/analytics.py` for the allowlist).

## 7. Acceptance criteria

See §21 of the original brief; the verified/unverified breakdown is maintained in [`PROJECT_STATE.md`](../PROJECT_STATE.md).
