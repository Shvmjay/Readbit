"""Unit tests: prompts, model router (retries, schema enforcement, escalation, budget), extractive engine,
question validation/deduplication helpers, and learning algorithms."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.ai.embeddings import HashingEmbedder, cosine
from app.ai.prompts import all_prompt_ids, load_prompt
from app.ai.providers.base import GenerationRequest, GenerationResult, LLMProvider, ProviderError
from app.ai.providers.extractive import ExtractiveProvider
from app.ai.router import ModelRouter, set_provider_override
from app.ai.schemas import SCHEMAS
from app.core.db import SessionLocal
from app.core.errors import AppError, ErrorCode
from app.models.ops import AIExecution
from app.services import learning_service as ls
from app.services.quiz_service import fingerprint, structural_problems
from tests.conftest import FIXTURES

REQUIRED_PROMPTS = {
    "chapter_detector",
    "document_extraction_repair",
    "summary_generator",
    "book_summary_aggregator",
    "book_qa",
    "quiz_question_generator",
    "quiz_question_validator",
    "answer_explainer",
    "translation",
    "source_faithfulness_evaluator",
}


def load_book(book_id="attentive_mind"):
    book = json.loads((FIXTURES.parent / "datasets" / "books" / f"{book_id}.json").read_text())
    chapters, n = [], 0
    for ch in book["chapters"]:
        paras = ch.get("paragraphs") or [p for s in ch["sections"] for p in s["paragraphs"]]
        items = []
        for p in paras:
            n += 1
            items.append({"id": f"P{n}", "text": p, "section": None})
        chapters.append(items)
    return book, chapters


# ------------------------------------------------------------------ prompts
def test_all_required_prompts_exist_and_are_versioned():
    assert REQUIRED_PROMPTS <= set(all_prompt_ids())
    for pid in all_prompt_ids():
        t = load_prompt(pid)
        assert t.version and t.id == pid
        system, _ = t.render(passages="", question="", output_language="en")
        assert "untrusted DATA" in system, pid  # every prompt carries the shared source/safety rules
        assert pid in SCHEMAS


def test_prompt_substitution_never_re_expands_untrusted_text():
    _, user = load_prompt("book_qa").render(
        passages="{{shared_rules}} {{question}}", question="Q?", book_title="B", scope_line=""
    )
    assert "{{shared_rules}} {{question}}" in user


# ------------------------------------------------------------------ router
class ScriptedProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate(self, request, timeout):
        self.calls.append(request.model)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return GenerationResult(
            data=item, provider="anthropic", model=request.model, input_tokens=1000, output_tokens=200
        )


QA_OK = {
    "answerable": True,
    "answer": "x",
    "evidence_ids": ["P1"],
    "confidence": "high",
    "unanswerable_reason": "",
    "language_ok": True,
}


@pytest.fixture
def paid_router(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setattr("time.sleep", lambda s: None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _gen(db, **kw):
    return ModelRouter(db).generate(
        "book_qa",
        variables={"book_title": "B", "question": "Q", "passages": "", "scope_line": ""},
        context={},
        **kw,
    )


def test_router_retries_transient_errors_then_succeeds(paid_router):
    prov = ScriptedProvider([ProviderError("rl", retryable=True, category="rate_limited"), QA_OK])
    set_provider_override("anthropic", prov)
    with SessionLocal() as db:
        r = _gen(db)
        assert r.data["answer"] == "x" and len(prov.calls) == 2
        assert r.cost > 0
        rows = db.query(AIExecution).all()
        assert [row.success for row in rows] == [False, True]
        assert rows[0].failure_category == "rate_limited"


def test_router_escalates_on_schema_invalid_output(paid_router):
    prov = ScriptedProvider([{"answer": "missing fields"}, QA_OK])
    set_provider_override("anthropic", prov)
    with SessionLocal() as db:
        _gen(db)
    assert prov.calls == ["claude-sonnet-5", "claude-opus-5"]


def test_router_fails_closed_when_output_never_valid(paid_router):
    set_provider_override("anthropic", ScriptedProvider([{"bad": 1}, {"bad": 2}]))
    with SessionLocal() as db, pytest.raises(AppError) as exc:
        _gen(db)
    assert exc.value.code == ErrorCode.AI_OUTPUT_INVALID


def test_router_provider_outage_is_reported_as_unavailable(paid_router):
    errs = [ProviderError("down", retryable=True, category="connection") for _ in range(6)]
    set_provider_override("anthropic", ScriptedProvider(errs))
    with SessionLocal() as db, pytest.raises(AppError) as exc:
        _gen(db)
    assert exc.value.code == ErrorCode.AI_PROVIDER_UNAVAILABLE


def test_router_enforces_daily_budget(paid_router, monkeypatch):
    monkeypatch.setenv("AI_DAILY_BUDGET", "0.01")
    from app.core.config import get_settings

    get_settings.cache_clear()
    set_provider_override("anthropic", ScriptedProvider([QA_OK]))
    with SessionLocal() as db:
        db.add(
            AIExecution(
                task_type="x", provider="anthropic", model="m", prompt_version="v", estimated_cost=1.0
            )
        )
        db.commit()
        with pytest.raises(AppError) as exc:
            _gen(db)
    assert exc.value.code == ErrorCode.AI_BUDGET_EXCEEDED


def test_router_rejects_language_the_model_could_not_write(paid_router):
    set_provider_override("anthropic", ScriptedProvider([{**QA_OK, "language_ok": False}]))
    with SessionLocal() as db, pytest.raises(AppError) as exc:
        _gen(db, output_language="hi")
    assert exc.value.code == ErrorCode.LANGUAGE_UNSUPPORTED


def test_offline_engine_refuses_translation_instead_of_answering_in_another_language():
    with SessionLocal() as db, pytest.raises(AppError) as exc:
        ModelRouter(db).generate(
            "book_qa",
            variables={"book_title": "", "question": "", "passages": "", "scope_line": ""},
            context={},
            output_language="hi",
            source_language="en",
        )
    assert exc.value.code == ErrorCode.LANGUAGE_UNSUPPORTED


# ------------------------------------------------------------------ extractive engine
def _run(task, ctx, lang="en"):
    req = GenerationRequest(
        task, "v", "", "", SCHEMAS[task], "extractive-v1", 100, output_language=lang, context=ctx
    )
    return ExtractiveProvider().generate(req, 10).data


def test_extractive_summary_is_verbatim_and_cited():
    _, chapters = load_book()
    text = " ".join(p["text"] for p in chapters[0])
    s = _run(
        "summary_generator",
        {"passages": chapters[0], "depth": "comprehensive", "chapter_title": "Ch 1", "max_quote_ratio": 0.35},
    )
    assert "argues" in s["central_thesis"]["text"]
    claims = [s["central_thesis"]] + s["takeaways"] + s["caveats"]
    for c in claims:
        assert c["evidence_ids"] and c["text"] in text  # no invented sentences
    assert any("switching tax" == d["term"] for d in s["definitions"])


def test_extractive_summary_excludes_injected_instructions():
    _, chapters = load_book("injection_test")
    s = _run(
        "summary_generator",
        {"passages": chapters[0], "depth": "comprehensive", "chapter_title": "Ch", "max_quote_ratio": 0.35},
    )
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in json.dumps(s)


def test_extractive_qa_abstains_on_out_of_book_questions():
    _, chapters = load_book()
    passages = [p for ch in chapters for p in ch]
    assert not _run("book_qa", {"question": "What is the capital of France?", "passages": passages})[
        "answerable"
    ]
    r = _run(
        "book_qa",
        {"question": "What does the author call the time needed to rebuild context?", "passages": passages},
    )
    assert r["answerable"] and "switching tax" in r["answer"]


def test_extractive_questions_pass_blind_validation():
    _, chapters = load_book()
    for chapter in chapters:
        data = _run(
            "quiz_question_generator",
            {"passages": chapter, "count": 5, "chapter_title": "Chapter", "seed": 3},
        )
        assert data["questions"]
        for q in data["questions"]:
            assert structural_problems(q, {p["id"] for p in chapter}) == []
            blind = {"question": q["question"], "options": q["options"], "explanation": q["explanation"]}
            v = _run("quiz_question_validator", {"question": blind, "passages": chapter})
            assert v["answer_key"] == q["correct_key"], q


def test_validator_rejects_question_with_two_supported_options():
    _, chapters = load_book()
    q = {
        "question": "Which statement is supported by Chapter 1?",
        "explanation": "",
        "options": [
            {"key": "A", "text": "Attention is the scarcest resource a reader owns."},
            {"key": "B", "text": "The switching tax is small for a single interruption, but it compounds."},
            {"key": "C", "text": "Attention is plentiful."},
            {"key": "D", "text": "Readers never switch tasks."},
        ],
    }
    v = _run("quiz_question_validator", {"question": q, "passages": chapters[0]})
    assert v["answer_key"] == "none" and not v["checks"]["unambiguous"]


# ------------------------------------------------------------------ structural checks + dedup helpers
def _q(**over):
    base = {
        "question": "Which term fits?",
        "question_type": "recall",
        "difficulty": 1,
        "topic": "t",
        "options": [
            {"key": k, "text": t} for k, t in zip("ABCD", ["alpha", "beta", "gamma", "delta"], strict=True)
        ],
        "correct_key": "B",
        "evidence_ids": ["P1"],
        "explanation": "Because.",
        "misconception": "",
    }
    base.update(over)
    return base


def test_structural_checks():
    assert structural_problems(_q(), {"P1"}) == []
    assert "not_four_options" in structural_problems(_q(options=_q()["options"][:3]), {"P1"})
    dup = _q(options=[{"key": k, "text": "same"} for k in "ABCD"])
    assert "duplicate_options" in structural_problems(dup, {"P1"})
    assert "no_valid_evidence" in structural_problems(_q(evidence_ids=["P99"]), {"P1"})
    long = _q(
        options=[
            {"key": "A", "text": "a"},
            {"key": "B", "text": "b" * 120},
            {"key": "C", "text": "c"},
            {"key": "D", "text": "d"},
        ]
    )
    assert "length_reveals_answer" in structural_problems(long, {"P1"})


def test_fingerprint_is_order_insensitive_and_embeddings_detect_near_duplicates():
    assert fingerprint("What is the switching tax?", "time") == fingerprint(
        "the switching tax is what?", "time"
    )
    e = HashingEmbedder(256)
    a, b, c = e.embed(
        [
            "What does the author call the switching tax?",
            "What does the author call the switching tax cost?",
            "How warm does a compost pile get?",
        ]
    )
    assert cosine(a, b) > 0.8 > cosine(a, c)


# ------------------------------------------------------------------ learning algorithms
def test_adaptive_difficulty_rules():
    assert ls.next_difficulty(1, [True, True], [None, None]) == 2
    assert ls.next_difficulty(3, [True, True], [None, None]) == 3
    assert ls.next_difficulty(2, [True, False, False], [None] * 3) == 1
    assert ls.next_difficulty(2, [True], [None]) == 2
    assert (
        ls.next_difficulty(1, [True, True], [None, 60_000]) == 1
    )  # slow correct answers do not raise difficulty


def test_weakness_detection():
    class M:
        attempts_count = 2
        mastery_score = 0.3
        next_review_at = None

    assert ls.is_weak(M())
    M.mastery_score = 0.9
    assert not ls.is_weak(M())
    M.mastery_score, M.next_review_at = 0.7, datetime.now(UTC) - timedelta(hours=1)
    assert ls.is_weak(M())
