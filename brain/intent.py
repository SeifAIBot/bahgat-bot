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
    # v1.0: normalize the KEYWORDS too, not just the message. Before this,
    # a list entry written with ى/ة could never match: the text "دور على"
    # normalizes to "دور علي", so the raw entry "دور على" was dead weight
    # (verified live: _has("دور علي", ["دور على"]) was False). Normalizing
    # both sides is the standard rule (Larkey et al. SIGIR 2002; see
    # docs/research-intent-routing.md §3) and makes duplicate spellings
    # in the lists unnecessary.
    return any(
        re.search(rf"(?<!\w){re.escape(normalize_arabic(w))}(?!\w)", text)
        for w in words
    )


def _content_words(text: str) -> list[str]:
    """Words of a normalised message with the trigger tokens removed
    ("بهجت" and @mentions) — used to judge how much *content* a short
    message carries (bare "بهجت اغنية الخلاصه" is a song request, bare
    "بهجت" is not)."""
    t = re.sub(r"@\w+", " ", text or "")
    t = re.sub(r"(?<!\w)بهجت(?!\w)", " ", t)
    return re.sub(r"\s+", " ", t).strip().split() if t.strip() else []


def _skip_leading_vocative(words: list[str]) -> list[str]:
    """Drop a LEADING "يا" vocative ("يا بهجت قول ..." — _content_words
    already stripped "بهجت", so the first content word is "يا"; "يا قول
    ..." has no بهجت at all). Only the first word is touched: "يا"
    mid-sentence is content ("قول يا عم نكته" keeps its "يا")."""
    return words[1:] if words and words[0] == "يا" else words


# All patterns below are written in NORMALISED form (e.g. "علي" not "على",
# "النتيجه" not "النتيجة") because matching runs on normalised text — and
# since v1.0 _has() normalises the keywords too, so a list entry written
# with ى/ة still matches (the old "دور على" duplicate is gone: it
# normalises to "دور علي").
_VOICE_WORDS = ["بصوتك", "قولها بصوت", "فويس", "ابعت فويس", "قولي بصوتك"]
_YOUTUBE_WORDS = [
    "هات فيديو", "هاتي فيديو", "هات اغنيه", "هاتي اغنيه",
    # v1.0: "هاتلي"/"جبلي"/"نزل" were standalone triggers here, but they
    # are request verbs, not media — "هاتلي ملخص" is a summary request,
    # "نزل سعر الدولار" is a price question. They live in
    # _YOUTUBE_VERBS now and only fire with a media noun (media+verb
    # rule below). "شغل" stays standalone: "شغل X" means play X.
    "شغل", "شغلي",
    "عايز اغنيه", "عاوز اغنيه", "عايز فيديو", "عاوز فيديو",
]
# v1.0: media nouns + request verbs. The bare word "دورلي" is a *search*
# verb ("دورلي علي حادثة الوراق" -> search), so it only means YouTube
# when a media noun is present ("دورلي علي اغنية مروان موسي الخلاصه").
# Bare media mentions ("بهجت اغنية الخلاصه", "تراك مروان موسي") also
# count as YouTube when the message is short and not a question —
# naming a track at the bot is a request to play it. ال-prefixed forms
# included: "الاغنيه" must match too, or "دورلي علي الاغنية" misses.
_YOUTUBE_MEDIA = [
    "اغنيه", "الاغنيه", "تراك", "التراك", "فيديو", "الفيديو",
    "كليب", "الكليب", "موسيقي", "الموسيقي", "صوت", "الصوت",
]
_YOUTUBE_VERBS = [
    "دورلي", "دور لي", "هاتلي", "هاتيلي", "هات لي", "جبلي", "شغل",
    "شغلي", "اسمع", "نزل", "نزلي", "عايز", "عاوز", "دور", "جيب",
]
# Question markers: a message asking ABOUT a song ("ايه رايك في اغنية
# مروان موسي") is a question for the LLM, not a play request — the
# bare-media rule below must not fire on it.
_QUESTION_MARKERS = [
    "؟", "ايه", "رايك", "مين", "ليه", "ازاي", "امتى", "فين", "كام", "بكام",
]
_BARE_MEDIA_MAX_WORDS = 4
_SEARCH_WORDS = [
    "دور علي", "دورلي", "ابحث", "ايه هو", "مين هو", "اخبار", "خبر",
    "سعر", "النتيجه", "مين بهجت", "مين كسب", "كسب مين", "كام", "امتى", "فين",
    "بكام", "ايه اللي حصل", "ايه الحصل", "ايه حصل", "سيرش", "علي النت",
    "حادثه", "عايز اعرف", "عاوز اعرف",
]
# v0.9: "سيرش على النت على حادثة الوراق" missed every keyword above
# (no "سيرش", no "على النت", no "حادثه") and fell through to just_chat,
# so no search ran before the first LLM call and the bot answered with
# a "هدورلك" promise instead of a result. v1.0: _has() now normalises
# the keywords too, so the "دور على"/"على النت" duplicates are gone.


