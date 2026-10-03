# AI Grounding, Generation and Evaluation

## 1. Source-of-truth policy

The uploaded document is the only authority for book-derived content: summaries, Q&A answers, quiz questions, answer
keys, explanations and takeaways. Models may use general language ability to read and rephrase, but factual claims must
be supported by passages of the book. Missing content is never filled from outside knowledge; unanswerable questions
abstain with an explicit reason.

This policy is enforced in three layers:

1. **Prompts** — every generation prompt includes the shared rules in `prompts/_shared_rules.md` (allowed sources,
   prohibited behaviour, citation requirements, uncertainty behaviour, language rules, prompt-injection handling).
2. **Structure** — outputs are JSON-schema constrained (`app/ai/schemas.py`); every claim carries `evidence_ids` that
   must reference passages actually supplied to the model.
3. **Verification in code** — claims with no valid evidence are removed and counted; cited passages are resolved to
   bounded excerpts; quiz keys must be independently re-derived by a blind validator; Q&A answers without valid
   citations are withheld.

## 2. Chunking and retrieval

- Chunks are paragraph-aligned (~220 words, max 360) within a chapter, with stable ids (`P{ordinal}` in prompts, UUID
  in the DB), char offsets into the chapter text, page index + printed label (PDF) or spine index + href (EPUB),
  section title and extraction confidence.
- Retrieval (`app/ai/retrieval.py`) is always scoped to one book (optionally one chapter) and fuses BM25 with embedding
  cosine using reciprocal rank fusion. There is no cross-book or cross-user search path.
- Summaries do **not** use top-k retrieval: a chapter summary reads *every* chunk of the chapter; long chapters are
  processed hierarchically (passage windows → notes → chapter synthesis) and a book summary aggregates *every*
  chapter summary. Coverage (`source_passages_considered/cited`, `chapters_covered/total`, failures) is stored with
  each summary and shown in the UI.

## 3. Evidence representation

`evidence_references`: book, chunk, chapter, source type, page label, page index, EPUB location, character start/end
(within the chunk), excerpt (≤ `MAX_EXCERPT_CHARS`), document version (content hash) and extraction confidence.
For each cited passage the service selects the sentence that best supports the claim (`services/evidence.py`), so a
citation shows the specific supporting sentence rather than a whole page. Citations are resolvable via
`GET /books/{id}/evidence/{evidence_id}` and open the source reader at the passage. Page numbers are never invented:
when a physical page is not available the citation shows section and passage.

## 4. Summary generation

Schema (`SUMMARY_SCHEMA`): title, central thesis, sections (heading, content, key concepts, evidence), definitions,
examples, caveats, connections, conclusion, takeaways, known gaps, `language_ok`. Depth contract (in the prompt):
concise (thesis, primary arguments, conclusions), balanced (+ reasoning, concepts, examples), comprehensive (+ detailed
argument structure, evidence, caveats). Empty sections are allowed and expected; the prompt forbids inventing examples.
Stored content adds `coverage`, `engine`, reading-time estimates and, for each claim, `evidence_ids` (UUIDs),
`passage_ids` and a lexical `support` flag. Oversized outputs fail (`max_tokens` → provider error → retry/escalate) rather
than being silently truncated; the hierarchical path keeps each call within budget.

## 5. Book Q&A

1. Retrieve up to 6 passages (whole book or a chapter).
2. `book_qa` returns `answerable`, `answer`, `evidence_ids`, `confidence`, `unanswerable_reason`.
3. If not answerable, or the answer cites nothing valid, the API returns an abstention (the drafted answer is withheld).
4. Cited passages are resolved to excerpts; confidence is downgraded if lexical support is very low.
General-knowledge questions get an explicit “only answers from your book” response.

## 6. Quiz generation and validation

Stage A — **generation** (`quiz_question_generator`): chapter passages (rotating windows for long chapters), requested
types/difficulties, and an `<avoid>` list of existing questions.

Stage B — **validation** (every candidate):
- Structural (`structural_problems`): exactly four options with keys A–D, unique non-empty option texts, a valid key,
  valid type/difficulty, at least one valid evidence id, an explanation, answer not revealed in the stem, correct option
  not conspicuously longer than the distractors.
