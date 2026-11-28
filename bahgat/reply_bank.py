"""Reply bank — the curated line file persona/reply_bank.yaml, loaded once
and served with a per-chat no-repeat window.

v2.2 serving filter (owner rules, enforced in code — target-aware):
- confidence "approximate" lines are never served.
- Lines with member_safe: false (family insults) serve ONLY when the
  target is a resolved non-member (is_member=False); at a member or an
  unknown target they are excluded. Default is member-safe.
- Any line that trips a red line in bahgat/rules.py is never served
  (family checked per the target, as above).
- A line tagged `target:` serves ONLY for a roast of that subject
  (specific tier first, generic lines as fallback); with no target given,
  tagged lines never serve — a Sisi line must never land on someone else.
- Lines tagged `dare: true` never serve as a roast (a dare is not an
  insult of the target).
- Gender/number gates (v1.13, ported): a generic line tagged `gender: f`
  serves only a feminine-marked request, `number: p` only a plural one.
  Target-specific lines are exempt — their authoring already matched
  them to their subject.
"""
import random
from pathlib import Path

import yaml

from bahgat import db, rules

_BANK_PATH = Path(__file__).resolve().parents[1] / "persona" / "reply_bank.yaml"

_CATEGORIES = (
    "catchphrase", "challenge", "condolence", "dismiss", "greeting",
    "insulted", "joke_request", "opinion_asked", "roast", "search_fetch",
    "thanks",
)

# Normalised aliases for target-specific roast subjects (v1.3, ported).
# Substring matching already covers "سيسي" and "عبد الفتاح السيسي"; the
# alias map covers spellings that share no substring with the subject.
# Deliberately NOT aliased: bare "عبد" — "اشتم عبد الله" would serve
# Sisi lines for unrelated عبد-prefixed names.
_TARGET_ALIASES = {
    "السيسي": {"بلحه", "بلحة"},
    "كيسنجر": {"كسينجر"},
}

# v1.12 (owner decision): Messi is Bahgat's GOAT — a roast request for
# Messi must NEVER pick a bank line. It falls through to the plain LLM
# turn, where the persona defends him instead.
_MESSI_TARGETS = frozenset({"ميسي", "messi", "ليونيل"})

_bank_cache: dict[bool, dict] = {}


def is_servable(entry: dict, is_member: bool = True) -> bool:
    """One entry's eligibility under the v2.2 rules.

    is_member=True (default, fail-safe): family-insult lines are out.
    is_member=False (resolved non-member): they are eligible."""
    if entry.get("confidence") == "approximate":
        return False
    if entry.get("member_safe") is False and is_member:
        return False
    line = str(entry.get("line") or "").strip()
    if not line:
        return False
    if rules.find_violation(line, check_family=is_member):
        return False
    return True


def load_bank(path=None) -> dict:
    """Load the YAML into {category: [entry, ...]}, unfiltered. Use
    servable_bank() for the filtered serving view."""
    p = Path(path) if path else _BANK_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = {}
    for entry in raw.get("entries") or []:
        cat = entry.get("trigger")
        if cat in _CATEGORIES:
            out.setdefault(cat, []).append(entry)
    return out


def servable_bank(path=None, is_member: bool = True) -> dict:
    """{category: [entry, ...]} with only servable lines for this target."""
    return {cat: [e for e in entries if is_servable(e, is_member=is_member)]
            for cat, entries in load_bank(path).items()}


def _bank(is_member: bool = True) -> dict:
    if is_member not in _bank_cache:
        _bank_cache[is_member] = servable_bank(is_member=is_member)
    return _bank_cache[is_member]


def reload_bank() -> None:
    _bank_cache.clear()


def categories() -> tuple:
    return _CATEGORIES


