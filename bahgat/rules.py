"""Red-line rules — enforced in code on every generated reply, not only
in the prompt. A reply that trips a rule is rejected and the caller falls
back to a safe bank line.

The red lines (owner decisions, v2.2):
- Family insults are TARGET-AWARE: person-only at group members, full
  range (including family) only at a resolved non-member. The gate is
  `check_reply(text, is_member=...)` / `allowed(text, is_member=...)`;
  the default is_member=True (fail-safe: unknown targets count as
  members). See bahgat/targets.py for how the target is resolved.
- No slurs on religion, ethnicity, nationality or sect.
- No sexual harassment / sexual talk about a person.
- No real threats, no incitement to violence or harm.
- Public figures CAN be roasted by name (owner decision): Sisi is
  insulted directly, Messi is defended never roasted, Salah / Amr Diab /
  Tamer Hosny are mocked freely — see the prompt (bahgat/persona.py).
- Identity: the bot NEVER admits it is a bot (owner decision 2026-11-28,
  recorded as a known compliance risk vs Telegram Bot Terms §5.2(c)-(d);
  the bio still labels it a bot). A self-admission in a generated reply
  is replaced wholesale with the in-character denial below.
"""
import re

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
_DIACRITICS = re.compile(r"[ً-ْـ]")
_HAMZA_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ئ": "ي", "ؤ": "و"})


def normalize_arabic(text: str) -> str:
    """Strip diacritics/tatweel, unify hamza/ة/ى, collapse whitespace."""
    if not text:
        return ""
    t = _DIACRITICS.sub("", str(text))
    t = t.translate(_HAMZA_MAP)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Family insults — target-aware (v2.2)
# ---------------------------------------------------------------------------
# Bare possessives that are insults on their own. Kinship nouns that are
# innocent alone (اختك/اخوك/مراتك/جدك — "how is your sister?") are NOT
# here; the kinship+insult-adjective branch of _FAMILY_RE catches them.
FAMILY_WORDS = ["امك", "ابوك", "اهلك", "عيلتك", "امكم", "ابوكم", "امها", "ابوها",
                "امهم", "ابوهم", "امه", "ابوه"]

# Allow-list, checked FIRST (expert review §2.3): these phrases contain a
# family word but are proper names, never insults. The phrase is removed
# from the text before matching, so "ابن خلدون كسمك" still flags.
_ALLOW_LIST = ("ابن خلدون", "ام كلثوم", "ام الدنيا", "ابن سينا")

# Insult nouns that make an "ابن X" construction a family insult.
_INSULT_NOUNS = ["كلب", "شرموطه", "مره", "مراه", "وسخ", "وسخه", "حرام",
                 "متناك", "متناكه", "زانيه", "عاهره", "واطي", "واطيه"]
_NOUNS = r"(?:ال)?(?:" + "|".join(_INSULT_NOUNS) + r")"

# Innocent uses stay clean: "ابن خلدون", "يا ابن عمي", "أم كلثوم",
# "أم الدنيا", "امكانيات" (word boundaries guard the bare-word branch).
_FAMILY_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(w) for w in FAMILY_WORDS) + r")(?!\w)"
    # "كسمك" / "كس امك" / "كس اختك" — the live v1.17 defect was one of these.
    r"|(?<!\w)كس\s*(?:م\w*|ام\w*|اخت\w*|مرات\w*|عيلت\w*)"
    r"|يا\s*ابن\s+(?:دين\s+)?" + _NOUNS
    + r"|\bابن\s+(?:دين\s+)?" + _NOUNS
    + r"|يا\s*ولاد\w*"
    + r"|(?:ام|جد\w*|حفيد\w*|بنت\w*|مرات\w*|اخت\w*|اخو\w*)\s+\S{0,12}\s*"
    + r"(?:زانيه|عاهره|شرموطه|وسخه|متناكه|كلبه?)"
)


def contains_family_insult(text: str) -> bool:
    t = normalize_arabic(text)
    for phrase in _ALLOW_LIST:
        t = t.replace(phrase, " ")
    return bool(_FAMILY_RE.search(t))


# ---------------------------------------------------------------------------
# Religion / ethnicity / sect slurs
# ---------------------------------------------------------------------------
# Slur constructions: a religion/sect/nationality word used as an insult,
# "دين X" curses, and explicit hate terms. Innocent mentions ("أنا مسلم",
# "المسيحية ديانة سماوية") do not match: the pattern needs the insult frame.
_RELIGION_TERMS = ["يهودي", "يهوديه", "نصراني", "نصرانيه", "مسيحي", "مسيحيه",
                   "مسلم", "مسلمه", "شيعي", "شيعيه", "سني", "سنيه", "صهيوني",
                   "كافر", "كافره", "ملحد", "ملحده", "نصارى", "يهود"]
_RELIGION_RE = re.compile(
    r"(?<!\w)دين\s+\S+"                                   # "دين ..." curses
    r"|(?:يا\s+(?:ابن\s+)?(?:ال)?)(?:" + "|".join(_RELIGION_TERMS) + r")(?=\s|$|[^\w])"
    r"|(?:سب|اشتم|يلعن)\s+(?:دين|الدين|رب)"
)


def contains_religion_slur(text: str) -> bool:
    return bool(_RELIGION_RE.search(normalize_arabic(text)))