# v1.1: bare artist names after "هات" — "هات مروان موسي" is a request
# for the artist's songs, not a summary. The remainder counts as an
# artist query when it is SHORT (<= 3 words), has no question markers,
# and contains no clearly non-media noun. "هات ملخص" stays out via the
# denylist (a summary is not a video); "هاتلي فلوس" too.
_NON_MEDIA_NOUNS = [
    "ملخص", "سعر", "اسعار", "خبر", "اخبار", "نتيجه", "معلومه",
    "معلومات", "ترجمه", "صوره", "لينك", "رابط", "عنوان", "رقم",
    "كود", "حساب", "كلمه", "فلوس",
]
_HAAT_PREFIXES = ("هات", "هاتلي", "هاتيلي", "جبلي")
_BARE_ARTIST_MAX_WORDS = 3


def _looks_like_bare_artist(rest: list[str]) -> bool:
    """Remainder after a هات-family verb that reads as an artist name:
    short, not a question, no non-media noun."""
    if not rest or len(rest) > _BARE_ARTIST_MAX_WORDS:
        return False
    rest_s = " ".join(rest)
    if _has(rest_s, _QUESTION_MARKERS):
        return False
    if _has(rest_s, _NON_MEDIA_NOUNS):
        return False
    return True


def _bare_artist_after_verb(text: str) -> bool:
    """A هات-family verb mid-message ("يا بهجت هاتلي مروان موسي") followed
    by a bare artist name. The prefix layer only fires when the verb is
    the first word, so the classifier needs the same rule."""
    words = _content_words(text)
    for i, w in enumerate(words):
        if w in _HAAT_PREFIXES:
            rest = words[i + 1:]
            if rest and rest[0] == "لي":
                rest = rest[1:]
            if _looks_like_bare_artist(rest):
                return True
    return False


# --- v1.1: opinion questions -------------------------------------------------
# "ايه رايك في نظريه المليار الذهبي" must get a STANCE, not a summary.
# The live v1.0 failure: the bot restated the theory ("دي نظريه بتقول
# ان فيه ناس عايزه تقلل...") instead of taking a position. Detection is
# deliberately narrow — "رايك" and "شايف ايه" / "انت شايف" only.
_OPINION_MARKERS = ["رايك", "شايف ايه", "انت شايف"]


def looks_like_opinion_ask(text: str) -> bool:
    """User asks the bot's opinion — the reply must take a sharp stance,
    not restate the topic."""
    return _has(normalize_arabic(text or ""), _OPINION_MARKERS)


