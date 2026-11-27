"""Post-generation checks — code, not prompt. Runs before sending.
- Egyptian dialect check: reply must not contain Fusha markers.
- Banned AI phrases check.
- Family-insult enforcement (TARGET-AWARE, v1.2): the handler resolves
  the insult target first (tg/handlers.py _resolve_insult_level) and
  passes insult_level="personal_only" when the target is a member or
  unresolved/ambiguous, "full" only for a resolved non-member. Here,
  personal_only + family words means the offending sentences are SILENTLY
  dropped (never narrate the rule, never name the owner mid-roast).
  Family detection lives in core/rules.py (contains_family_insult) and
  covers امك/ابوك/… AND the vocative shapes ("يا ابن الكلب",
  "يا ولاد الكلب", "أم إلهك زانية") — the old word list missed those.
- Leakage filter: the reply must never contain the owner id, prompt
  internals, or key/token-like strings.
- Length: Telegram cap 4096 chars, split on sentence boundaries.
"""
import re

from brain.persona_facts import filter_persona_polarity
try:
    from core.rules import (
        FAMILY_WORDS,
        contains_family_insult as _rules_contains_family,
        normalize_arabic as _core_normalize,
    )
except ImportError:  # core/rules.py has no normalize_arabic yet (v0.4).
    from core.rules import FAMILY_WORDS
    _core_normalize = None
    _rules_contains_family = None

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

# v1.8: self-bot admission — Bahgat must NEVER say HE is a bot/AI
# (Seif's directive after the rival bot kept admitting it: Bahgat
# considers himself a normal human). FIRST-PERSON ONLY, matched on
# the normalised text (so alef/ة/ى variants match), so answers about
# OTHER bots/people — "سعد ده بوت", "انت مش بني آدم" — pass untouched.
# The bare word "بوت" is deliberately NOT here: it is only an
# admission when the speaker applies it to himself.
_SELF_BOT_PATTERNS = [
    "انا بوت",
    "انا ذكاء اصطناعي",
    "انا مش بني ادم",
    "انا مش انسان",
    "انا برنامج",
    "انا نموذج لغوي",
]

# In-character denial served when a reply admits being a bot: the
# whole reply is replaced (a self-admission breaks the turn's stance,
# it cannot be salvaged by word replacement). The denial passes its
# own filter — it contains "مش بوت" but never "انا بوت".
_SELF_BOT_DENIAL = "أنا بهجت يا عم، إنسان عادي، مش بوت."


def contains_self_bot_admission(text: str) -> bool:
    """True when the reply says the SPEAKER is a bot/AI. First-person
    only — "سعد ده بوت" / "انت مش بني آدم" (about others) return False."""
    t = normalize_arabic(text or "")
    return any(p in t for p in _SELF_BOT_PATTERNS)

_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"gsk_[A-Za-z0-9]{10,}"),
    re.compile(r"AIza[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\d{8,}:[A-Za-z0-9_\-]{30,}"),  # Telegram bot token shape
]

_DEFLECTION = "يا عم الكلام ده مش هقوله، قول حاجة تانية."


def contains_family(text: str) -> bool:
    """Canonical family-insult check (core/rules.py): possessive family
    words AND the vocative shapes ("يا ابن الكلب", "يا ولاد الكلب",
    "أم إلهك زانية"). Word-boundary aware, so innocent words containing
    a family word as a substring ("امكانيات", "ابن خلدون", "يا ابن عمي",
    "أم كلثوم") do not match. Falls back to the bare word list if the
    canonical check is unavailable (old core/rules.py)."""
    if _rules_contains_family is not None:
        return bool(_rules_contains_family(text))
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


