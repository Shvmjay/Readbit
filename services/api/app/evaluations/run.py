"""Readbit AI evaluation runner.

Runs the curated evaluation corpus (evals/datasets) through the real pipeline — upload, extraction, chapter
detection, summarization, Q&A and quiz generation — in an isolated temporary database, then computes grounding,
quiz-validity, abstention and safety metrics and checks them against the release gates in evals/gates.json.

    python -m app.evaluations.run                       # offline engine (deterministic, used in CI)
    python -m app.evaluations.run --provider anthropic  # live provider (opt-in; requires LLM_API_KEY; costs money)

Exit code is non-zero when any release gate fails.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EVALS = ROOT / "evals"
EVAL_VERSION = "2026-09-27.1"


def _setup_env(provider: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="readbit-eval-"))
    os.environ.update(
        {
            "APP_ENV": "test",
            "DATABASE_URL": os.environ.get("EVAL_DATABASE_URL", f"sqlite:///{tmp}/eval.db"),
            "JOB_BACKEND": "inline",
            "STORAGE_PROVIDER": "local",
            "STORAGE_LOCAL_PATH": str(tmp / "storage"),
            "DEFAULT_LLM_PROVIDER": provider,
            "USER_RATE_LIMIT": "100000",
            "UPLOAD_RATE_LIMIT": "100000",
            "LOG_LEVEL": "ERROR",
            "SECRET_KEY": os.environ.get("SECRET_KEY", "evaluation-secret-key-0123456789abcdef0123"),
        }
    )
    return tmp


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("’", "'").split())


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


class Evaluator:
    def __init__(self, provider: str) -> None:
        from fastapi.testclient import TestClient

        import app.models  # noqa: F401
        from app.core.db import Base, get_engine
        from app.main import create_app

        Base.metadata.create_all(get_engine())
        self.client = TestClient(create_app())
        self.client.headers.update({"X-Readbit-CSRF": "1"})
        self.client.__enter__()
        r = self.client.post("/api/v1/auth/guest", json={"language": "en", "accepted_privacy": True})
        r.raise_for_status()
        self.provider = provider
        self.m: dict[str, list[float]] = {}
        self.failures: list[dict] = []
        self.outputs: list[str] = []

    def rec(self, metric: str, value: float, **ctx) -> None:
        self.m.setdefault(metric, []).append(float(value))
        if value < 1 and ctx:
            self.failures.append({"metric": metric, "value": value, **ctx})

    # ------------------------------------------------------------------ helpers
    def upload(self, fixture: str) -> dict:
        data = (EVALS / "fixtures" / fixture).read_bytes()
        mime = "application/pdf" if fixture.endswith(".pdf") else "application/epub+zip"
        r = self.client.post("/api/v1/books/upload", files={"file": (fixture, data, mime)})
        r.raise_for_status()
        book = r.json()["book"]
        return self.client.get(f"/api/v1/books/{book['id']}").json()["book"]

    def summary(self, book_id: str, chapter_id: str | None, depth: str) -> dict:
        r = self.client.post(
            f"/api/v1/books/{book_id}/summaries", json={"chapter_id": chapter_id, "depth": depth}
        )
        r.raise_for_status()
        sid = r.json()["summary"]["id"]
        for _ in range(600):
            s = self.client.get(f"/api/v1/books/{book_id}/summaries/{sid}").json()["summary"]
            if s["status"] in ("ready", "failed"):
                return s
            time.sleep(0.5)
        raise TimeoutError("summary did not finish")

    # ------------------------------------------------------------------ suites
    def eval_structure(self, spec: dict) -> None:
        from difflib import SequenceMatcher

        expected = [c["title"] for c in spec["chapters"]]
        for fixture in spec["fixtures"]:
            book = self.upload(fixture)
            if book["processing_status"] != "ready":
                self.rec("structure.chapter_title_accuracy", 0.0, fixture=fixture, reason="not ready")
                continue
            got = [
                c["title"] for c in self.client.get(f"/api/v1/books/{book['id']}/chapters").json()["items"]
            ]
            matched = sum(
                1
                for exp in expected
                if any(SequenceMatcher(None, _norm(exp), _norm(g)).ratio() >= 0.9 for g in got)
            )
            score = (
                matched / len(expected)
                if len(got) == len(expected)
                else matched / max(len(expected), len(got))
            )
            self.rec("structure.chapter_title_accuracy", score, fixture=fixture, expected=expected, got=got)

    def _claims(self, content: dict) -> list[dict]:
        claims = []
        for f in ("central_thesis", "conclusion"):
            if content[f]["text"]:
                claims.append({"text": content[f]["text"], "evidence_ids": content[f]["evidence_ids"]})
        for f, key in (
            ("sections", "content"),
            ("definitions", "definition"),
            ("examples", "description"),
            ("caveats", "text"),
            ("connections", "text"),
            ("takeaways", "text"),
        ):
            for item in content.get(f, []):
                if item.get(key):
                    claims.append({"text": item[key], "evidence_ids": item.get("evidence_ids", [])})
        return claims

    def _judge(self, book_id: str, summary: dict) -> None:
        """Citation precision and unsupported-claim rate via the faithfulness evaluator (lexical offline, LLM judge live)."""
        from app.ai.router import ModelRouter
        from app.core.db import SessionLocal

        claims = self._claims(summary["content"])
        passages: dict[str, str] = {}
        judged_claims = []
        for i, c in enumerate(claims):
            ids = []
            for eid in c["evidence_ids"]:
                ev = self.client.get(f"/api/v1/books/{book_id}/evidence/{eid}")
                ok = ev.status_code == 200 and self._excerpt_in_passage(ev.json()["evidence"])
                self.rec("summary.citations_resolvable", 1.0 if ok else 0.0, book=book_id, evidence=eid)
                if ev.status_code == 200:
                    pid = f"E{len(passages) + 1}"
                    passages[pid] = ev.json()["evidence"]["passage_text"] or ""
                    ids.append(pid)
            self.rec("summary.claims_with_evidence", 1.0 if c["evidence_ids"] else 0.0, claim=c["text"][:120])
            judged_claims.append({"index": i, "text": c["text"], "evidence_ids": ids})
        if not judged_claims:
            return
        rendered_p = "\n".join(f'<passage id="{k}">{v}</passage>' for k, v in passages.items())
        rendered_c = "\n".join(
            f"{c['index']}. {c['text']} [cites: {', '.join(c['evidence_ids'])}]" for c in judged_claims
        )
        with SessionLocal() as db:
            r = ModelRouter(db).generate(
                "source_faithfulness_evaluator",
                variables={"passages": rendered_p, "claims": rendered_c},
                context={
                    "passages": [{"id": k, "text": v} for k, v in passages.items()],
                    "claims": judged_claims,
                },
                output_language=summary["output_language"],
            )
            db.commit()
        for j in r.data["judgements"]:
            v = j["verdict"]
            text = (
                judged_claims[j["claim_index"]]["text"][:160] if j["claim_index"] < len(judged_claims) else ""
            )
            self.rec(
                "summary.citation_precision",
                {"supported": 1.0, "partial": 0.5}.get(v, 0.0),
                claim=text,
                verdict=v,
            )
            self.m.setdefault("summary.unsupported_claim_rate", []).append(1.0 if v == "unsupported" else 0.0)

    @staticmethod
    def _excerpt_in_passage(ev: dict) -> bool:
        excerpt = ev["excerpt"].rstrip("…").strip()
        return _norm(excerpt[:120]) in _norm(ev.get("passage_text") or "")

    def eval_summaries(self, spec: dict) -> None:
        from app.document_processing.text import detect_language

        book = self.upload(spec["fixtures"][0])
        bid = book["id"]
        chapters = self.client.get(f"/api/v1/books/{bid}/chapters").json()["items"]
        for ch, exp in zip(chapters, spec["chapters"], strict=False):
            s = self.summary(bid, ch["id"], "comprehensive")
            if s["status"] != "ready":
                self.rec("summary.generation_success", 0.0, chapter=ch["title"], error=s.get("error"))
                continue
            self.rec("summary.generation_success", 1.0)
            text = (
                " ".join(c["text"] for c in self._claims(s["content"]))
                + " "
                + " ".join(k for sec in s["content"]["sections"] for k in sec["key_concepts"])
            )
            self.outputs.append(text)
            for fact in exp["key_facts"]:
                self.rec(
                    "summary.key_fact_recall_comprehensive",
                    1.0 if _norm(fact) in _norm(text) else 0.0,
                    chapter=ch["title"],
                    fact=fact,
                )
            lang = detect_language(text)
            self.rec(
                "summary.language_fidelity",
                1.0
                if lang in (None, spec["language"]) and (lang == spec["language"] or len(text) < 200)
                else 0.0,
                chapter=ch["title"],
                detected=lang,
            )
            self._judge(bid, s)
        for depth in ("concise", "balanced"):
            s = self.summary(bid, chapters[0]["id"], depth)
            self.rec("summary.generation_success", 1.0 if s["status"] == "ready" else 0.0, depth=depth)
        s = self.summary(bid, None, "balanced")
        if s["status"] == "ready":
            cov = s["content"]["coverage"]
            self.rec(
                "summary.book_chapter_coverage",
                cov["chapters_covered"] / max(1, cov["chapters_total"]),
                book=spec["book"],
            )
            self.outputs.append(" ".join(c["text"] for c in self._claims(s["content"])))
            self._judge(bid, s)
        else:
            self.rec("summary.book_chapter_coverage", 0.0, book=spec["book"], error=s.get("error"))
        self._book_ids = getattr(self, "_book_ids", {})
        self._book_ids[spec["book"]] = bid

    def eval_qa(self, spec: dict) -> None:
        bid = self._book_ids[spec["book"]]
        for item in spec["answerable"]:
            r = self.client.post(f"/api/v1/books/{bid}/questions", json={"question": item["question"]}).json()
            answer = r.get("answer") or ""
            self.outputs.append(answer)
            ok = r["answerable"] and any(_norm(e) in _norm(answer) for e in item["expect_any"])
            self.rec("qa.answer_accuracy", 1.0 if ok else 0.0, question=item["question"], answer=answer[:200])
            found = False
            for c in r.get("citations", []):
                ev = self.client.get(f"/api/v1/books/{bid}/evidence/{c['id']}").json()["evidence"]
                if _norm(item["evidence_contains"]) in _norm(ev["passage_text"] or ""):
                    found = True
            self.rec("qa.evidence_recall", 1.0 if found else 0.0, question=item["question"])
            self.m.setdefault("_qa.abstained_on_answerable", []).append(0.0 if r["answerable"] else 1.0)
        for q in spec["unanswerable"]:
            r = self.client.post(f"/api/v1/books/{bid}/questions", json={"question": q}).json()
            self.outputs.append(r.get("answer") or "")
            self.rec(
                "qa.abstention_recall",
                0.0 if r["answerable"] else 1.0,
                question=q,
                answer=(r.get("answer") or "")[:200],
            )

    def eval_quiz(self, spec: dict) -> None:
        import uuid

        from sqlalchemy import select

        from app.ai.embeddings import cosine
        from app.core.db import SessionLocal
        from app.models.books import EvidenceReference
        from app.models.learning import Question
        from app.services.quiz_service import structural_problems

        bid = self._book_ids[spec["book"]]
        chapters = self.client.get(f"/api/v1/books/{bid}/chapters").json()["items"]
        for ch in chapters:
            self.client.post(f"/api/v1/books/{bid}/quiz-sessions", json={"chapter_id": ch["id"]})
        with SessionLocal() as db:
            qs = list(db.scalars(select(Question).where(Question.book_id == uuid.UUID(bid))))
            approved = [q for q in qs if q.validation_status == "approved"]
            self.m.setdefault("quiz.approved_count", []).append(float(len(approved)))
            self.m.setdefault("quiz.rejection_rate", []).append(1 - len(approved) / len(qs) if qs else 0.0)
            answers = []
            for q in approved:
                cand = {
                    "question": q.question_text,
                    "question_type": q.question_type,
                    "difficulty": q.difficulty,
                    "options": q.options_json,
                    "correct_key": q.correct_option_key,
                    "evidence_ids": q.validation_report.get("passage_ids", []),
                    "explanation": q.explanation,
                }
                problems = structural_problems(cand, set(cand["evidence_ids"]))
                self.rec(
                    "quiz.structural_validity",
                    0.0 if problems else 1.0,
                    question=q.question_text[:120],
                    problems=problems,
                )
                sem = q.validation_report.get("semantic", {})
                self.rec(
                    "quiz.key_matches_blind_validator",
                    1.0 if sem.get("validator_key") == q.correct_option_key else 0.0,
                    question=q.question_text[:120],
                )
                evs = [db.get(EvidenceReference, uuid.UUID(e)) for e in q.evidence_ids]
                self.rec(
                    "quiz.valid_evidence",
                    1.0 if evs and all(e is not None and e.book_id == q.book_id for e in evs) else 0.0,
                    question=q.question_text[:120],
                )
                answers.append(q.correct_option_key)
                self.outputs.append(q.question_text + " " + q.explanation)
            dup = 0
            for i, a in enumerate(approved):
                for b in approved[i + 1 :]:
                    if a.chapter_id == b.chapter_id and (
                        a.semantic_fingerprint == b.semantic_fingerprint
                        or cosine(a.embedding, b.embedding) >= 0.9
                    ):
                        dup += 1
                        self.failures.append(
                            {
                                "metric": "quiz.duplicate_rate",
                                "a": a.question_text[:100],
                                "b": b.question_text[:100],
                            }
                        )
            self.m.setdefault("quiz.duplicate_rate", []).append(dup / max(1, len(approved)))
            if answers:
                top = max(answers.count(k) for k in "ABCD") / len(answers)
                self.m.setdefault("quiz.max_answer_key_share", []).append(top)
            types = {
                t: sum(1 for q in approved if q.question_type == t)
                for t in ("recall", "comprehension", "application", "inference")
            }
            self.m.setdefault("_quiz.type_distribution", []).append(0.0)
            self.type_distribution = getattr(self, "type_distribution", {})
            self.type_distribution[spec["book"]] = types

    def eval_safety(self, specs: list[dict]) -> None:
        forbidden = [f for s in specs for f in s.get("forbidden_output", [])]
        blob = _norm(" ".join(self.outputs))
        leaks = [f for f in forbidden if _norm(f) in blob]
        self.m["safety.injection_leaks"] = [float(len(leaks))]
        if leaks:
            self.failures.append({"metric": "safety.injection_leaks", "leaks": leaks})

    # ------------------------------------------------------------------ report
    def results(self) -> dict:
        metrics = {k: _mean(v) for k, v in self.m.items() if not k.startswith("_")}
        metrics["safety.injection_leaks"] = max(self.m.get("safety.injection_leaks", [0.0]))
        abstained_answerable = sum(self.m.get("_qa.abstained_on_answerable", []))
        abstained_unanswerable = sum(self.m.get("qa.abstention_recall", []))
        total_abstentions = abstained_answerable + abstained_unanswerable
        metrics["qa.abstention_precision"] = (
            round(abstained_unanswerable / total_abstentions, 4) if total_abstentions else 1.0
        )
        return metrics


def check_gates(metrics: dict) -> list[dict]:
    gates = json.loads((EVALS / "gates.json").read_text())["gates"]
    out = []
    for name, rule in gates.items():
        value = metrics.get(name)
        ok = (
            value is not None
            and ("min" not in rule or value >= rule["min"])
            and ("max" not in rule or value <= rule["max"])
        )
        out.append({"gate": name, "value": value, **rule, "passed": ok})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="extractive", choices=["extractive", "anthropic"])
    ap.add_argument("--books", nargs="*", default=None, help="subset of dataset ids")
    ap.add_argument("--out", default=str(EVALS / "reports"))
    args = ap.parse_args()
    if args.provider == "anthropic" and not os.environ.get("LLM_API_KEY"):
        print("LLM_API_KEY is required for the live-provider evaluation.", file=sys.stderr)
        return 2
    _setup_env(args.provider)
    specs = [json.loads(p.read_text()) for p in sorted((EVALS / "datasets").glob("*.eval.json"))]
    if args.books:
        specs = [s for s in specs if s["book"] in args.books]
    started = time.monotonic()
    ev = Evaluator(args.provider)
    for spec in specs:
        ev.eval_structure(spec)
        ev.eval_summaries(spec)
        ev.eval_qa(spec)
        ev.eval_quiz(spec)
    ev.eval_safety(specs)
    metrics = ev.results()
    gates = check_gates(metrics)

    from sqlalchemy import func, select

    from app.ai.prompts import all_prompt_ids, load_prompt
    from app.core.config import get_settings
    from app.core.db import SessionLocal
    from app.models.ops import AIExecution

    with SessionLocal() as db:
        cost = db.scalar(select(func.coalesce(func.sum(AIExecution.estimated_cost), 0.0)))
        calls = db.scalar(select(func.count()).select_from(AIExecution))
    s = get_settings()
    report = {
        "evaluation_version": EVAL_VERSION,
        "dataset_version": json.loads((EVALS / "gates.json").read_text())["version"],
        "run_at": datetime.now(UTC).isoformat(),
        "provider": args.provider,
        "models": {
            "summary": s.summary_model,
            "qa": s.qa_model,
            "quiz": s.quiz_model,
            "validation": s.validation_model,
        }
        if args.provider != "extractive"
        else {"all": "extractive-v1"},
        "prompt_versions": {pid: load_prompt(pid).version for pid in all_prompt_ids()},
        "books": [sp["book"] for sp in specs],
        "metrics": metrics,
        "quiz_type_distribution": getattr(ev, "type_distribution", {}),
        "gates": gates,
        "passed": all(g["passed"] for g in gates),
        "ai_calls": calls,
        "estimated_cost_usd": round(float(cost or 0.0), 4),
        "duration_seconds": round(time.monotonic() - started, 1),
        "failures": ev.failures[:200],
    }
    baseline_path = EVALS / "baselines" / f"{args.provider}.json"
    if baseline_path.exists():
        base = json.loads(baseline_path.read_text())["metrics"]
        report["regression"] = {
            k: {"baseline": base.get(k), "current": v, "delta": round(v - base[k], 4)}
            for k, v in metrics.items()
            if isinstance(v, int | float) and isinstance(base.get(k), int | float) and v != base[k]
        }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"latest-{args.provider}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (out / f"latest-{args.provider}.md").write_text(_markdown(report))
    print(_markdown(report))
    return 0 if report["passed"] else 1


def _markdown(r: dict) -> str:
    lines = [
        f"# Readbit evaluation — {r['provider']}",
        "",
        f"Run {r['run_at']} · eval {r['evaluation_version']} · dataset {r['dataset_version']} · "
        f"{r['ai_calls']} AI calls · ${r['estimated_cost_usd']} · {r['duration_seconds']}s",
        "",
        "| Gate | Value | Threshold | Result |",
        "|---|---|---|---|",
    ]
    for g in r["gates"]:
        thr = f">= {g['min']}" if "min" in g else f"<= {g['max']}"
        lines.append(f"| {g['gate']} | {g['value']} | {thr} | {'PASS' if g['passed'] else 'FAIL'} |")
    lines += ["", "| Metric | Value |", "|---|---|"] + [
        f"| {k} | {v} |" for k, v in sorted(r["metrics"].items())
    ]
    if r.get("regression"):
        lines += ["", "Changes vs baseline:", ""] + [
            f"- {k}: {v['baseline']} → {v['current']} ({v['delta']:+})" for k, v in r["regression"].items()
        ]
    lines += ["", f"**Overall: {'PASSED' if r['passed'] else 'FAILED'}**"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