def detect_intent(text: str) -> str:
    t = normalize_arabic(text or "")
    low = t.lower()
    # v1.0: deterministic prefix layer first (Seif's design) — "دور"
    # search, "هات" YouTube, "قول" voice. See detect_prefix_mode.
    prefix = detect_prefix_mode(text)
    if prefix is not None:
        return prefix[0]
    if _has(t, _VOICE_WORDS):
        return "voice"
    if "youtu.be" in low or "youtube.com" in low:
        return "youtube"
    if _has(t, _YOUTUBE_WORDS):
        return "youtube"
    # v1.1: bare artist after a هات-family verb mid-message.
    if _bare_artist_after_verb(t):
        return "youtube"
    # v1.0: media noun + request verb ("دورلي علي اغنية ..." is YouTube,
    # "دورلي علي حادثة ..." is search — the verb alone cannot decide).
    # A short bare media mention with no question in it is also a play
    # request ("بهجت اغنية الخلاصه"); a question about a song is not.
    if _has(t, _YOUTUBE_MEDIA):
        if _has(t, _YOUTUBE_VERBS):
            return "youtube"
        if len(_content_words(t)) <= _BARE_MEDIA_MAX_WORDS and not _has(t, _QUESTION_MARKERS):
            return "youtube"
    # v1.3: an insult turn is NEVER a search. This sits after the voice
    # and YouTube checks (those are not searches) and before the search
    # check, so "انت حمار، ايه اللي حصل" cannot reach the search path
    # via a stray search keyword. The live phrase "يا بهجت انتا حمار"
    # already fell through to just_chat here — the search it produced
    # came from the handler's unknown-retry (see tg/handlers.py) — but
    # routing must not depend on that: no insult turn may ever be
    # classified as search, at any layer.
    if looks_like_insult_turn(text):
        return "just_chat"
    if _has(t, _SEARCH_WORDS):
        return "search"
    return "just_chat"


# --- v1.0 prefix layer (Seif's design) --------------------------------------
# Deterministic mode prefixes, checked FIRST, before the keyword
# classifier: "دور" -> search, "هات" -> YouTube, "قول"/"قولي" -> voice.
# This is tier 1 of hybrid routing (rules first for unambiguous
# triggers, classifier for the ambiguous tail — see
# docs/research-intent-routing.md §5). The message may start with the
# trigger "بهجت" (or an @mention) before the prefix word. v1.7: it
# may also start with the vocative "يا" — "يا بهجت قول ..." and "يا
# قول ..." — which _content_words does NOT strip (it only strips
# "بهجت" and @mentions); detect_prefix_mode skips one leading "يا" so
# Seif's usual "يا بهجت ..." form reaches the prefix layer, while a
# "يا" anywhere else in the message is untouched. Matching is
# word-boundary + normalised, so "دورلي" is NOT the "دور" prefix and
# "الدور" is not either.
#
# Guards (a prefix must not force a wrong mode):
# - empty remainder ("دور" alone) -> fall through to the classifier;
# - question remainder ("دور مين؟" is "whose turn?", not a search) ->
#   fall through;
# - media noun after "دور" ("دور اغنية مروان موسي" is a song request,
#   not a web search) -> fall through (the classifier's media+verb
#   rule routes it to YouTube);
# - non-media remainder after "هات" ("هات ملخص" is a summary, not a
#   video) -> fall through (the classifier routes it, e.g. to search
#   via "حادثه") — EXCEPT a short bare artist name ("هات مروان موسي",
#   v1.1), which is a song request and goes to YouTube.
def detect_prefix_mode(text: str) -> tuple[str, str] | None:
    """Return (mode, remainder) when the message starts with a mode
    prefix, else None. The remainder is the normalised text after the
    prefix word, ready to use as a search / YouTube query — for a
    prefix search it is self-contained and must NOT get the follow-up
    topic inheritance (_search_query) applied to it."""
    words = _skip_leading_vocative(
        _content_words(normalize_arabic(text or "")))
    if not words:
        return None
    first, rest = words[0], words[1:]
    if not rest:
        return None
    rest_s = " ".join(rest)
    if _has(rest_s, _QUESTION_MARKERS):
        return None
    # v1.1: the "قول" prefix is checked BEFORE the voice-words guard —
    # "قول اهلا في فويس نوت" (live 6:10 PM) contains "فويس" in its
    # remainder, so the old order returned None here and the handler
    # lost voice_only: the turn sent TEXT first + trailing voice
    # instead of a voice note. The guard below exists for "دور"/"هات"
    # ("هات فيديو بصوتك" is a voice request, not YouTube) and must
    # never veto the voice prefix itself.
    if first in ("قول", "قولي"):
        return ("voice", rest_s)
    # Voice beats every prefix: "هات فيديو بصوتك" is a voice request,
    # not a YouTube search (the classifier's voice > youtube priority).
    if _has(rest_s, _VOICE_WORDS):
        return None
    if first == "دور":
        if _has(rest_s, _YOUTUBE_MEDIA):
            return None
        # v1.3: "دور يا حمار" is an insult, not a search — the remainder
        # carries no information request. Fall through to the classifier,
        # whose insult guard routes it to just_chat.
        if looks_like_insult(rest_s):
            return None
        return ("search", rest_s)
    if first in _HAAT_PREFIXES:
        # "هات لي ..." — drop the stray "لي" so the remainder is the query.
        if first == "هات" and rest and rest[0] == "لي":
            rest = rest[1:]
            if not rest:
                return None
            rest_s = " ".join(rest)
        if _has(rest_s, _YOUTUBE_MEDIA):
            return ("youtube", rest_s)
        # v1.1: bare artist name ("هات مروان موسي") is a song request —
        # people ask for an artist's songs by name. Short remainder, no
        # question, no non-media noun (the "هات ملخص" guard stays).
        if _looks_like_bare_artist(rest):
            return ("youtube", rest_s)
        return None
    return None