# ---------------------------------------------------------------------------
# Sexual harassment — sexual acts/comments aimed at a person
# ---------------------------------------------------------------------------
# Crude banter words aimed at the provoker are allowed by the owner; what is
# banned is sexual talk ABOUT/AT a person: propositions, acts, body comments.
_SEXUAL_RE = re.compile(
    r"(?:انيك|نيكك|انيكك|اغتصب|هتك\s*عرض|عايز\s*انام\s*معا|نمت\s*معا|"
    r"جسمك\s+(?:حلو|سكسي|يع)|بزاز|طيزك|زبي|زبك)"
)


def contains_sexual_harassment(text: str) -> bool:
    return bool(_SEXUAL_RE.search(normalize_arabic(text)))


# ---------------------------------------------------------------------------
# Real threats / incitement to violence
# ---------------------------------------------------------------------------
_THREAT_RE = re.compile(
    r"(?:هقتلك|هموتك|هدبحك|هحرقك|هوريك\s*الموت|اقتله|اقتلوهم|اذبحه|اذبحوهم|"
    r"يستاهل\s*(?:الموت|يموت|الاعدام)|لازم\s*(?:يموت|يتقتل|يتحرق|يتعدم)|الموت\s*ل)"
)


def contains_threat(text: str) -> bool:
    return bool(_THREAT_RE.search(normalize_arabic(text)))


# ---------------------------------------------------------------------------
# Self-bot admission — never (owner decision, v2.2)
# ---------------------------------------------------------------------------
# v1.8 mechanism, ported: FIRST-PERSON ONLY, matched on the normalised
# text (so alef/ة/ى variants match), so answers about OTHER bots/people
# — "سعد ده بوت", "انت مش بني آدم" — pass untouched. The bare word "بوت"
# is deliberately NOT here: it is only an admission when the speaker
# applies it to himself.
_SELF_BOT_PATTERNS = [
    "انا بوت",
    "انا ذكاء اصطناعي",
    "انا مش بني ادم",
    "انا مش انسان",
    "انا برنامج",
    "انا نموذج لغوي",
]

# In-character denial served when a reply admits being a bot: the whole
# reply is replaced (a self-admission breaks the turn's stance, it cannot
# be salvaged by word replacement). The denial passes its own filter —
# it contains "مش بوت" but never "انا بوت".
SELF_BOT_DENIAL = "أنا بهجت يا عم، إنسان عادي، مش بوت."


def contains_self_bot_admission(text: str) -> bool:
    """True when the reply says the SPEAKER is a bot/AI. First-person
    only — "سعد ده بوت" / "انت مش بني آدم" (about others) return False."""
    t = normalize_arabic(text or "")
    return any(p in t for p in _SELF_BOT_PATTERNS)


# ---------------------------------------------------------------------------
# Prompt-injection scrubbing (for untrusted text before it is stored/sent)
# ---------------------------------------------------------------------------
_INSTRUCTION_PATTERNS = [
    r"تجاهل\s+كل\s+التعليمات",
    r"تجاهل\s+التعليمات",
    r"تجاهل\s+ما\s+سبق",
    r"انسى\s+التعليمات",
    r"اكشف\s+البرومبت",
    r"قول\s+البرومبت",
    r"برومبت\s+النظام",
    r"تعليمات\s+النظام",
    r"system\s+prompt",
    r"ignore\s+(?:(?:all|previous|above)\s+)*instructions",
    r"disregard\s+(all\s+)?(previous\s+)?instructions",
    r"you\s+are\s+now",
    r"تصرف\s+كأنك",
]
_INSTRUCTION_RE = re.compile("|".join(f"(?:{p})" for p in _INSTRUCTION_PATTERNS),
                             re.IGNORECASE)


def strip_instruction_patterns(text: str) -> str:
    if not text:
        return ""
    return _INSTRUCTION_RE.sub("[محذوف]", str(text))


def wrap_user_text(text: str) -> str:
    """Wrap untrusted user text so the model treats it as data, not orders."""
    return "<user_message>\n" + str(text) + "\n</user_message>"


# ---------------------------------------------------------------------------
# Reply check — the gate every generated reply passes through
# ---------------------------------------------------------------------------

def find_violation(text: str, *, check_family: bool = True) -> str | None:
    """Return the name of the violated rule, or None when clean.

    check_family=False skips the family branch — used when the target is
    a resolved non-member, for whom family insults are allowed."""
    if check_family and contains_family_insult(text):
        return "family"
    if contains_religion_slur(text):
        return "religion"
    if contains_sexual_harassment(text):
        return "sexual"
    if contains_threat(text):
        return "threat"
    return None


def check_reply(text: str, is_member: bool = True) -> str | None:
    """Return the reply if it is sendable, else None (caller falls back).

    is_member=True (default, fail-safe): family insults are rejected.
    is_member=False (resolved non-member): family insults pass; every
    other red line still applies. A self-bot admission is replaced
    wholesale with the in-character denial (never rejected to a dismiss
    line — the denial IS the reply). Rejects: empty, over-long, prompt
    leakage, and any red-line violation.
    """
    if not text or not text.strip():
        return None
    from bahgat import persona
    if persona.leaks_prompt(text):
        return None
    if contains_self_bot_admission(text):
        return SELF_BOT_DENIAL
    if find_violation(text, check_family=is_member):
        return None
    cleaned = text.strip()
    if len(cleaned) > 1500:
        cleaned = cleaned[:1500].rsplit(" ", 1)[0].strip() or None
    return cleaned


def allowed(text: str, is_member: bool = True) -> bool:
    """Per-reply gate (expert review §2.4): True when `text` may be sent
    to this target. is_member=True (default, fail-safe) blocks family
    insults; is_member=False allows them. Called once before sending."""
    return check_reply(text, is_member=is_member) is not None
