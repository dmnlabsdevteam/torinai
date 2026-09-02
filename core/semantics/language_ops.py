"""The substrate's language-operations faculty.

One place that owns the small, recurring text operations the substrate needs
over prose it did not itself produce — summarising a passage, judging the
sentiment of a message, pulling named entities out of text, and classifying a
passage against caller-supplied cues. These used to be scattered LLM calls (one
per caller, each with its own prompt and its own ad-hoc fallback); they are
gathered here so there is ONE implementation of each, deterministic and
inspectable, that every caller reaches.

Each operation is a real algorithm, not a stub: extractive ranking for
summaries, a polarity lexicon with negation handling for sentiment, pattern and
gazetteer matching for entities, weighted cue scoring for classification. They
are honestly bounded — pattern recall is finite, a summary is selected not
paraphrased — and they say so in their outputs (confidence, what matched) rather
than inventing coverage they do not have.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── shared primitives ────────────────────────────────────────────────────────

_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"\'(])')
_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_CAP_TOKEN = re.compile(r"[A-Z][A-Za-z.&'\-]*")

#: Structure-carrying words that add no content to a frequency profile. Kept
#: small and visible; every entry is a word a person decided carries no topic.
STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "then", "of", "to", "in", "on",
    "at", "by", "for", "with", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "it", "its", "this", "that", "these", "those", "there",
    "here", "he", "she", "they", "them", "his", "her", "their", "we", "us",
    "our", "you", "your", "i", "me", "my", "do", "does", "did", "has", "have",
    "had", "will", "would", "can", "could", "should", "may", "might", "must",
    "not", "no", "so", "than", "too", "very", "just", "about", "into", "over",
    "up", "down", "out", "off", "any", "all", "each", "which", "who", "whom",
    "what", "when", "where", "why", "how", "s", "t", "re", "ve", "ll", "d", "m",
})


def _sentences(text: str) -> List[str]:
    """Split prose into sentences. A blunt rule on terminal punctuation — wrong
    in ways you can see (abbreviations), not buried in a model."""
    text = (text or "").strip()
    if not text:
        return []
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def _content_words(text: str) -> List[str]:
    """Lowercased content words — topic-bearing tokens, stopwords removed."""
    return [w for w in (m.group(0).lower() for m in _WORD.finditer(text))
            if w not in STOPWORDS and len(w) > 1]


# ── sentiment ────────────────────────────────────────────────────────────────
# A compact, curated polarity lexicon. Not exhaustive — it is meant to carry the
# common affective vocabulary honestly, and its bounded recall is reported as
# confidence rather than hidden.

_POSITIVE = frozenset({
    "good", "great", "excellent", "amazing", "wonderful", "fantastic", "love",
    "loved", "like", "liked", "happy", "glad", "pleased", "delighted", "best",
    "better", "positive", "success", "successful", "win", "won", "gain", "gained",
    "improve", "improved", "improvement", "benefit", "beneficial", "helpful",
    "useful", "effective", "efficient", "reliable", "safe", "secure", "clear",
    "correct", "right", "perfect", "strong", "robust", "fast", "smooth", "clean",
    "recommend", "recommended", "enjoy", "enjoyed", "thanks", "thank", "appreciate",
    "impressive", "brilliant", "outstanding", "superb", "favorable", "hopeful",
    "confident", "satisfied", "satisfying", "resolved", "works", "worked", "fixed",
})

_NEGATIVE = frozenset({
    "bad", "terrible", "awful", "horrible", "hate", "hated", "dislike", "poor",
    "worst", "worse", "negative", "fail", "failed", "failure", "loss", "lost",
    "broken", "break", "bug", "buggy", "error", "errors", "crash", "crashed",
    "slow", "sluggish", "unreliable", "unsafe", "insecure", "wrong", "incorrect",
    "confusing", "confused", "difficult", "hard", "painful", "frustrating",
    "frustrated", "angry", "annoyed", "annoying", "disappointed", "disappointing",
    "useless", "pointless", "weak", "fragile", "dangerous", "critical", "severe",
    "problem", "problems", "issue", "issues", "concern", "concerned", "risk",
    "risky", "vulnerable", "malicious", "attack", "threat", "denied", "reject",
    "rejected", "unhappy", "sad", "regret", "complaint", "complain", "warning",
})

_NEGATORS = frozenset({"not", "no", "never", "none", "without", "hardly",
                       "barely", "cannot", "cant", "dont", "doesnt", "didnt",
                       "isnt", "wasnt", "arent", "wont", "n't", "neither", "nor"})


def sentiment(text: str) -> Dict[str, Any]:
    """The affective lean of a passage: positive, negative, or neutral.

    Counts polarity-lexicon hits, flipping a hit's sign when a negator precedes
    it within a short window ("not good" -> negative). Score is the normalised
    balance in [-1, 1]; the label falls to neutral inside a dead-band, and
    confidence is the count-backed strength — a passage with no lexicon hits is
    an honest neutral at confidence 0, not a guess.
    """
    tokens = [m.group(0).lower() for m in _WORD.finditer(text or "")]
    pos = neg = 0
    neg_window = 0
    for tok in tokens:
        if tok in _NEGATORS or tok.endswith("n_t") or tok.endswith("n't"):
            neg_window = 3
            continue
        flip = neg_window > 0
        if tok in _POSITIVE:
            neg += 1 if flip else 0
            pos += 0 if flip else 1
        elif tok in _NEGATIVE:
            pos += 1 if flip else 0
            neg += 0 if flip else 1
        neg_window = max(0, neg_window - 1)

    total = pos + neg
    if total == 0:
        return {"label": "neutral", "score": 0.0, "confidence": 0.0,
                "positive_hits": 0, "negative_hits": 0}
    score = (pos - neg) / total
    label = "positive" if score > 0.15 else "negative" if score < -0.15 else "neutral"
    return {"label": label, "score": round(score, 3),
            "confidence": round(min(1.0, total / 5.0) * abs(score) if label != "neutral"
                                else min(1.0, total / 5.0), 3),
            "positive_hits": pos, "negative_hits": neg}


# ── summarise (extractive) ───────────────────────────────────────────────────

def summarize(text: str, max_sentences: int = 3) -> str:
    """A summary by SELECTION: the sentences that best carry the passage's own
    most frequent content words, returned in their original order.

    Extractive, not abstractive — it never writes a sentence the text did not
    contain, so it cannot hallucinate. Short inputs are returned whole; there is
    nothing to distil.
    """
    sents = _sentences(text)
    if len(sents) <= max_sentences:
        return (text or "").strip()

    freq = Counter(_content_words(text))
    if not freq:
        return " ".join(sents[:max_sentences])
    peak = max(freq.values())

    scored: List[Tuple[float, int, str]] = []
    for idx, sent in enumerate(sents):
        words = _content_words(sent)
        if not words:
            scored.append((0.0, idx, sent))
            continue
        # Mean normalised frequency of the sentence's content words: rewards
        # topic density without simply preferring the longest sentence.
        s = sum(freq[w] / peak for w in words) / len(words)
        # A mild lead bias: earlier sentences tend to frame the passage.
        s *= 1.0 + max(0.0, 0.15 - idx * 0.01)
        scored.append((s, idx, sent))

    top = sorted(scored, key=lambda t: t[0], reverse=True)[:max_sentences]
    chosen = sorted(top, key=lambda t: t[1])  # restore original order
    return " ".join(s for _, _, s in chosen)


def summarize_length(text: str, max_words: int = 100) -> str:
    """Summarise to roughly a word budget. Picks whole sentences (by the same
    ranking) until the budget is met — a word cap over selected sentences, never
    a mid-sentence truncation."""
    sents = _sentences(text)
    if not sents:
        return ""
    words_total = len(re.findall(r"\S+", text))
    if words_total <= max_words:
        return text.strip()
    # Rank all sentences, then admit in original order until the budget fills.
    ranked = summarize(text, max_sentences=len(sents))  # full ranking preserved order
    out, used = [], 0
    for sent in _sentences(ranked):
        n = len(re.findall(r"\S+", sent))
        if used + n > max_words and out:
            break
        out.append(sent)
        used += n
    return " ".join(out)


# ── entity extraction ────────────────────────────────────────────────────────

_DATE = re.compile(
    r"\b("
    r"\d{4}-\d{2}-\d{2}"                                              # 2026-08-30
    r"|\d{1,2}/\d{1,2}/\d{2,4}"                                       # 8/30/2026
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{4})?"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm|AM|PM)?"                 # 14:05 / 2:05 pm
    r"|\b(?:today|tomorrow|yesterday)\b"
    r")\b"
)

_ORG_SUFFIX = frozenset({
    "inc", "inc.", "corp", "corp.", "llc", "ltd", "ltd.", "co", "co.", "company",
    "foundation", "university", "institute", "college", "group", "labs",
    "laboratories", "technologies", "systems", "software", "solutions",
    "association", "committee", "agency", "department", "bureau", "council",
    "partners", "holdings", "ventures", "capital", "bank", "gmbh", "plc",
})

_LOCATION_CUES = frozenset({"in", "at", "from", "to", "near", "across", "within"})

_GAZETTEER = frozenset({
    "america", "usa", "us", "u.s.", "uk", "england", "britain", "canada",
    "mexico", "france", "germany", "spain", "italy", "china", "japan", "india",
    "russia", "brazil", "australia", "africa", "europe", "asia", "london",
    "paris", "berlin", "tokyo", "beijing", "moscow", "york", "california",
    "texas", "florida", "washington", "boston", "chicago", "seattle", "miami",
})

_TITLES = frozenset({"mr", "mrs", "ms", "dr", "prof", "sir", "madam", "mr.",
                     "mrs.", "ms.", "dr.", "prof."})


def _capitalized_spans(text: str) -> List[Tuple[int, str]]:
    """Runs of Capitalized tokens, with the index of the sentence each starts in
    (0 = sentence-initial, where capitalization is uninformative)."""
    spans: List[Tuple[int, str]] = []
    for sent in _sentences(text) or [text or ""]:
        toks = sent.split()
        i = 0
        while i < len(toks):
            m = _CAP_TOKEN.fullmatch(toks[i].strip(",;:()\"'"))
            if m:
                start = i
                run = [toks[i].strip(",;:()\"'")]
                j = i + 1
                while j < len(toks):
                    m2 = _CAP_TOKEN.fullmatch(toks[j].strip(",;:()\"'"))
                    if not m2:
                        break
                    run.append(toks[j].strip(",;:()\"'"))
                    j += 1
                spans.append((start, " ".join(run)))
                i = j
            else:
                i += 1
    return spans


def extract_entities(text: str) -> Dict[str, List[str]]:
    """Named entities by pattern and gazetteer — person / organization /
    location / date / other.

    Rule-based: capitalization runs, organisational suffixes, a place gazetteer
    with locational prepositions, and date/time regexes. Bounded recall (it will
    miss what its patterns do not cover) and never fabricated — an empty category
    means "no pattern matched", which the caller must not read as "none exist".
    """
    out: Dict[str, List[str]] = {"person": [], "organization": [],
                                 "location": [], "date": [], "other": []}
    text = text or ""

    for m in _DATE.finditer(text):
        out["date"].append(m.group(0).strip())

    # Locational preposition immediately before a capitalized span -> location.
    words = text.split()
    loc_prefixed = set()
    for i, w in enumerate(words[:-1]):
        if w.lower() in _LOCATION_CUES:
            nxt = words[i + 1].strip(",;:()\"'")
            if _CAP_TOKEN.fullmatch(nxt):
                loc_prefixed.add(nxt)

    for start, span in _capitalized_spans(text):
        low = span.lower()
        toks = span.split()
        last = toks[-1].lower().strip(".")
        first = toks[0].lower()
        if any(t.lower().strip(".") in _ORG_SUFFIX for t in toks):
            _add(out["organization"], span)
        elif low in _GAZETTEER or any(t.lower() in _GAZETTEER for t in toks) \
                or span in loc_prefixed or toks[0] in loc_prefixed:
            _add(out["location"], span)
        elif first in _TITLES and len(toks) >= 2:
            _add(out["person"], span)         # "Dr. Smith"
        elif first in _TITLES:
            continue                          # dangling title from an abbreviation split
        elif len(toks) >= 2:
            # A multi-word capitalized run is an entity regardless of position;
            # sentence-initial names ("Stefan Ragland …") count.
            _add(out["person"], span)
        elif start > 0:                       # a single mid-sentence Capitalized word
            _add(out["other"], span)
    return out


def _add(bucket: List[str], value: str) -> None:
    if value and value not in bucket:
        bucket.append(value)


# ── classification by cues ───────────────────────────────────────────────────

def classify(text: str, label_cues: Dict[str, Sequence[str]], *,
             default: Optional[str] = None,
             weights: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Assign a passage to one of several labels by CALLER-SUPPLIED cues.

    Each label carries a set of cue strings (words or phrases); the label whose
    cues the text hits most wins. Domain callers (a security screen, a
    sensitivity grader) own their vocabulary and pass it in — this is the one
    scoring engine they share, not a place their domain knowledge lives. With no
    cue hit at all the result is `default` at confidence 0: an honest abstention,
    never a coin-flip.
    """
    low = (text or "").lower()
    weights = weights or {}
    scores: Dict[str, float] = {}
    matched: Dict[str, List[str]] = {}
    for label, cues in label_cues.items():
        hit = [c for c in cues if c.lower() in low]
        scores[label] = sum(weights.get(c, 1.0) for c in hit)
        if hit:
            matched[label] = hit

    total = sum(scores.values())
    if total <= 0:
        return {"label": default, "confidence": 0.0, "scores": scores, "matched": {}}
    top = max(scores, key=scores.get)
    return {"label": top, "confidence": round(scores[top] / total, 3),
            "scores": scores, "matched": matched}


# ── singleton ────────────────────────────────────────────────────────────────

class LanguageOps:
    """The faculty as an object, for callers that prefer a handle. All methods
    are the module functions above; the class exists only to give the operations
    one named owner to reach them through."""

    summarize = staticmethod(summarize)
    summarize_length = staticmethod(summarize_length)
    sentiment = staticmethod(sentiment)
    extract_entities = staticmethod(extract_entities)
    classify = staticmethod(classify)


_language_ops: Optional[LanguageOps] = None


def get_language_ops() -> LanguageOps:
    """The one language-operations faculty."""
    global _language_ops
    if _language_ops is None:
        _language_ops = LanguageOps()
    return _language_ops


__all__ = ["LanguageOps", "get_language_ops", "summarize", "summarize_length",
           "sentiment", "extract_entities", "classify", "STOPWORDS"]