_INSULT_RE = re.compile(
    # v1.3: "انتا" is the common Egyptian spelling of "انت" (trailing
    # alif) — "يا بهجت انتا حمار" (live 2026-11-26 19:53 EET) missed
    # this regex entirely, so no insult path fired for it. Longest
    # first: "انتا" must be tried before "انت" (which cannot match
    # "انتا حمار" — "انت" is followed by "ا", not whitespace).
    # v1.6 phase 2: the noun lists were the 5 tamest words only
    # (حمار/غبي/كلب/عبيط/حيوان), so the commonest Egyptian insults —
    # "يا معرص", "يا شرموط", "يا وسخ", "يا خول", "يا ابن الكلب" —
    # never reached the bank at all, and the family-attacked situation
    # could never fire. The lists now cover the usual nouns, the
    # "يا ابن ..." family vocatives, and bare "امك"/"ابوك".
    # "يا ابن عمي" (friendly) is still excluded in looks_like_insult.
    r"(انتا|انت|انته)\s+(حمار|غبي|كلب|عبيط|حيوان|وسخ|معرص|شرموط|متناك|خول|قحبه|عرص|منيك|علق)"
    r"|يا\s*(حمار|غبي|كلب|عبيط|حيوان|وسخ|معرص|شرموط|متناك|خول|قحبه|عرص|منيك|علق)"
    r"|يا ابن (الكلب|المتناك|المتناكه|الوسخ|الوسخه|الشرموط|الشرموطه|القحبه|دين الكلب|الحرام|المتنكه)"
    r"|ابن (الكلب|المتناك|المتناكه|الوسخ|الوسخه|دين الكلب)"
    r"|(ولد|ولاد) (الكلب|الوسخ|الوسخه|دين الكلب)"
    r"|(?<!\w)(امك|ابوك|ابوكي)(?!\w)"
    r"|(هقتلك|هضربك|هكسرك|هفضحك|هفشخك|هموتك)"
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


# --- v1.0 fast path: trivial chat -------------------------------------------
# Research (docs/research-intent-routing.md §2): even classifier-based
# production bots keep a regex fast path for "obvious greetings", and
# predictable messages get canned replies — no model call, no quota, no
# status bubble. The live trigger: "شكرا يا بهجت" ran a full LLM turn
# with a "بفكر يا عم، استنى…" bubble for a thank-you.
#
# Guard rails (deliberately narrow — a false positive here answers a
# real question with a canned line):
# - short only (<= 3 content words after the trigger is stripped);
# - no question mark; no insult; no apology ("خلاص انا اسف" is a real
#   forgiveness turn, not a template — the LLM handles it);
# - calm mood only (mood >= 70: an angry Bahgat does not sweetly say
#   "العفو" — the LLM handles it);
# - the caller must already have checked just_chat + no grudge.
_TRIVIAL_MAX_WORDS = 3
_FAST_MOOD_MAX = 70
_FAST_THANKS = ("شكرا", "تسلم", "مشكور", "تشكر")
_FAST_GREETINGS = (
    "اهلا", "اهلين", "السلام عليكم", "صباح الخير", "مساء الخير",
    "هاي", "هلا", "ازيك", "عامل ايه", "ازيكم", "مرحبا",
    "صباح النور", "مساء النور",
)
_FAST_ACK = ("تمام", "ماشي", "اوكي", "اوك", "طيب", "حاضر", "خلاص", "اوكيه")
_FAST_REPLIES = {
    "thanks": ["العفو يا عم، ده واجبي.", "ماشي يا سيدي، انت تؤمر.",
               "على إيه يا عم، ده أقل حاجة."],
    "greeting": ["أهلاً يا عم، زي الفل؟", "تمام يا عم، انت عامل ايه؟",
                 "أيوه يا عم، جايبلي ايه النهارده؟"],
    "ack": ["تمام يا عم.", "ماشي يا سيدي.", "خلاص يا عم، فهمت."],
    "laugh": ["ههههههه", "هههههههه"],
    "bare": ["أيوه يا عم؟", "نعم يا سيدي؟"],
}


def _fast_pick(kind: str, seed: str) -> str:
    """Deterministic-ish variant pick: rotates every 30 minutes so the
    same user saying "شكرا" twice does not get the identical line twice
    in a row forever, but stays stable inside one test run window.
    Tests should assert membership in _FAST_REPLIES[kind], not a
    specific variant."""
    import time
    import zlib

    variants = _FAST_REPLIES[kind]
    bucket = int(time.time() // 1800)
    idx = zlib.crc32(f"{seed}|{bucket}".encode("utf-8")) % len(variants)
    return variants[idx]


def detect_fast_reply(text: str, mood: int = 30) -> str | None:
    """Instant local reply for trivial chat, or None when the turn needs
    the LLM. Never raises; returns None on any doubt — a missed fast
    path only costs one LLM call, a wrong one answers a real question
    with a canned line."""
    if mood is not None and mood >= _FAST_MOOD_MAX:
        return None
    t = normalize_arabic(text or "")
    if not t or "؟" in t or "?" in t:
        return None
    if looks_like_insult(text):
        return None
    words = _content_words(t)
    # v1.7: same leading-vocative gap as the prefix layer — "يا بهجت
    # شكرا" built "يا شكرا" and missed the fast path, so a thank-you
    # in Seif's usual form cost a full LLM turn. Only the leading "يا"
    # is dropped; the insult guard above already ran on the full text.
    words = _skip_leading_vocative(words)
    if not words:
        return _fast_pick("bare", t)
    if len(words) > _TRIVIAL_MAX_WORDS:
        return None
    s = " ".join(words)
    # Apologies are real turns (forgiveness), never templates.
    if "اسف" in s or "معلش" in s:
        return None
    if re.fullmatch(r"ه{2,}", s):
        return _fast_pick("laugh", t)
    for kind, patterns in (
        ("thanks", _FAST_THANKS),
        ("greeting", _FAST_GREETINGS),
        ("ack", _FAST_ACK),
    ):
        for p in patterns:
            if s == p or s.startswith(p + " "):
                return _fast_pick(kind, t)
    return None


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


_TARGET_RE = re.compile(r"اشتم(?:وا|ي)?\s+@?([A-Za-z0-9_\u0600-\u06FF]+)")


def extract_insult_target(text: str) -> str | None:
    """Name/username mentioned after اشتم/اشتمي, e.g. "اشتم محمد" -> "محمد",
    "اشتم @mohamed" -> "mohamed". None when no target is named."""
    m = _TARGET_RE.search(text or "")
    if not m:
        return None
    return m.group(1)


def looks_like_insult_turn(text: str) -> bool:
    """v1.3: the whole turn is an insult turn — an insult directed at
    the bot (looks_like_insult) OR a roast request ("اشتم X",
    extract_insult_target). Either kind must NEVER run a web search:
    the handler's unknown-retry search is gated on this, and
    detect_intent() routes it to just_chat before the search check."""
    return looks_like_insult(text) or extract_insult_target(text) is not None


# --- v1.6 phase 2: insult situations -----------------------------------------
# What the USER did to the bot (insulted pool) or why the roast target
# deserves it (roast pool, from the roast request's extra words).
# Deterministic keyword rules on normalised Arabic, same style as the
# rest of this module — no LLM call on any message. Ambiguous tail ->
# "general". The reply bank tags every served insulted/roast line with
# `situations:` from these taxonomies; brain/reply_bank.py prefers
# lines whose tags match the detected situation.
INSULTED_SITUATIONS = (
    "mocked", "called-dumb", "sworn-at", "family-attacked",
    "threatened", "dismissed", "repeated-insult", "general",
)
ROAST_SITUATIONS = (
    "arrogant", "stupid-statement", "cowardly", "annoying", "perv",
    "general",
)

# "يا ابن عمي" (friendly) must never read as a family attack.
_FAMILY_ATTACK_WORDS = [
    "ابن الكلب", "ابن المتناك", "ابن المتناكه", "ابن الوسخ",
    "ابن الوسخه", "ابن دين الكلب", "ابن الشرموط", "ابن الشرموطه",
    "ابن القحبه", "ابن الحرام", "ابن المتنكه",
    "امك", "ابوك", "ابوكي", "ولاد الكلب", "ولاد دين الكلب",
    "يا ابن ال",
]
_THREAT_WORDS = [
    "هقتلك", "هضربك", "هكسرك", "هفضحك", "هفشخك", "هموتك",
    "هنيكك", "لو راجل", "هعمل فيك", "هوريك",
]
# Insult nouns that, repeated, mark a repeated insult ("يا حمار يا حمار").
_REPEAT_INSULT_NOUNS = [
    "حمار", "غبي", "كلب", "عبيط", "حيوان", "وسخ", "معرص",
    "شرموط", "متناك", "خول", "قحبه", "عرص", "منيك",
]
_LAUGH_RE = re.compile(r"(ه{3,}|خ{3,}|هاها)")
_MOCKED_WORDS = ["بتتريق", "بتسخر", "مسخره", "بتضحك", "بتضحك عليا"]
_CALLED_DUMB_WORDS = [
    "حمار", "غبي", "عبيط", "متخلف", "جاهل", "بهيم", "بهيمه",
    "جاموس", "حيوان", "مبتفهمش", "مش فاهم", "بتخرف", "اهبل",
    "هبله", "غبيه",
]
_SWEAR_WORDS = [
    "معرص", "وسخ", "شرموط", "متناك", "خول", "قحبه", "كلب",
    "عرص", "منيك", "علق",
]
_DISMISSED_WORDS = [
    "انت غلط", "كلامك غلط", "مش صحيح", "انت مش فاهم",
    "انت ولا حاجه", "ولا حاجه", "فاشل", "تافه", "ملكش لازمه",
    "انت مين", "مين انت", "اخرس", "اسكت",
]


def _repeated_insult(t: str) -> bool:
    """Same insult noun twice ("يا حمار يا حمار"), or "تاني"/"برضه"
    on top of an insult — the user is at it again, not starting."""
    words = t.split()
    for w in _REPEAT_INSULT_NOUNS:
        if words.count(normalize_arabic(w)) >= 2:
            return True
    return _has(t, ["تاني", "برضه", "برده"]) and looks_like_insult(t)


def detect_insult_situation(text: str) -> str:
    """Situation of an insult aimed at the bot, from the incoming
    message alone. Priority is specificity: a family attack outranks
    a generic swear, a threat outranks a taunt, laughter marks mockery
    even when an insult noun is present too. Returns "general" when
    nothing specific matches."""
    t = normalize_arabic(text or "")
    if "يا ابن عمي" in t:
        return "general"
    if _has(t, _FAMILY_ATTACK_WORDS):
        return "family-attacked"
    if _has(t, _THREAT_WORDS):
        return "threatened"
    if _repeated_insult(t):
        return "repeated-insult"
    if _LAUGH_RE.search(t) or _has(t, _MOCKED_WORDS):
        return "mocked"
    if _has(t, _CALLED_DUMB_WORDS):
        return "called-dumb"
    if _has(t, _SWEAR_WORDS):
        return "sworn-at"
    if _has(t, _DISMISSED_WORDS):
        return "dismissed"
    return "general"


# Roast situations come from the extra words AFTER "اشتم X" — a bare
# "اشتم X" carries no situation and is "general".
_ROAST_ARROGANT_WORDS = [
    "بيتباهي", "بيتفاخر", "مغرور", "بيتنطط", "بيتكبر", "متكبر",
    "شايف نفسه", "فاكر نفسه", "بيتفشخر", "غرور", "عايش الدور",
]
_ROAST_STUPID_WORDS = [
    "غبي", "حمار", "عبيط", "متخلف", "جاهل", "بيهبد", "هبد",
    "بيخرف", "اهبل", "هبله", "بيقول كلام غبي", "كلامه غبي",
    "مبيفهمش", "مش فاهم حاجه",
]
_ROAST_COWARDLY_WORDS = [
    "جبان", "خايف", "بيهرب", "بيخاف", "بيستخبي", "جبن",
]
_ROAST_ANNOYING_WORDS = [
    "مزعج", "بيزعج", "بيزن", "رغاي", "بيتكلم كتير", "ممل",
    "بيكرر", "بيعيد", "صدعنا", "زهقنا", "بيضايق", "بيضايقنا",
    "رخم",
]
_ROAST_PERV_WORDS = [
    "شرموط", "قحبه", "منحرف", "بيتحرش", "سافل", "متناك",
    "عرص", "بيشتهي", "بيبعبص", "داعر", "عاهر",
]


def detect_roast_situation(text: str) -> str:
    """Situation of a roast request, from the words after "اشتم X".
    The target name itself is stripped first, so "اشتم محمد" is
    "general" while "اشتم محمد عشان بيتباهى" is "arrogant"."""
    t = normalize_arabic(text or "")
    rest = _TARGET_RE.sub(" ", t)
    rest = re.sub(r"(?<!\w)اشتم(?:وا|ي)?(?!\w)", " ", rest)
    rest = re.sub(r"(?<!\w)بهجت(?!\w)", " ", rest)
    if _has(rest, _ROAST_ARROGANT_WORDS):
        return "arrogant"
    if _has(rest, _ROAST_STUPID_WORDS):
        return "stupid-statement"
    if _has(rest, _ROAST_COWARDLY_WORDS):
        return "cowardly"
    if _has(rest, _ROAST_ANNOYING_WORDS):
        return "annoying"
    if _has(rest, _ROAST_PERV_WORDS):
        return "perv"
    return "general"


# v1.13: gender / number of the roast target, from the request's own
# wording only. No name list, no guessing: Arabic names are not
# reliably gendered by string rules, and a wrong guess would serve
# feminine lines to men (the exact bug). The feminine signal is the
# imperative "اشتمي" or a feminine marker word after the target
# ("البنت", "الست"); the plural signal is "اشتموا", a plural marker
# ("العيال", "الناس", "دول"), or a collective target (a team is
# addressed as plural — "انتو"). Anything else -> None, the
# masculine/singular default (Arabic unmarked default).
_PLURAL_TARGETS = frozenset({
    "الزمالك", "الاهلي", "المنتخب", "ريال مدريد", "برشلونه",
})


def detect_roast_target_gender(text: str) -> str | None:
    """'f' when the roast request is feminine-marked, else None."""
    t = normalize_arabic(text or "")
    if re.search(r"اشتمي\s", t):
        return "f"
    if _has(t, ["البنت", "الست"]):
        return "f"
    return None


def detect_roast_target_number(text: str) -> str | None:
    """'plural' when the roast request is plural-marked, else None."""
    t = normalize_arabic(text or "")
    if re.search(r"(?<!\w)اشتموا(?!\w)", t):
        return "plural"
    if _has(t, ["العيال", "الناس", "دول"]):
        return "plural"
    target = extract_insult_target(text)
    if target and normalize_arabic(target) in _PLURAL_TARGETS:
        return "plural"
    return None


# v1.13: deep / personal questions ("انت حاسس إنك مبسوط في حياتك ولا
# ناقصك حاجة؟", "أكتر حاجة ندمت عليها إيه؟") — the bot dodged these
# with an insult in four consecutive conversation runs (v1.9–v1.12).
# The fix is a prompt note (answer-first), not a bank pick: these
# turns never reach the bank. Keyword heuristic only; a false positive
# just adds a mild answer-first instruction to a chat turn.
_DEEP_WORDS = [
    "حاسس", "مبسوط", "ناقصك", "ندمت", "ندمان", "خايف", "بتخاف",
    "خوف", "حلمك", "بتحلم", "حياتك", "فرحان", "زعلان", "مكتئب",
    "وحيد", "بتتمنى", "نفسك",
    # v1.16: "خوفك" / "بتخوفك" / "بيخوفك" — "ايه اللي بيخوفك؟" /
    # "خوفك ايه؟" ask about his fear without the bare "خايف" /
    # "خوف" forms. (The v1.16 draft had only "بتخوفك" — the
    # third-person "بيخوفك" in the comment's own example never
    # matched; both prefixes are in the list now.)
    "خوفك", "بتخوفك", "بيخوفك",
]


def looks_like_deep_question(text: str) -> bool:
    """True when the message asks a personal / deep question about
    the bot's feelings, life, regrets or dreams."""
    return _has(normalize_arabic(text or ""), _DEEP_WORDS)


_FEAR_WORDS = ["خايف", "بتخاف", "خوف", "خوفك", "بتخوفك", "بيخوفك"]


def looks_like_fear_question(text: str) -> bool:
    """True when the message asks about fear specifically — a subset
    of looks_like_deep_question. The deep-turn fear containment
    (v1.16) applies ONLY here: a happiness/regret/dream question
    answered sincerely must not be replaced by a fear line (the
    v1.11 deep test's "أنا مبسوط" answer is valid and names no
    fear)."""
    return _has(normalize_arabic(text or ""), _FEAR_WORDS)


# v1.17: regret questions ("ندمت على حاجة؟") — a subset of
# looks_like_deep_question, like fear. The regret containment
# (sincere fallback) applies ONLY here: a fear/happiness/dream
# answer must not be replaced by a regret line.
_REGRET_WORDS = ["ندمت", "ندمان", "ندمانه", "بتندم", "ندم", "الندم"]


def looks_like_regret_question(text: str) -> bool:
    """True when the message asks about regret specifically."""
    return _has(normalize_arabic(text or ""), _REGRET_WORDS)


def deep_question_cluster(text: str) -> str:
    """Which deep-question cluster a message belongs to — "fear",
    "regret", or "deep" (any other personal question). Used for the
    per-cluster previous-answer note and last-reply store (v1.17):
    a repeat is only a repeat of the SAME kind of question."""
    if looks_like_fear_question(text):
        return "fear"
    if looks_like_regret_question(text):
        return "regret"
    return "deep"