def _target_matches(line_target, roast_target: str | None) -> bool:
    """True when a bank line may serve for this roast target. A line
    with no `target:` field is generic and fits any target; a tagged
    line fits only when the target names its subject (normalised
    substring match either way, plus the alias map). `line_target`
    may be a single subject string or a list of them."""
    if line_target is None:
        return True
    rt = rules.normalize_arabic(roast_target or "")
    if not rt:
        return False
    subjects = (
        line_target if isinstance(line_target, (list, tuple)) else [line_target]
    )
    for subject in subjects:
        s = rules.normalize_arabic(str(subject))
        if not s:
            continue
        if s in rt or rt in s:
            return True
        if rt in {rules.normalize_arabic(a) for a in _TARGET_ALIASES.get(s, ())}:
            return True
    return False


def is_messi_target(roast_target: str | None) -> bool:
    """True when the roast target is Messi (any spelling)."""
    rt = rules.normalize_arabic(roast_target or "")
    return rt in _MESSI_TARGETS


def _is_gated(entry: dict, target_gender: str | None,
              target_number: str | None) -> bool:
    """True when a GENERIC line is excluded by the gender/number gates.
    Target-specific lines are exempt. None means unmarked ->
    masculine/singular default."""
    if entry.get("target"):
        return False
    if entry.get("gender") == "f" and target_gender != "f":
        return True
    if entry.get("number") == "p" and target_number != "plural":
        return True
    return False


def _pick_from_tier(entries: list, chat_id: int,
                    rng: random.Random) -> dict | None:
    """One tier of the pick: prefer lines outside the recent window,
    fall back to the whole tier rather than silence."""
    if not entries:
        return None
    recent = db.recent_line_ids(chat_id) if chat_id else set()
    fresh = [e for e in entries if e.get("id") not in recent]
    pool = fresh or entries
    choice = rng.choice(pool)
    if chat_id and choice.get("id"):
        db.record_line(chat_id, choice["id"])
    return choice


def pick(category: str, chat_id: int = 0, is_member: bool = True,
         target: str | None = None, target_gender: str | None = None,
         target_number: str | None = None,
         rng: random.Random | None = None) -> dict | None:
    """Pick a servable line in `category`, avoiding the chat's recent
    window. Returns the entry dict (with id/line) or None.

    is_member=True (default, fail-safe) excludes family-insult lines;
    is_member=False (resolved non-member) includes them. target (roast
    only): specific lines for that subject first, generic lines on
    exhaustion; with no target, tagged lines never serve."""
    entries = _bank(is_member).get(category) or []
    if category == "roast":
        entries = [e for e in entries if not e.get("dare")]
    entries = [e for e in entries
               if not _is_gated(e, target_gender, target_number)]
    r = rng or random
    if target is not None:
        entries = [e for e in entries if _target_matches(e.get("target"), target)]
        specific = [e for e in entries if e.get("target")]
        generic = [e for e in entries if not e.get("target")]
        for tier in (specific, generic):
            choice = _pick_from_tier(tier, chat_id, r)
            if choice is not None:
                return choice
        return None
    entries = [e for e in entries if not e.get("target")]
    return _pick_from_tier(entries, chat_id, r)


def pick_line(category: str, chat_id: int = 0, is_member: bool = True,
              target: str | None = None, target_gender: str | None = None,
              target_number: str | None = None,
              rng: random.Random | None = None) -> str | None:
    entry = pick(category, chat_id, is_member=is_member, target=target,
                 target_gender=target_gender, target_number=target_number,
                 rng=rng)
    return entry.get("line") if entry else None


# Fixed safe fallbacks for when the bank has nothing in a category (or the
# DB is unavailable): short, person-only, rule-clean.
FALLBACKS = {
    "insulted": "انت اللي قليل الأدب يا عم، روح اتربى وبعدين تعالى.",
    "roast": "يا عم انت نكتة لوحدك، مش محتاج حد يعملك حاجة.",
    "dismiss": "يا عم خلاص، كلامك ده مش داخل دماغي.",
    "search_fetch": "ثانية واحدة، بسأل وارجع لك.",
    "media_fail": "يوتيوب واقف معايا النهارده، خد اللينك واسمعه بنفسك.",
    "thanks": "العفو يا عم، ده واجبي.",
    "greeting": "أهلاً وسهلاً.",
    "error": "حاجة علت عندي، جرب تاني كده.",
}


def fallback_line(kind: str) -> str:
    return FALLBACKS.get(kind, FALLBACKS["error"])
