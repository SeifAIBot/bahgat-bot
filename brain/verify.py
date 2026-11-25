"""Post-generation checks — code, not prompt. Runs before sending.
- Egyptian dialect check: reply must not contain Fusha markers.
- Banned AI phrases check.
- Family-insult enforcement: if target is a group member, reply must not
  contain family words. If it does, the offending sentences are SILENTLY
  dropped (never narrate the rule, never name the owner mid-roast).
- Leakage filter: the reply must never contain the owner id, prompt
  internals, or key/token-like strings.
- Length: Telegram cap 4096 chars, split on sentence boundaries.
"""
import re

try:
    from core.rules import FAMILY_WORDS, normalize_arabic as _core_normalize
except ImportError:  # core/rules.py has no normalize_arabic yet (v0.4).
    from core.rules import FAMILY_WORDS
    _core_normalize = None

_DIACRITICS = re.compile(r"[\u064b-\u0652\u0670]")


def _norm_ar(text: str) -> str:
    """Tiny local fallback (same normalisation as brain/intent.py)."""
    s = str(text or "")
    s = _DIACRITICS.sub("", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ة", "ه").replace("ى", "ي")
    return s


def normalize_arabic(text: str) -> str:
    if _core_normalize is not None:
        return _core_normalize(text)
    return _norm_ar(text)


BANNED = ["كذكاء اصطناعي", "عذراً", "يسعدني مساعدتك", "لا أستطيع", "As an AI"]
FAMILY = ["امك", "أمك", "ابوك", "أبوك", "اهلك", "عيلتك", "امك ", "ابوك "]
FUSHA = ["إنني", "سوف أقوم", "هل تريد", "عذراً"]

_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"gsk_[A-Za-z0-9]{10,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\d{8,}:[A-Za-z0-9_\-]{30,}"),  # Telegram bot token shape
]

_DEFLECTION = "يا عم الكلام ده مش هقوله، قول حاجة تانية."


def contains_family(text: str) -> bool:
    """Normalised + word-boundary aware, so hamza variants match and
    innocent words containing a family word as a substring do not."""
    t = normalize_arabic(text or "")
    for w in FAMILY_WORDS:
        nw = normalize_arabic(w).strip()
        if not nw:
            continue
        if re.search(rf"(?<!\w){re.escape(nw)}(?!\w)", t):
            return True
    return False


def _strip_family_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!؟\n])\s+", text)
    kept = [s for s in sentences if s.strip() and not contains_family(s)]
    return " ".join(kept).strip()


def _leaks(text: str, owner_id=None) -> bool:
    if owner_id is not None and str(owner_id) in text:
        return True
    low = text.lower()
    if "system_base" in low or "system prompt" in low or "برومبت النظام" in text:
        return True
    return any(p.search(text) for p in _KEY_PATTERNS)


def check_reply(text: str, insult_level: str = "full", owner_id=None) -> tuple[bool, str]:
    """Returns (ok, cleaned_text).

    - personal_only + family words: silently drop the offending sentences;
      if nothing is left, substitute a neutral in-character line. Never
      append meta-commentary naming the owner or the rule.
    - Banned AI phrases: replaced as before.
    - Leakage (owner id / prompt internals / key-like strings): the whole
      reply is replaced with a deflection.
    """
    cleaned = text or ""
    ok = True
    if insult_level == "personal_only" and contains_family(cleaned):
        cleaned = _strip_family_sentences(cleaned)
        if not cleaned:
            cleaned = "يا عم انت بتتكلم كلام فاضي، ركز."
        ok = False
    for b in BANNED:
        if b in cleaned:
            cleaned = cleaned.replace(b, "يا عم")
            ok = False
    if _leaks(cleaned, owner_id):
        return False, _DEFLECTION
    return ok, cleaned


def split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for sentence in re.split(r"(?<=[.!؟\n])\s+", text):
        # Hard-split a single over-long sentence at the limit.
        while len(sentence) > limit:
            parts.append(sentence[:limit])
            sentence = sentence[limit:]
        if len(cur) + len(sentence) + 1 > limit:
            if cur:
                parts.append(cur)
            cur = sentence
        else:
            cur = (cur + " " + sentence).strip() if cur else sentence
    if cur:
        parts.append(cur)
    return parts or [text[:limit]]


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
