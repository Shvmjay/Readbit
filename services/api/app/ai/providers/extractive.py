"""Offline extractive engine.

A deterministic provider that needs no API key. It never writes new claims: summaries are built from sentences
selected from the book, answers quote the best-supported sentences, and quiz questions are derived from source
sentences (cloze, numeric recall and statement-verification items) so that every answer key can be checked
mechanically against the text. It also serves as the deterministic "mock LLM" for automated tests.

Limitations (documented in docs/AI_GROUNDING.md): no paraphrasing, no translation, no application/inference
questions, and headings are derived from the book's own section titles or key terms.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from app.ai.providers.base import GenerationRequest, GenerationResult, LLMProvider, ProviderError
from app.document_processing.text import (
    STOPWORDS,
    content_words,
    detect_language,
    fuzzy_contains,
    normalize_for_match,
    split_sentences,
    token_overlap,
    tokenize,
)

MODEL = "extractive-v1"
BLANK = "_____"

EXAMPLE_CUES = re.compile(
    r"\b(for example|for instance|such as|consider|in one study|observed|case study|story of|the example of|named|"
    r"workshop|account of|illustration|experiment|उदाहरण)\b",
    re.I,
)
CAVEAT_CUES = re.compile(
    r"\b(however|although|though|does not claim|not always|caveat|acknowledges|cannot show|warns|cautions|unless|"
    r"limitation|may not|not as a proven|cannot)\b",
    re.I,
)
CONCLUSION_CUES = re.compile(r"\b(concludes|in conclusion|closes|ends by|ends with|finally|overall|in short)\b", re.I)
THESIS_CUES = re.compile(r"\b(argues|claims|central idea|main idea|the central|thesis|contends|the author)\b", re.I)
DEFINITION_CUES = re.compile(
    r"\b(defines?|definition|is called|calls this|calls it|refers to|known as|is the (?:sense|ability|idea|finding)|"
    r"we call|she calls|he calls|कहती हैं|कहते हैं)\b",
    re.I,
)
INJECTION = re.compile(
    r"(ignore (all )?(previous|prior|above) instructions|system prompt|developer mode|you are now|api key|"
    r"^system\s*:|the assistant must)",
    re.I,
)
NUMBER_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twelve", "fifteen",
                "twenty", "twenty-five", "thirty", "forty", "fifty", "sixty", "hundred"]
NUMBER_PHRASE = re.compile(
    r"\b((?:\d+(?:[.,]\d+)?|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"
    r"(?:\s+(?:and|to|or)\s+(?:\d+(?:[.,]\d+)?|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r"))?"
    r"\s+(?:[a-z]+\s+)?(?:minutes?|hours?|days?|weeks?|months?|years?|times?|parts?|steps?|degrees?(?:\s+celsius)?|"
    r"centimetres?|metres?|kilometres?|cubic metres?|ideas|questions|kinds|groups))\b",
    re.I,
)
TERM_PATTERNS = [
    re.compile(r"\bcalls? (?:this|it|them)(?: [a-z]+)? (?:the )?([a-z][a-z\- ]{2,40}?)(?=[,.;:]| and\b)", re.I),
    re.compile(r"\b(?:idea|concept|method|practice|principle) (?:of |called |(?:she|he|they|the author) calls? )(?:the )?([a-z][a-z\- ]{2,40}?)(?=[,.;:])", re.I),
    re.compile(r"\bknown as (?:the )?([a-z][a-z\- ]{2,40}?)(?=[,.;:])", re.I),
    re.compile(r"\bthe ([a-z]+ effect)\b", re.I),
    re.compile(r"^([A-Z][a-z]+(?: [a-z]+){0,2})(?:, [^,]{0,60},)? (?:is|are) (?:the|a|an) ", 0),
    re.compile(r"\bcalls? (?:carbon-rich|nitrogen-rich) material ([a-z]+)\b", re.I),
]
COMMON_VERBS = frozenset(
    "argues says writes notes describes recommends suggests explains reports treats warns becomes remains makes "
    "takes gives keeps uses needs finds seems appears allows leads produces feels works reading author chapter "
    "book because another before during every people person reader readers".split()
)


@dataclass
class Sent:
    text: str
    pid: str
    pos: int  # global order
    passage_index: int
    section: str | None
    score: float = 0.0


def _stem(t: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def _stems(text: str) -> set[str]:
    return {_stem(t) for t in content_words(text)}


def _seed(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def _sentences(passages: list[dict]) -> list[Sent]:
    out: list[Sent] = []
    for pi, p in enumerate(passages):
        for s in split_sentences(p["text"]):
            if len(s.split()) >= 4 and not INJECTION.search(s):
                out.append(Sent(s, p["id"], len(out), pi, p.get("section")))
    return out


def _score(sents: list[Sent], df: Counter[str] | None = None, n_docs: int = 1) -> Counter[str]:
    tf: Counter[str] = Counter()
    for s in sents:
        tf.update(_stems(s.text))
    for s in sents:
        stems = _stems(s.text)
        if not stems:
            continue
        weight = 0.0
        for st in stems:
            idf = math.log((1 + n_docs) / (1 + (df or {}).get(st, 0))) + 1 if df else 1.0
            weight += math.log(1 + tf[st]) * idf
        s.score = weight / math.sqrt(len(stems) + 4)
        if THESIS_CUES.search(s.text):
            s.score *= 1.25
        if DEFINITION_CUES.search(s.text):
            s.score *= 1.15
    return tf


def _key_terms(text_units: list[str], limit: int = 8) -> list[str]:
    """Key terms from the source (definitional patterns first, then frequent bigrams/unigrams)."""
    counts: Counter[str] = Counter()
    defined: list[str] = []
    for unit in text_units:
        for s in split_sentences(unit):
            for pat in TERM_PATTERNS:
                for m in pat.finditer(s):
                    term = re.sub(r"\s+", " ", m.group(1)).strip(" -").lower()
                    term = re.sub(r"^(the|a|an) ", "", term)
                    if 3 <= len(term) <= 40 and term not in STOPWORDS and not set(term.split()) & COMMON_VERBS:
                        if term not in defined:
                            defined.append(term)
        toks = [t for t in tokenize(unit)]
        for a, b in zip(toks, toks[1:], strict=False):
            if a not in STOPWORDS and b not in STOPWORDS and len(a) > 2 and len(b) > 2 and not (a.isdigit() or b.isdigit()) and not a.endswith("ed"):
                if not ({a, b} & COMMON_VERBS):
                    counts[f"{a} {b}"] += 1
        for t in content_words(unit):
            if len(t) >= 5 and t not in COMMON_VERBS and not t.endswith(("ly", "ing", "ed")):
                counts[t] += 1
    frequent = [t for t, c in counts.most_common(60) if (c >= 2 and " " in t) or c >= 3]
    # Prefer bigrams over the unigrams they contain.
    result = list(defined)
    for t in frequent:
        if t in result or any(t in r or r in t for r in result):
            continue
        result.append(t)
        if len(result) >= limit:
            break
    return result[:limit]


DEPTH = {
    "concise": {"sections": 2, "per_section": 2, "examples": 1, "caveats": 1, "definitions": 2, "takeaways": 3, "ratio": 0.45},
    "balanced": {"sections": 4, "per_section": 3, "examples": 2, "caveats": 2, "definitions": 3, "takeaways": 4, "ratio": 0.7},
    "comprehensive": {"sections": 6, "per_section": 5, "examples": 4, "caveats": 4, "definitions": 5, "takeaways": 5, "ratio": 1.0},
}


class ExtractiveProvider(LLMProvider):
    name = "extractive"

    def supports_language(self, task: str, output_language: str, source_language: str | None) -> bool:
        # Extractive output is in the book's own language; it cannot translate.
        if task in ("translation",):
            return False
        return source_language is None or output_language == source_language

    def generate(self, request: GenerationRequest, timeout: float) -> GenerationResult:
        handler = getattr(self, f"_task_{request.task}", None)
        if handler is None:
            raise ProviderError(f"task {request.task} unsupported offline", retryable=False, category="unsupported")
        data = handler(request.context, request)
        return GenerationResult(data=data, provider=self.name, model=MODEL)

    # ------------------------------------------------------------------ summaries
    def _summarize(self, passages: list[dict], depth: str, title: str, max_ratio: float) -> dict[str, Any]:
        cfg = DEPTH.get(depth, DEPTH["balanced"])
        sents = _sentences(passages)
        if not sents:
            return self._empty_summary(title, "No readable text was found in this part of the book.")
        _score(sents, *(self._df(passages)))
        total_words = sum(len(p["text"].split()) for p in passages)
        budget_words = max(60, int(total_words * max_ratio * cfg["ratio"]))
        used: set[int] = set()

        def take(s: Sent) -> dict:
            used.add(s.pos)
            return {"text": s.text, "evidence_ids": [s.pid]}

        early = [s for s in sents if s.pos <= max(1, int(len(sents) * 0.4))]
        def thesis_score(s: Sent) -> float:
            bonus = 1.0 if THESIS_CUES.search(s.text) else 0.0
            bonus += 0.4 if s.pos < 2 else 0.0
            bonus -= 1.0 if EXAMPLE_CUES.search(s.text) or CAVEAT_CUES.search(s.text) else 0.0
            return s.score + bonus

        thesis_s = max(early or sents, key=thesis_score)
        thesis = take(thesis_s)

        concl_candidates = [s for s in sents if CONCLUSION_CUES.search(s.text) and s.pos not in used]
        concl_s = concl_candidates[-1] if concl_candidates else (sents[-1] if sents[-1].pos not in used else None)
        conclusion = take(concl_s) if concl_s else {"text": "", "evidence_ids": []}

        definitions = []
        for s in sorted((s for s in sents if DEFINITION_CUES.search(s.text) and s.pos not in used), key=lambda s: -s.score):
            terms = _key_terms([s.text], 1)
            if terms:
                definitions.append({"term": terms[0], "definition": s.text, "evidence_ids": [s.pid]})
                used.add(s.pos)
            if len(definitions) >= cfg["definitions"]:
                break
        definitions.sort(key=lambda d: next(x.pos for x in sents if x.text == d["definition"]))

        examples = [
            {"description": s.text, "evidence_ids": [s.pid]}
            for s in sorted((s for s in sents if EXAMPLE_CUES.search(s.text) and s.pos not in used), key=lambda s: -s.score)[: cfg["examples"]]
        ]
        for e in examples:
            used.update(s.pos for s in sents if s.text == e["description"])
        caveats = [
            {"text": s.text, "evidence_ids": [s.pid]}
            for s in sorted((s for s in sents if CAVEAT_CUES.search(s.text) and s.pos not in used), key=lambda s: -s.score)[: cfg["caveats"]]
        ]
        for c in caveats:
            used.update(s.pos for s in sents if s.text == c["text"])

        # Sections: the book's own section titles when present, otherwise contiguous groups of passages.
        groups: list[tuple[str | None, list[Sent]]] = []
        sections_present = [p.get("section") for p in passages]
        if len({s for s in sections_present if s}) >= 2:
            for s in sents:
                if not groups or groups[-1][0] != s.section:
                    groups.append((s.section, []))
                groups[-1][1].append(s)
        else:
            n_groups = min(cfg["sections"], max(1, len(passages)), max(1, len(sents) // 3))
            per = math.ceil(len(passages) / n_groups)
            for g in range(n_groups):
                members = [s for s in sents if g * per <= s.passage_index < (g + 1) * per]
                if members:
                    groups.append((None, members))
        groups = groups[: cfg["sections"]]
        words_used = sum(len(s.text.split()) for s in sents if s.pos in used)
        sections = []
        for heading, members in groups:
            picks = sorted((s for s in members if s.pos not in used), key=lambda s: -s.score)[: cfg["per_section"]]
            picks = [s for s in picks if (words_used := words_used + len(s.text.split())) <= budget_words or not sections]
            if not picks:
                continue
            picks.sort(key=lambda s: s.pos)
            for s in picks:
                used.add(s.pos)
            terms = _key_terms([s.text for s in members], 3)
            sections.append(
                {
                    "heading": heading or (terms[0].capitalize() if terms else "Key passages"),
                    "content": " ".join(s.text for s in picks),
                    "key_concepts": terms,
                    "evidence_ids": sorted({s.pid for s in picks}, key=lambda x: int(x[1:]) if x[1:].isdigit() else 0),
                }
            )
        remaining = sorted((s for s in sents if s.pos not in used), key=lambda s: -s.score)
        takeaway_src = remaining[: cfg["takeaways"]]
        if len(takeaway_src) < 2:
            takeaway_src = sorted(sents, key=lambda s: -s.score)[: cfg["takeaways"]]
        takeaways = [{"text": s.text, "evidence_ids": [s.pid]} for s in sorted(takeaway_src, key=lambda s: s.pos)]
        return {
            "title": title,
            "central_thesis": thesis,
            "sections": sections,
            "definitions": definitions,
            "examples": examples,
            "caveats": caveats,
            "connections": [],
            "conclusion": conclusion,
            "takeaways": takeaways,
            "known_gaps": [],
            "language_ok": True,
        }

    @staticmethod
    def _df(passages: list[dict]) -> tuple[Counter[str] | None, int]:
        df: Counter[str] = Counter()
        for p in passages:
            df.update(_stems(p["text"]))
        return (df, len(passages)) if len(passages) > 1 else (None, 1)

    @staticmethod
    def _empty_summary(title: str, gap: str) -> dict[str, Any]:
        empty = {"text": "", "evidence_ids": []}
        return {"title": title, "central_thesis": empty, "sections": [], "definitions": [], "examples": [],
                "caveats": [], "connections": [], "conclusion": empty, "takeaways": [], "known_gaps": [gap],
                "language_ok": True}

    def _task_summary_generator(self, ctx: dict, req: GenerationRequest) -> dict:
        return self._summarize(ctx["passages"], ctx.get("depth", "balanced"), ctx.get("chapter_title", ""), ctx.get("max_quote_ratio", 0.25))

    def _task_summary_passage_notes(self, ctx: dict, req: GenerationRequest) -> dict:
        summary = self._summarize(ctx["passages"], "comprehensive", "", ctx.get("max_quote_ratio", 0.25))
        notes = [{"kind": "argument", "text": summary["central_thesis"]["text"], "evidence_ids": summary["central_thesis"]["evidence_ids"]}]
        for sec in summary["sections"]:
            notes.append({"kind": "reasoning", "text": sec["content"], "evidence_ids": sec["evidence_ids"]})
        notes += [{"kind": "example", "text": e["description"], "evidence_ids": e["evidence_ids"]} for e in summary["examples"]]
        notes += [{"kind": "caveat", "text": c["text"], "evidence_ids": c["evidence_ids"]} for c in summary["caveats"]]
        notes += [{"kind": "definition", "text": d["definition"], "evidence_ids": d["evidence_ids"]} for d in summary["definitions"]]
        return {"notes": [n for n in notes if n["text"]], "language_ok": True}

    def _task_book_summary_aggregator(self, ctx: dict, req: GenerationRequest) -> dict:
        depth = ctx.get("depth", "balanced")
        cfg = DEPTH.get(depth, DEPTH["balanced"])
        chapters: list[dict] = ctx["chapter_summaries"]
        sections, takeaways, definitions, caveats, gaps = [], [], [], [], []
        theses = []
        for ch in chapters:
            s = ch.get("summary")
            if not s:
                gaps.append(f"{ch['title']}: summary unavailable")
                continue
            th = s["central_thesis"]
            if th["text"]:
                theses.append(th)
            parts = [th["text"]]
            if s["conclusion"]["text"] and s["conclusion"]["text"] != th["text"] and depth != "concise":
                parts.append(s["conclusion"]["text"])
            concepts = [c for sec in s["sections"] for c in sec["key_concepts"]][:3]
            sections.append({
                "heading": ch["title"],
                "content": " ".join(p for p in parts if p),
                "key_concepts": concepts,
                "evidence_ids": sorted(set(th["evidence_ids"]) | (set(s["conclusion"]["evidence_ids"]) if len(parts) > 1 else set())),
            })
            if s["takeaways"]:
                takeaways.append(s["takeaways"][0])
            definitions.extend(s["definitions"][:1])
            caveats.extend(s["caveats"][:1])
        all_text = " ".join(t["text"] for t in theses)
        central = max(theses, key=lambda t: token_overlap(t["text"], all_text), default={"text": "", "evidence_ids": []})
        last = next((ch["summary"]["conclusion"] for ch in reversed(chapters) if ch.get("summary") and ch["summary"]["conclusion"]["text"]), {"text": "", "evidence_ids": []})
        return {
            "title": ctx.get("book_title", ""),
            "central_thesis": central,
            "sections": sections,
            "definitions": definitions[: cfg["definitions"]],
            "examples": [],
            "caveats": caveats[: cfg["caveats"]],
            "connections": [],
            "conclusion": last,
            "takeaways": takeaways[: max(cfg["takeaways"], len(chapters)) if depth == "comprehensive" else cfg["takeaways"]],
            "known_gaps": gaps,
            "language_ok": True,
        }

    # ------------------------------------------------------------------ Q&A
    def _task_book_qa(self, ctx: dict, req: GenerationRequest) -> dict:
        question = ctx["question"]
        q = _stems(question)
        sents = _sentences(ctx["passages"])
        if not q or not sents:
            return self._abstain("The question has no terms the book could answer.")
        scored = []
        q_bigrams = set(zip(sorted(q), sorted(q)[1:], strict=False))
        for s in sents:
            st = _stems(s.text)
            match = len(q & st) / len(q)
            if len(q) >= 3 and len(q & st) >= 2:
                match += 0.1 * len(q_bigrams & set(zip(sorted(st), sorted(st)[1:], strict=False)))
            scored.append((match, s))
        scored.sort(key=lambda x: (-x[0], x[1].pos))
        best = scored[0][0]
        threshold = 0.5 if len(q) >= 2 else 1.0
        if best < threshold:
            return self._abstain(
                "The uploaded book does not appear to address this question. Readbit's assistant only answers from "
                "your book, so it will not fill the gap with outside knowledge."
            )
        picked = [s for m, s in scored[:3] if m >= max(threshold, 0.6 * best)]
        picked.sort(key=lambda s: s.pos)
        return {
            "answerable": True,
            "answer": " ".join(s.text for s in picked),
            "evidence_ids": sorted({s.pid for s in picked}),
            "confidence": "high" if best >= 0.75 else "medium",
            "unanswerable_reason": "",
            "language_ok": True,
        }

    @staticmethod
    def _abstain(reason: str) -> dict:
        return {"answerable": False, "answer": "", "evidence_ids": [], "confidence": "low", "unanswerable_reason": reason, "language_ok": True}

    # ------------------------------------------------------------------ quiz generation
    def _task_quiz_question_generator(self, ctx: dict, req: GenerationRequest) -> dict:
        passages = ctx["passages"]
        count = int(ctx.get("count", 5))
        lang = ctx.get("source_language") or "en"
        chapter = ctx.get("chapter_title") or "this chapter"
        avoid = {normalize_for_match(a) for a in ctx.get("avoid", [])}
        seed = int(ctx.get("seed", 0))
        sents = _sentences(passages)
        _score(sents, *(self._df(passages)))
        chapter_terms = _key_terms([p["text"] for p in passages], 12)
        pool_terms = list(dict.fromkeys(chapter_terms + [t.lower() for t in ctx.get("book_terms", [])]))
        full_text = " ".join(p["text"] for p in passages)

        candidates: list[dict] = []
        for s in sorted(sents, key=lambda s: -s.score):
            n_words = len(s.text.split())
            if n_words < 8 or n_words > 48:
                continue
            candidates.extend(self._cloze(s, pool_terms, chapter_terms, chapter, lang))
            candidates.extend(self._numeric(s, chapter, lang, chapter_terms))
            candidates.extend(self._statement(s, pool_terms, chapter, lang, full_text))
        # Deterministic, seed-dependent ordering that still favours central sentences.
        ranked = sorted(enumerate(candidates), key=lambda ic: (ic[0] // 6, _seed(seed, ic[1]["question"])))
        out: list[dict] = []
        used_sentences: set[str] = set()
        for _, c in ranked:
            key = normalize_for_match(c["question"])
            if key in avoid or c["_sentence"] in used_sentences:
                continue
            used_sentences.add(c["_sentence"])
            out.append(self._finalize(c, seed))
            if len(out) >= count:
                break
        return {"questions": out, "language_ok": True}

    def _finalize(self, c: dict, seed: int) -> dict:
        options_text = [c["_correct"]] + c["_distractors"][:3]
        pos = _seed(seed, c["question"]) % 4
        options_text[0], options_text[pos] = options_text[pos], options_text[0]
        keys = ["A", "B", "C", "D"]
        return {
            "question": c["question"],
            "question_type": c["question_type"],
            "difficulty": c["difficulty"],
            "topic": c["topic"],
            "options": [{"key": k, "text": t} for k, t in zip(keys, options_text, strict=True)],
            "correct_key": keys[pos],
            "evidence_ids": [c["_pid"]],
            "explanation": c["explanation"],
            "misconception": c["misconception"],
        }

    @staticmethod
    def _pick_distractors(correct: str, pool: list[str], sentence: str, seed: str) -> list[str]:
        sent_norm = normalize_for_match(sentence)
        c_words = len(correct.split())
        options = []
        for t in pool:
            tn = normalize_for_match(t)
            if not tn or tn == normalize_for_match(correct) or tn in normalize_for_match(correct) or normalize_for_match(correct) in tn:
                continue
            if re.search(rf"\b{re.escape(tn)}\b", sent_norm):
                continue
            options.append(t)
        # Prefer distractors of similar shape (word count) so option length does not reveal the answer.
        options.sort(key=lambda t: (abs(len(t.split()) - c_words), _seed(seed, t)))
        return options[:3]

    def _cloze(self, s: Sent, pool: list[str], chapter_terms: list[str], chapter: str, lang: str) -> list[dict]:
        out = []
        for term in chapter_terms:
            m = re.search(rf"\b{re.escape(term)}\b", s.text, re.I)
            if not m or len(re.findall(rf"\b{re.escape(term)}\b", s.text, re.I)) != 1:
                continue
            distractors = self._pick_distractors(term, pool, s.text, s.text)
            if len(distractors) < 3:
                continue
            clozed = s.text[: m.start()] + BLANK + s.text[m.end() :]
            stem = (
                f"पुस्तक के अनुसार रिक्त स्थान भरें ({chapter}): “{clozed}”" if lang == "hi"
                else f"Complete the statement from {chapter}: “{clozed}”"
            )
            defined = bool(DEFINITION_CUES.search(s.text))
            out.append({
                "question": stem,
                "question_type": "recall",
                "difficulty": 1 if defined else 2,
                "topic": term,
                "_correct": term,
                "_distractors": distractors,
                "_pid": s.pid,
                "_sentence": s.text,
                "explanation": (f"पुस्तक में लिखा है: “{s.text}”" if lang == "hi" else f"The book states: “{s.text}”"),
                "misconception": "" if lang == "hi" else (
                    f"“{distractors[0]}” is a term from the book, but it is not the one used in this statement."
                ),
            })
            break
        return out

    def _numeric(self, s: Sent, chapter: str, lang: str, terms: list[str] | None = None) -> list[dict]:
        if lang != "en":
            return []
        m = NUMBER_PHRASE.search(s.text)
        if not m:
            return []
        phrase = m.group(1)
        distractors = self._number_variants(phrase)
        distractors = [d for d in distractors if not fuzzy_contains(s.text, d, 1.0)]
        if len(distractors) < 3:
            return []
        clozed = s.text[: m.start(1)] + BLANK + s.text[m.end(1) :]
        return [{
            "question": f"According to {chapter}, which option completes the statement: “{clozed}”",
            "question_type": "recall",
            "difficulty": 2,
            "topic": next((t for t in (terms or []) if re.search(rf"\b{re.escape(t)}\b", s.text, re.I)), "key figures"),
            "_correct": phrase,
            "_distractors": distractors[:3],
            "_pid": s.pid,
            "_sentence": s.text,
            "explanation": f"The book states: “{s.text}”",
            "misconception": "The other options change the quantity the book gives.",
        }]

    @staticmethod
    def _number_variants(phrase: str) -> list[str]:
        nums = re.findall(r"\d+(?:[.,]\d+)?|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)), phrase, re.I)
        if not nums:
            return []
        variants: list[str] = []
        first = nums[0]
        if first.replace(".", "").replace(",", "").isdigit():
            base = float(first.replace(",", ""))
            factors = [0.5, 2, 3, 1.5] if base >= 2 else [2, 3, 4, 5]
            for f in factors:
                val = base * f
                txt = str(int(val)) if val.is_integer() else f"{val:g}"
                if len(nums) > 1 and nums[1].isdigit():
                    second = float(nums[1]) * f
                    txt2 = str(int(second)) if second.is_integer() else f"{second:g}"
                    cand = phrase.replace(nums[1], txt2, 1).replace(first, txt, 1)
                else:
                    cand = phrase.replace(first, txt, 1)
                if cand != phrase and cand not in variants:
                    variants.append(cand)
        else:
            idx = NUMBER_WORDS.index(first.lower()) if first.lower() in NUMBER_WORDS else 0
            for off in (1, 2, -1, 3, -2):
                j = idx + off
                if 0 <= j < len(NUMBER_WORDS):
                    cand = re.sub(rf"\b{re.escape(first)}\b", NUMBER_WORDS[j], phrase, count=1, flags=re.I)
                    if len(nums) > 1 and nums[1].lower() in NUMBER_WORDS:
                        k = min(len(NUMBER_WORDS) - 1, max(0, NUMBER_WORDS.index(nums[1].lower()) + off))
                        cand = re.sub(rf"\b{re.escape(nums[1])}\b", NUMBER_WORDS[k], cand, count=1, flags=re.I)
                    if cand.lower() != phrase.lower() and cand not in variants:
                        variants.append(cand)
        return variants

    def _statement(self, s: Sent, pool: list[str], chapter: str, lang: str, full_text: str) -> list[dict]:
        present = [t for t in pool if re.search(rf"\b{re.escape(t)}\b", s.text, re.I)]
        # Never swap a term that is part of a longer term in the same sentence ("attention" in "directed attention").
        present = [t for t in present if not any(t != o and t in o for o in present)]
        if not present:
            return []
        target = max(present, key=len)
        replacements = self._pick_distractors(target, pool, s.text, "stmt" + s.text)
        false_statements = []
        for r in replacements:
            variant = re.sub(rf"\b{re.escape(target)}\b", r, s.text, count=1, flags=re.I)
            if variant != s.text and not fuzzy_contains(full_text, variant, 0.97):
                false_statements.append(variant)
        if len(false_statements) < 3:
            return []
        stem = (
            f"{chapter} के अनुसार कौन-सा कथन सही है?" if lang == "hi"
            else f"Which statement is supported by {chapter}?"
        )
        return [{
            "question": stem + ("" if lang == "hi" else f" (Topic: {target})"),
            "question_type": "comprehension",
            "difficulty": 3,
            "topic": target,
            "_correct": s.text,
            "_distractors": false_statements,
            "_pid": s.pid,
            "_sentence": s.text,
            "explanation": (f"पुस्तक में लिखा है: “{s.text}”" if lang == "hi" else f"This is what the book states: “{s.text}”"),
            "misconception": "" if lang == "hi" else (
                f"The other statements swap “{target}” for a different term, which changes the meaning."
            ),
        }]

    # ------------------------------------------------------------------ validation (blind)
    def _task_quiz_question_validator(self, ctx: dict, req: GenerationRequest) -> dict:
        q = ctx["question"]
        text = " ".join(p["text"] for p in ctx["passages"])
        norm_text = normalize_for_match(text)
        stem = q["question"]
        options = q["options"]
        m = re.search(r"“(.*)”", stem)
        supported = []
        for opt in options:
            # Extractive items are verbatim, so an option is "supported" only if the completed sentence appears
            # in the passages exactly (after normalisation). Near-misses count as unsupported.
            if m and BLANK in m.group(1):
                candidate = m.group(1).replace(BLANK, opt["text"])
            else:
                candidate = opt["text"]
            ok = normalize_for_match(candidate) in norm_text
            if ok:
                supported.append(opt["key"])
        exactly_one = len(supported) == 1
        expl_quote = re.search(r"“(.*)”", q.get("explanation", ""))
        explanation_ok = bool(expl_quote and fuzzy_contains(text, expl_quote.group(1), 0.95)) or token_overlap(q.get("explanation", ""), text) >= 0.6
        detected = detect_language(stem + " " + " ".join(o["text"] for o in options))
        language_ok = detected is None or detected == req.output_language
        return {
            "answer_key": supported[0] if exactly_one else "none",
            "checks": {
                "answer_supported": exactly_one,
                "distractors_incorrect": exactly_one,
                "unambiguous": exactly_one,
                "no_external_knowledge": exactly_one,
                "explanation_supports_answer": explanation_ok,
                "language_ok": language_ok,
            },
            "reason": "" if exactly_one else f"{len(supported)} options are supported by the passages",
        }

    def _task_answer_explainer(self, ctx: dict, req: GenerationRequest) -> dict:
        q = ctx["question"]
        passages = ctx["passages"]
        correct = next(o["text"] for o in q["options"] if o["key"] == q["correct_key"])
        best = max(_sentences(passages), key=lambda s: token_overlap(correct + " " + q["question"], s.text), default=None)
        if best is None:
            return {"explanation": "", "misconception": "", "evidence_ids": []}
        return {"explanation": f"The book states: “{best.text}”", "misconception": "", "evidence_ids": [best.pid]}

    # ------------------------------------------------------------------ misc tasks
    def _task_chapter_detector(self, ctx: dict, req: GenerationRequest) -> dict:
        return {"chapter_start_indices": [], "confidence": "low"}

    def _task_document_extraction_repair(self, ctx: dict, req: GenerationRequest) -> dict:
        return {"repaired": [{"id": p["id"], "text": p["text"]} for p in ctx["passages"]]}

    def _task_source_faithfulness_evaluator(self, ctx: dict, req: GenerationRequest) -> dict:
        by_id = {p["id"]: p["text"] for p in ctx["passages"]}
        judgements = []
        for i, claim in enumerate(ctx["claims"]):
            cited = " ".join(by_id.get(e, "") for e in claim["evidence_ids"])
            if not cited:
                verdict = "unsupported"
            elif fuzzy_contains(cited, claim["text"], 0.9) or token_overlap(claim["text"], cited) >= 0.7:
                verdict = "supported"
            elif token_overlap(claim["text"], cited) >= 0.4:
                verdict = "partial"
            else:
                verdict = "unsupported"
            judgements.append({"claim_index": i, "verdict": verdict, "misattributed": False, "reason": "lexical judge"})
        return {"judgements": judgements}