- Semantic, **blind** (`quiz_question_validator`): the validator sees the passages, question and options but *not*
  the key; it must independently choose the same key, and pass `answer_supported`, `distractors_incorrect`,
  `unambiguous`, `no_external_knowledge`, `language_ok`. If only `explanation_supports_answer` fails, the
  `answer_explainer` rewrites the explanation from the passages; otherwise the candidate is rejected.
- Rejected candidates are stored with `validation_status=rejected` and a `validation_report` (the decision record).
  Only `approved` questions are ever served.

Stage C — **dynamic generation**: when a reader has used the unanswered approved questions for a chapter, a lesson
start enqueues generation of new questions (method `dynamic`) through the same pipeline, avoiding existing questions.
If none pass validation the lesson becomes `unavailable` with an explanation — invalid questions are never shown.

Stage D — **deduplication**: exact normalized text; order-insensitive content-word fingerprint; embedding cosine ≥
`DEDUP_SIMILARITY_THRESHOLD` (0.9) within the chapter; same correct answer + same first evidence passage. Reader history
is excluded in normal lessons; revision sessions deliberately reuse questions from weak topics. Semantic similarity is a
heuristic, so uniqueness is not guaranteed mathematically; decisions are recorded in `validation_report.dedup`.

Stage E — **explanations and grading**: the stored key is authoritative; grading compares keys in the DB (no model call),
then returns correctness, the correct answer, the explanation, misconception, supporting excerpts and mastery update.

## 7. Adaptive difficulty and mastery (rule-based)

- Levels 1 (easy), 2 (medium), 3 (hard). Initial level from the reader's average topic mastery for the chapter
  (<0.4 → 1, <0.75 → 2, else 3; no history → 1).
- After each answer (window = last 4 in the session): last two correct and window accuracy ≥ 0.75 → +1 (unless the last
  correct answer took > 45 s); last two wrong or accuracy ≤ 0.4 → −1.
- Next question: closest difficulty, then a different topic from the previous question, then lower-mastery topics,
  then a different question type, then a stable pseudo-random tiebreak.
- Mastery per topic: EWMA `m ← m + 0.35·(outcome − m)`, outcome = 0.85/0.95/1.0 for correct easy/medium/hard, 0 for
  incorrect; confidence `1 − 0.7^attempts`. Review schedule: correct → interval 1 day, then ×2.2; incorrect → 10 minutes.
  Weak = mastery < 0.6, or due for review with mastery < 0.85.
- These are transparent heuristics, not a trained personalization model, and mastery is an estimate from quiz answers —
  the UI labels it that way. Chapter completion = at least one lesson in the chapter with ≥ 60 % accuracy.

## 8. Model routing and cost control

Per-task models are configured by environment (`SUMMARY_MODEL`, `QA_MODEL`, `QUIZ_MODEL`, `VALIDATION_MODEL`,
`TRANSLATION_MODEL`; defaults `claude-sonnet-5`) with escalation to `ESCALATION_MODEL` (default `claude-opus-5`) when
output fails schema validation. Effort is configurable (`LLM_EFFORT`). Controls: token caps per task, bounded retries
with backoff, `AI_DAILY_BUDGET` (USD per UTC day), per-actor AI rate limit, caching of summaries and question banks,
on-demand generation (nothing is generated at upload time beyond indexing). Every call is logged to `ai_executions`
with tokens, estimated cost (`app/ai/pricing.py`), latency and failure category.

The **extractive** provider implements the same tasks deterministically (selected sentences, verbatim cloze/numeric/
statement questions, lexical judge). It is the default so the product works without keys, and it doubles as the
deterministic "mock LLM" for tests. It cannot translate; requesting another output language returns
`language_unsupported` instead of silently answering in the book's language.

## 9. Prompt versioning

Prompts live in `/prompts/<area>/<id>.md` with front matter (`id`, `version`, `task`) and `# System` / `# User`
sections. Every AI execution, summary and question records the prompt version. Book text is inserted via single-pass
substitution, so text inside a book can never inject template variables. Changing a prompt requires bumping its version
and running the evaluation suite (CI does this on every PR with the offline engine).

## 10. Evaluation framework

`python -m app.evaluations.run [--provider extractive|anthropic]` runs the corpus in `evals/datasets` through the real
API in an isolated database and writes `evals/reports/latest-<provider>.{json,md}` (versions, models, prompt versions,
metrics, gate results, cost, failures, regression vs `evals/baselines/<provider>.json`). Exit code ≠ 0 if a gate fails.