# v1.13: internal instruction blocks the LLM sometimes echoes into its
# reply ([MEMORY] is sent as a user-role message; [BANK LINE] sits in
# the system prompt). They are never legitimate reply content, so
# check_reply strips them. A reply that was ONLY a leaked block comes
# out empty and the handler's empty-reply fallback answers instead.
_INTERNAL_BLOCK_RES = [
    re.compile(r"\[MEMORY\].*?\[/MEMORY\]", re.DOTALL),
    re.compile(r"\[BANK LINE.*?\].*?\[/BANK LINE\]", re.DOTALL),
]


# v1.14: script-mixing filter. The LLM sometimes mixes scripts into an
# otherwise Arabic reply — live v1.13: Latin "مessi" / "ya" / "متnak",
# Hebrew "גדול", Cyrillic "б" inside "عبيط". Bahgat writes Egyptian
# Arabic only, so Hebrew / Cyrillic / Greek characters are never
# legitimate — with one correction to the naive "strip them" idea: the
# live Cyrillic artifact was a SUBSTITUTE, not an extra letter
# ("عбиط" is ع + Cyrillic б + ي + ط, the б standing in for the Arabic
# ب), so stripping it alone leaves the wrong word "عيط". The
# confusable б is therefore mapped to ب first, and only the remaining
# foreign-script characters are stripped. A token mixing Arabic and
# Latin letters in one word is never legitimate (the whole token
# goes), and a standalone Latin token is kept only when allowlisted
# (PES / eFootball / Android / iPhone / Mac / YouTube). Fast path: a
# reply with no foreign-script or Latin letter is returned untouched.
_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_GREEK_RE = re.compile(r"[\u0370-\u03FF]")
_FOREIGN_SCRIPT_RE = re.compile(r"[\u0590-\u05FF\u0400-\u04FF\u0370-\u03FFA-Za-z]")
# Cyrillic lookalike standing in for an Arabic letter (live v1.13).
_CONFUSABLES = {"\u0431": "ب"}  # Cyrillic small letter be → Arabic beh
_LATIN_ALLOWLIST = frozenset(
    {"pes", "efootball", "android", "iphone", "mac", "youtube"})


def _strip_script_mixing(text: str) -> str:
    if not _FOREIGN_SCRIPT_RE.search(text):
        return text
    for conf, repl in _CONFUSABLES.items():
        text = text.replace(conf, repl)
    text = _HEBREW_RE.sub("", text)
    text = _CYRILLIC_RE.sub("", text)
    text = _GREEK_RE.sub("", text)
    out = []
    for tok in text.split(" "):
        if not tok:
            continue
        # Arabic LETTERS only (U+0621–U+064A) — the wider Arabic block
        # also holds punctuation (، ؛ ؟), and a Latin token next to an
        # Arabic comma ("PES،") is not a mixed token.
        has_ar = any("\u0621" <= c <= "\u064a" for c in tok)
        has_lat = any(c.isascii() and c.isalpha() for c in tok)
        if has_ar and has_lat:
            continue  # mixed token ("مessi", "متnak"): drop it whole
        if has_lat and not has_ar:
            core = tok.strip(".,!؟،؛:;\"'()[]")
            if core.lower() not in _LATIN_ALLOWLIST:
                continue
        out.append(tok)
    return " ".join(out)


