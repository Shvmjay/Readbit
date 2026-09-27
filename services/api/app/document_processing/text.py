"""Language-agnostic text helpers: normalization, sentence splitting, tokenization, language detection."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "­": ""}
_WS = re.compile(r"[ \t  -​]+")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_WORD = re.compile(r"[\wऀ-ॿ]+(?:['’][\w]+)?", re.UNICODE)
_SENT_SPLIT = re.compile(r"(?<=[.!?।])[\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9ऀ-ॿ])")
_ABBREV = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|St|vs|etc|e\.g|i\.e|No|Fig|Vol|pp|cf)\.$", re.IGNORECASE)

EN_STOPWORDS = frozenset(
    """a about above after again against all also am an and any are as at be because been before being below
    between both but by can could did do does doing down during each few for from further had has have having he
    her here hers herself him himself his how i if in into is it its itself just let me more most much must my
    myself no nor not now of off on once only or other ought our ours ourselves out over own same shall she should
    so some such than that the their theirs them themselves then there these they this those through to too under
    until up upon very was we were what when where which while who whom why will with within without would you your
    yours yourself yourselves one two may might many often every however thus therefore rather even though yet
    still something someone anything things thing way ways make makes made us like well new first last also back
    get gets got per via among across around whether either neither""".split()
)
HI_STOPWORDS = frozenset("के का की है में और को से एक यह पर था हैं कि जो भी तो ही या इस ने लिए किया करते होता".split())
STOPWORDS = EN_STOPWORDS | HI_STOPWORDS


def normalize_text(text: str) -> str:
    """Normalize extracted text without destroying meaningful structure (paragraph breaks survive)."""
    text = unicodedata.normalize("NFC", text)
    for src, dst in LIGATURES.items():
        text = text.replace(src, dst)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _WS.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    text = collapse_whitespace(text)
    if not text:
        return []
    raw = _SENT_SPLIT.split(text)
    out: list[str] = []
    for piece in raw:
        piece = piece.strip()
        if not piece:
            continue
        if out and _ABBREV.search(out[-1]):
            out[-1] = out[-1] + " " + piece
        else:
            out.append(piece)
    return out


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(text)]


def content_words(text: str) -> list[str]:
    return [
        t
        for t in tokenize(text)
        if t not in STOPWORDS and (len(t) > 2 or not t.isascii()) and not t.isdigit()
    ]


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def estimate_tokens(text: str) -> int:
    # Conservative approximation used for budgeting only (≈4 chars/token for Latin script).
    return max(1, int(len(text) / 3.6))


def detect_language(text: str) -> str | None:
    """Script + stopword heuristic. Returns an ISO 639-1 code, or None when not confident."""
    sample = text[:20000]
    letters = [c for c in sample if c.isalpha()]
    if len(letters) < 50:
        return None
    devanagari = sum(1 for c in letters if "ऀ" <= c <= "ॿ")
    if devanagari / len(letters) > 0.4:
        return "hi"
    latin = sum(1 for c in letters if c.isascii())
    if latin / len(letters) > 0.8:
        toks = tokenize(sample)
        if not toks:
            return None
        en_ratio = sum(1 for t in toks if t in EN_STOPWORDS) / len(toks)
        return "en" if en_ratio > 0.2 else None
    return None


def normalize_for_match(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[“”\"'‘’`]", "", text)
    text = re.sub(r"[^\wऀ-ॿ]+", " ", text)
    return text.strip()


def fuzzy_contains(haystack: str, needle: str, min_ratio: float = 0.85) -> bool:
    """True if `needle` appears in `haystack` exactly (normalized) or with high token-window overlap."""
    h, n = normalize_for_match(haystack), normalize_for_match(needle)
    if not n:
        return False
    if n in h:
        return True
    n_toks = n.split()
    h_toks = h.split()
    if len(n_toks) < 4 or len(h_toks) < len(n_toks):
        return False
    need = Counter(n_toks)
    window = len(n_toks)
    cur = Counter(h_toks[:window])
    best = sum((cur & need).values())
    for i in range(window, len(h_toks)):
        cur[h_toks[i]] += 1
        cur[h_toks[i - window]] -= 1
        if cur[h_toks[i - window]] <= 0:
            del cur[h_toks[i - window]]
        best = max(best, sum((cur & need).values()))
    return best / window >= min_ratio


def token_overlap(a: str, b: str) -> float:
    """Share of content words in `a` that also appear in `b`."""
    ta = set(content_words(a))
    if not ta:
        return 0.0
    tb = set(content_words(b))
    return len(ta & tb) / len(ta)
