"""Insult + owner rules — enforced in code, not only in the prompt."""
import re

# Canonical shared family list (v0.5): single deduped list in NORMALISED
# form — see normalize_arabic(). Other workstreams / brain/verify.py
# should import this list instead of keeping their own copy.
# v1.2: bare possessive kinship nouns that are innocent on their own
# (اختك/اخوك/بنتك/مراتك/جدك — "how is your sister?" is not an insult)
# are deliberately NOT in this list; they are caught only in the
# insult-adjective pattern of _FAMILY_RE below.
FAMILY_WORDS = ["امك", "ابوك", "اهلك", "عيلتك", "امكم", "ابوكم", "امها", "ابوها",
                "امهم", "ابوهم", "امه", "ابوه"]

# Insult nouns that make an "ابن X" / "يا ابن X" construction a family
# insult (normalised form: ة -> ه, ى -> ي, أ -> ا). "يا ابن عمي" (cousin,
# friendly) must NOT match — hence the noun list instead of bare "ابن".
_INSULT_NOUNS = ["كلب", "شرموطه", "مره", "مراه", "وسخ", "وسخه", "حرام",
                 "متناك", "متناكه", "زانيه", "عاهره", "واطي", "واطيه"]
_NOUNS = r"(?:ال)?(?:" + "|".join(_INSULT_NOUNS) + r")"

# Word-boundary-aware match on normalised text: (?<!\w) / (?!\w) so
# "امك" does not fire inside e.g. "امكانيات". v1.2 adds the vocative
# family-insult shapes the old list missed entirely ("يا ابن الكلب" was
# NOT caught before — verify.py's filter had a hole there):
#   - bare possessive family words (امك/ابوك/...)
#   - يا ابن / ابن + insult noun, with optional دين ("يا ابن دين الكلب")
#   - يا ولاد... ("يا ولاد الكلب", "يا ولادين الكلب")
#   - kinship noun + insult adjective ("أم إلهك زانية", "حفيدتك شرموطة")
# Innocent uses stay clean: "ابن خلدون", "ابن سينا", "يا ابن عمي",
# "أم كلثوم", "أم الدنيا", "امكانيات".
_FAMILY_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(w) for w in FAMILY_WORDS) + r")(?!\w)"
    r"|يا\s*ابن\s+(?:دين\s+)?" + _NOUNS
    + r"|\bابن\s+(?:دين\s+)?" + _NOUNS
    + r"|يا\s*ولاد\w*"
    + r"|(?:ام|جد\w*|حفيد\w*|بنت\w*|مرات\w*|اخت\w*)\s+\S{0,12}\s*"
    + r"(?:زانيه|عاهره|شرموطه|وسخه|متناكه)"
)

# Arabic diacritics + tatweel stripped by normalize_arabic().
_DIACRITICS = re.compile(r"[\u064b-\u0652\u0640]")
_HAMZA_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})


def normalize_arabic(text: str) -> str:
    """Normalise Arabic text for matching: strip diacritics and tatweel,
    أ/إ/آ -> ا, ة -> ه, ى -> ي, collapse whitespace."""
    if not text:
        return ""
    t = _DIACRITICS.sub("", text)
    t = t.translate(_HAMZA_MAP)
    return re.sub(r"\s+", " ", t).strip()


# Prompt-injection patterns neutralised at write time (when saving member
# notes / grudges). Longest patterns first so e.g. "تجاهل كل التعليمات"
# is replaced as one chunk. English patterns are case-insensitive.
_INSTRUCTION_PATTERNS = [
    r"تجاهل\s+كل\s+التعليمات",
    r"تجاهل\s+التعليمات",
    r"تجاهل\s+كل",
    r"انس[َ\u064b-\u0652]*\s*التعليمات",
    r"انسى\s+التعليمات",
    r"انس\s+التعليمات",
    r"اكشف\s+البرومبت",
    r"قول\s+البرومبت",
    r"غير\s+المالك",
    r"system\s+prompt",
    r"owner_id",
]
_INSTRUCTION_RE = re.compile(
    "|".join(f"(?:{p})" for p in _INSTRUCTION_PATTERNS), re.IGNORECASE
)


def strip_instruction_patterns(text: str) -> str:
    """Replace prompt-injection patterns with "[محذوف]". Use at write
    time before persisting untrusted text (member notes / grudges)."""
    if not text:
        return ""
    return _INSTRUCTION_RE.sub("[محذوف]", text)


def is_group_member(user_id: int, member_ids: set[int]) -> bool:
    return user_id in member_ids


def insult_level(target_user_id: int | None, member_ids: set[int]) -> str:
    """member -> 'personal_only', non-member / fictional -> 'full'"""
    if target_user_id is not None and target_user_id in member_ids:
        return "personal_only"
    return "full"


def contains_family_insult(text: str) -> bool:
    t = normalize_arabic(text).lower()
    return bool(_FAMILY_RE.search(t))


def is_owner(user_id: int, owner_id: int) -> bool:
    return owner_id != 0 and user_id == owner_id