def check_reply(text: str, insult_level: str = "full", owner_id=None,
                *, persona_selection=None) -> tuple[bool, str]:
    """Returns (ok, cleaned_text).

    - personal_only + family words: silently drop the offending sentences;
      if nothing is left, substitute a neutral in-character line. Never
      append meta-commentary naming the owner or the rule.
    - Banned AI phrases: replaced as before.
    - Self-bot admission ("أنا بوت" / "أنا ذكاء اصطناعي" / ... about
      HIMSELF): the whole reply is replaced with an in-character denial
      — the bot never sends a self-admission, even if the LLM produced
      one. Answers about OTHER bots/people are untouched.
    - Leakage (owner id / prompt internals / key-like strings): the whole
      reply is replaced with a deflection.
    - v1.13: markdown bold markers (** / __) are stripped (the LLM wraps
      woven bank lines in them), and internal instruction blocks the
      model echoed ([MEMORY]...[/MEMORY], [BANK LINE]...[/BANK LINE])
      are removed — live 2026-11-27 a [MEMORY] block leaked into a
      user-facing reply. Stripping happens FIRST, before the other
      checks, so a reply that was only a leaked block falls through to
      the handler's empty-reply fallback.
    - v1.14: script-mixing is stripped (see _strip_script_mixing), and
      when the handler passes persona_selection (a select_facts() dict
      for this turn), the deterministic polarity post-filter drops
      clauses from the unselected polarity and falls back to a canned
      template from the selected rows — never to the full persona block.
      The leak check runs BEFORE the script-mixing strip: the strip
      drops standalone Latin tokens, which is exactly what a leaked
      key / "SYSTEM_BASE" mention is.
    """
    cleaned = text or ""
    ok = True
    cleaned = cleaned.replace("**", "").replace("__", "")
    for _block_re in _INTERNAL_BLOCK_RES:
        cleaned = _block_re.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    # Leak check runs BEFORE the script-mixing strip (v1.14): the
    # strip drops standalone Latin tokens, which is exactly what a
    # leaked key / "SYSTEM_BASE" mention is — checking after the
    # strip would let the leak through as a clean reply.
    if _leaks(cleaned, owner_id):
        return False, _DEFLECTION
    cleaned = _strip_script_mixing(cleaned)
    if persona_selection is not None:
        cleaned = filter_persona_polarity(cleaned, persona_selection)
    if insult_level == "personal_only" and contains_family(cleaned):
        cleaned = _strip_family_sentences(cleaned)
        if not cleaned:
            cleaned = "يا عم انت بتتكلم كلام فاضي، ركز."
        ok = False
    for b in BANNED:
        if b in cleaned:
            cleaned = cleaned.replace(b, "يا عم")
            ok = False
    if contains_self_bot_admission(cleaned):
        cleaned = _SELF_BOT_DENIAL
        ok = False
    return ok, cleaned


def _contains_any(normalised: str, markers) -> bool:
    """Substring match with markers normalised the same way as the text,
    so a list entry written with ة/ى still matches."""
    return any(normalize_arabic(m) in normalised for m in markers)


# v1.1 voice check (research method #4, docs/research-persona-methods.md
# §6.2): the prompt can fail and the reply comes out polite / Fusha /
# apologetic — the exact v1.0 failure (opinion challenge answered by
# restating the theory). Pure regex, no LLM call. Returns a list of
# flags; [] means the reply sounds like Bahgat. The handler regenerates
# once on flags, then sends the best and logs them.
_APOLOGY_MARKERS = ["آسف", "أعتذر", "متأسف", "عذراً"]
_SOFTENING_MARKERS = ["كنت بهزر", "بهزر معاك", "مش قصدي"]
_RESTATEMENT_OPENERS = [
    "النظرية بتقول", "النظرية تقول", "دي نظرية بتقول", "باختصار",
]
_ANGRY_MARKERS = [
    "احا", "وسخ", "معرص", "معفن", "حمار", "غبي", "خول", "عرص", "زبر",
]
# The angry-turn check exempts only the DISTINCTIVE lazma: "تمام" /
# "خلاص" / "يا عم" are so common they appear in polite replies too, so
# they must not exempt an angry turn from the flag.
_STRONG_LAZMA_MARKERS = [
    "والله العظيم", "لا لا", "اسمع", "بقولك", "بقول لك",
]