Corpus (original CC0 texts written for Readbit): narrative non-fiction (*The Attentive Mind*, PDF with outline, PDF
without outline, EPUB), technical handbook with sections (*Backyard Compost*, EPUB + PDF), Hindi book (EPUB 2/NCX),
adversarial prompt-injection book, plus fixtures for no-structure, scanned, encrypted and malformed documents. Each
dataset records expected chapters, key facts per chapter, answerable questions with expected answer phrases and evidence,
unanswerable questions and forbidden outputs.

| Metric | Definition |
|---|---|
| `structure.chapter_title_accuracy` | Expected chapter titles detected (fuzzy ≥ 0.9), per fixture |
| `summary.citations_resolvable` | Cited evidence resolves and its excerpt is found in the source passage |
| `summary.claims_with_evidence` | Material claims carrying ≥ 1 citation |
| `summary.citation_precision` | Faithfulness judge: supported = 1, partial = 0.5, unsupported = 0 |
| `summary.unsupported_claim_rate` | Share of claims judged unsupported |
| `summary.key_fact_recall_comprehensive` | Annotated key facts present in comprehensive chapter summaries |
| `summary.book_chapter_coverage` | Chapters covered by the book summary |
| `summary.language_fidelity` | Summary written in the book's language |
| `qa.answer_accuracy` / `qa.evidence_recall` | Expected answer phrase present / expected evidence among citations |
| `qa.abstention_recall` / `qa.abstention_precision` | Unanswerable questions abstained / abstentions that were correct |
| `quiz.structural_validity`, `quiz.key_matches_blind_validator`, `quiz.valid_evidence` | Per approved question |
| `quiz.duplicate_rate` | Near-duplicate approved pairs per approved question |
| `safety.injection_leaks` | Forbidden strings (injected instructions, secrets) found in any output |

**Release gates** (`evals/gates.json`): 100 % structural validity, valid keys and evidence for published questions,
100 % resolvable citations and evidence-backed claims, full chapter coverage, zero injection leaks, and semantic
thresholds (citation precision ≥ 0.9, unsupported ≤ 5 %, key-fact recall ≥ 0.6, answer accuracy ≥ 0.6, evidence recall
≥ 0.6, abstention precision/recall ≥ 0.9, duplicates ≤ 5 %).

### Current results (offline engine, 2026-09-27)

All 17 gates pass: chapter titles 1.0, citations resolvable 1.0, claims with evidence 1.0, citation precision 1.0,
unsupported 0.0, book coverage 1.0, key-fact recall 1.0, language fidelity 1.0, answer accuracy 0.92, evidence recall
1.0, abstention recall/precision 1.0, quiz structure/key/evidence 1.0, duplicates 0.0, injection leaks 0; question
rejection rate 13 %; answer-key share max 33 %.

**How to read these numbers.** For the extractive engine several metrics are close to tautological: its summaries are
verbatim sentences, so a lexical faithfulness judge will score them highly, and its quiz items are designed to be
mechanically verifiable. These results show the *pipeline* (citations, coverage, abstention, validation, dedup,
injection filtering) works end-to-end; they do not measure generative faithfulness. The semantic thresholds were set as
provisional gates from this baseline and must be re-calibrated with the first live-provider run and a human-reviewed
sample before enabling the `anthropic` engine in production. LLM-as-judge results (live run) are supporting evidence,
not proof of correctness.

### Regression procedure

Any change to prompts, models, chunking, retrieval, embeddings, parsers, schemas or validation rules must: run the
offline evaluation (CI does), run the live evaluation when the change affects generative behaviour
(`live-eval.yml`, manual, budget-capped), compare against the baseline in the report, and update
`evals/baselines/<provider>.json` only when the change is an accepted improvement.

## 11. Multilingual behaviour

Interface language (cookie + user preference), document language (detected from script and stopwords), summary/quiz
output language (defaults to the book's language), and user notes are independent. Source evidence is always shown in
the original; `POST /evidence/{id}/translate` returns a machine translation labelled as such (requires a
translation-capable provider). The Hindi evaluation book checks that summaries stay in Hindi.
