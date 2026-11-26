"""Intent from normal talk — no slash commands.
Word-boundary aware, priority: voice > youtube > search > just_chat.
Keyword intent is a first pass; the LLM can override it via tool choice in v2.

All matching runs on NORMALISED Arabic (see normalize_arabic): hamza
variants (أ/إ/آ -> ا), ة -> ه, ى -> ي, diacritics stripped. Without this,
ordinary Egyptian phrasing ("شغل اغنية", "هاتلي", "النتيجة") silently missed.
"""
import re

try:  # core.rules owns the canonical normaliser once another workstream adds it.
    from core.rules import normalize_arabic as _core_normalize_arabic
except ImportError:  # core/rules.py has no normalize_arabic yet (v0.4).
    _core_normalize_arabic = None

_DIACRITICS = re.compile(r"[\u064b-\u0652\u0670]")


def _norm_ar(text: str) -> str:
    """Tiny local fallback: hamza-insensitive Arabic normalisation."""
    s = str(text or "")
    s = _DIACRITICS.sub("", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ة", "ه").replace("ى", "ي")
    return s


def normalize_arabic(text: str) -> str:
    """Normalise Arabic for matching; prefers core.rules when available."""
    if _core_normalize_arabic is not None:
        return _core_normalize_arabic(text)
    return _norm_ar(text)


def _has(text: str, words) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text) for w in words)


# All patterns below are written in NORMALISED form (e.g. "علي" not "على",
# "النتيجه" not "النتيجة") because matching runs on normalised text.
_VOICE_WORDS = ["بصوتك", "قولها بصوت", "فويس", "ابعت فويس", "قولي بصوتك"]
_YOUTUBE_WORDS = [
    "هات فيديو", "هاتي فيديو", "هات اغنيه", "هاتي اغنيه",
    "هاتلي", "هاتيلي", "جبلي", "شغلي", "شغل", "نزل", "نزلي",
    "عايز اغنيه", "عاوز اغنيه", "عايز فيديو", "عاوز فيديو",
]
_SEARCH_WORDS = [
    "دور علي", "دور على", "دورلي", "ابحث", "ايه هو", "مين هو", "اخبار", "خبر",
    "سعر", "النتيجه", "مين بهجت", "مين كسب", "كسب مين", "كام", "امتى", "فين",
    "بكام", "ايه اللي حصل", "ايه الحصل", "ايه حصل", "سيرش", "علي النت",
    "على النت", "حادثه", "عايز اعرف", "عاوز اعرف",
]
# v0.9: "سيرش على النت على حادثة الوراق" missed every keyword above
# (no "سيرش", no "على النت", no "حادثه") and fell through to just_chat,
# so no search ran before the first LLM call and the bot answered with
# a "هدورلك" promise instead of a result. Note the normaliser does NOT
# map على -> علي, so both spellings of "على النت" are listed.


def detect_intent(text: str) -> str:
    t = normalize_arabic(text or "")
    low = t.lower()
    if _has(t, _VOICE_WORDS):
        return "voice"
    if "youtu.be" in low or "youtube.com" in low:
        return "youtube"
    if _has(t, _YOUTUBE_WORDS):
        return "youtube"
    if _has(t, _SEARCH_WORDS):
        return "search"
    return "just_chat"


_INSULT_RE = re.compile(
    r"(انت|انته)\s+(حمار|غبي|كلب|عبيط|حيوان|وسخ)"
    r"|يا\s*(حمار|غبي|كلب|عبيط|حيوان)"
    r"|اخرس|اسكت يا"
)


def looks_like_insult(text: str) -> bool:
    # Word-boundary aware: "يا ابن عمي" (friendly) must NOT trigger.
    t = normalize_arabic(text or "")
    if "يا ابن عمي" in t:
        return False
    return bool(_INSULT_RE.search(t))


_PRAISE_WORDS = ["شكرا", "انت جامد", "بحبك", "عاش", "برافو", "تسلم"]


def looks_like_praise(text: str) -> bool:
    return _has(normalize_arabic(text or ""), _PRAISE_WORDS)


UNKNOWN_MARKERS = [
    "مش عارف", "معرفش", "ماعنديش فكره", "مش فاكر", "مش متاكد",
    "ما اعرفش", "لا اعرف", "مش قادر اقولك", "معنديش فكره",
    # v0.9: "يا عم أنا مش جوجل، بس هدورلك" is a promise of a search that
    # never comes — the turn ends right after it. Treat it as unanswered
    # so the handler actually runs the search instead of shipping it.
    "مش جوجل", "بس هدورلك",
]


def looks_unknown(reply: str) -> bool:
    # Normalise BOTH the reply and the markers: "ماعنديش فكرة" (with ة)
    # must match the marker "ماعنديش فكره".
    r = normalize_arabic(reply or "")
    return any(normalize_arabic(m) in r for m in UNKNOWN_MARKERS)


# v0.9: the "still searching" stall — the LLM claims the search is still
# in progress ("لسه قالك بدور… لما اجيبلك الخلاصه") instead of answering
# from the grounding that is already in its prompt. A stall is not a
# normal reply: the search already ran, so there is nothing left to wait
# for. The handler retries once with a firm instruction, then falls back
# to an extractive answer from the passages.
STALL_MARKERS = [
    "لسه بدور", "لسه قالك", "اجيبلك الخلاصه", "هجيبلك الخلاصه", "استنير",
]


def looks_stalling(reply: str) -> bool:
    r = normalize_arabic(reply or "")
    return any(normalize_arabic(m) in r for m in STALL_MARKERS)


_TARGET_RE = re.compile(r"اشتمي?\s+@?([A-Za-z0-9_\u0600-\u06FF]+)")


def extract_insult_target(text: str) -> str | None:
    """Name/username mentioned after اشتم/اشتمي, e.g. "اشتم محمد" -> "محمد",
    "اشتم @mohamed" -> "mohamed". None when no target is named."""
    m = _TARGET_RE.search(text or "")
    if not m:
        return None
    return m.group(1)