# v1.3 soft-polite ban (the v1.2 live failure was a bot whose DEFAULT
# register was polite-with-occasional-insults). These markers can never
# appear in a good Bahgat reply — not in a search answer, not in a song
# list — so they flag on EVERY turn, not only angry ones. Mock-polite
# address ("عادي يا أستاذة قحبة", a bank line) is Bahgat's; the bare
# service greeting ("أهلا بك") and the surrender ("عندك حق", "أنا غلطان")
# are not. "شكرا" on its own is NOT in this list: a thanks reply is
# fine — it is only soft under provocation (see provoked= below).
_SOFT_POLITE_MARKERS = [
    "بكل سرور", "يسعدني", "في خدمتك", "تحت امرك", "تحت أمرك",
    "بكل احترام", "من فضلك", "لو سمحت", "شكرا لتواصلك",
    "اتمني لك", "أتمنى لك", "يوم سعيد", "حاضر يا فندم",
    "حقك عليا", "انا غلطان", "أنا غلطان", "عندك حق", "انت صح",
    "ممكن اكون غلطان", "يمكن اكون غلطان", "اهلا بك", "مرحبا بك",
]
# Edge markers: Bahgat's edge is not only profanity ("احا", "حمار") and
# the strong lazma — a dismissive stance ("نظرية فاضية", "إنت بتستخف
# بالناس", "كذاب ومدلس") is edge too. These exempt a reply from the
# angry-turn and provoked-turn soft flags, the same way _ANGRY_MARKERS
# and _STRONG_LAZMA_MARKERS do.
_EDGE_MARKERS = [
    "فاضي", "فاضية", "هبل", "عبط", "كلام فاضي", "دماغك",
    "اخرس", "اسكت", "غور", "كذاب", "مدلس", "افحمتك",
    "بتستخف", "بتخرف", "بتدلس", "بتكذب",
]


def voice_check(reply: str, mood: int = 0, provoked: bool = False) -> list[str]:
    """Flags for a reply that does not sound like Bahgat. [] = pass.

    provoked=True is for turns where the user insulted, challenged, or
    otherwise provoked the bot (the handler knows: looks_like_insult /
    challenge turns). On a provoked turn a reply with no edge at all —
    no insult, no strong lazma, no dismissive edge — is soft even at
    low mood, so it flags "soft_reply_to_provocation". The handler does
    not pass provoked yet (it calls voice_check(reply, mood)); wiring
    it is a one-line follow-up there. Default False keeps every
    existing call site's behaviour.
    """
    flags = []
    t = normalize_arabic(reply or "")
    if _contains_any(t, FUSHA) or _contains_any(t, _APOLOGY_MARKERS):
        flags.append("fusha_or_apology")
    if any(b in (reply or "") for b in BANNED):
        flags.append("ai_phrase")
    if contains_self_bot_admission(reply or ""):
        # v1.8: the bot admitting it is a bot is a persona failure —
        # the handler regenerates once on flags, then check_reply
        # replaces any surviving admission with the denial.
        flags.append("self_bot_admission")
    # The v1.0 failure opened "بحس يا سيدي، دي نظريه بتقول..." — the
    # restatement sits mid-sentence, so this is a substring match, not
    # a startswith. Only runs on just_chat/voice turns (the handler
    # excludes search-grounded replies), where reporting the theory
    # instead of a stance is the failure.
    if _contains_any(t, _RESTATEMENT_OPENERS):
        flags.append("polite_restatement")
    if _contains_any(t, _SOFTENING_MARKERS):
        flags.append("soft_ending")
    if _contains_any(t, _SOFT_POLITE_MARKERS):
        flags.append("soft_polite")
    if (
        (mood or 0) >= 70
        and not _contains_any(t, _ANGRY_MARKERS)
        and not _contains_any(t, _STRONG_LAZMA_MARKERS)
        and not _contains_any(t, _EDGE_MARKERS)
    ):
        flags.append("angry_turn_came_out_polite")
    if (
        provoked
        and not _contains_any(t, _ANGRY_MARKERS)
        and not _contains_any(t, _STRONG_LAZMA_MARKERS)
        and not _contains_any(t, _EDGE_MARKERS)
    ):
        flags.append("soft_reply_to_provocation")
    return flags


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
