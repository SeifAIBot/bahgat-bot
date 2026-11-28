"""Resolve who an insult/roast is aimed at, and whether they are a member.

Expert review §2.1–2.2: resolve in this precedence, because each source
has a different reliability:
  1. message.reply_to_message.from_user — most reliable (full User object).
  2. MessageEntity.TEXT_MENTION — the entity carries the .user id.
  3. MessageEntity.MENTION (@username) — NOT resolvable by the Bot API;
     resolved only through the in-memory username cache built from users
     the bot has seen in the group. Unknown @username = unknown target.
  4. Default: the sender.

Membership (getChatMember): creator/administrator/member/restricted are
members; left/kicked are non-members; any exception or unknown status is
treated as a MEMBER (fail-safe). Family insults are served only when the
target is positively a non-member. getChatMember is only reliable when
the bot is an admin — it is an admin in the groups it serves. Results
are cached for 5 minutes per (chat_id, user_id).
"""
import logging
import time

logger = logging.getLogger(__name__)

_MEMBER_TTL_SECONDS = 300

# (chat_id, username_lower) -> user_id, built from users the bot sees.
_USERNAME_CACHE: dict[tuple[int, str], int] = {}
# (chat_id, user_id) -> (is_member, expires_at)
_MEMBER_CACHE: dict[tuple[int, int], tuple[bool, float]] = {}

_MEMBER_STATUSES = frozenset({"creator", "administrator", "member", "restricted"})
_NON_MEMBER_STATUSES = frozenset({"left", "kicked"})

# Plain-text names are NOT resolvable targets — except when the name
# matches a known public figure (expert review §2.1). A bare first name
# ("اشتم كريم") is treated as a member; a public-figure name is a
# non-member by definition (they are not in the group). This list is a
# membership decision only — it does not ban roasting them (owner rule).
PUBLIC_FIGURE_NAMES = frozenset({
    "السيسي", "سيسي", "السيسى", "صلاح", "محمد صلاح", "ميسي", "رونالدو",
    "مبابي", "ترامب", "بوتين", "نتنياهو", "زيلينسكي", "ميدو",
    "ابو تريكه", "عمرو دياب", "تامر حسني", "ويجز", "ابيوسف",
    "مرسي", "مورسي", "بايدن",
})


def is_public_figure_name(name: str | None) -> bool:
    """True when the name (normalised) matches a known public figure."""
    if not name:
        return False
    from bahgat import rules

    t = rules.normalize_arabic(name)
    return any(f in t or t in f for f in PUBLIC_FIGURE_NAMES)


def remember_user(chat_id: int, user) -> None:
    """Record a seen user for @mention resolution. Never raises."""
    try:
        username = getattr(user, "username", None)
        user_id = getattr(user, "id", None)
        if username and user_id:
            _USERNAME_CACHE[(int(chat_id), str(username).lower())] = int(user_id)
    except (TypeError, ValueError):
        pass


def resolve_target(message, bot_username: str = "") -> tuple[int | None, bool]:
    """Who is this message's insult/roast aimed at?

    Returns (user_id, known): known=False means the target could not be
    resolved (unresolvable @mention, or no target at all) — the caller
    must treat it as a member (fail-safe). The sender is always known.
    """
    msg = message
    replied = getattr(msg, "reply_to_message", None)
    replied_user = getattr(replied, "from_user", None) if replied else None
    if replied_user is not None and getattr(replied_user, "id", None):
        return int(replied_user.id), True

    entities = getattr(msg, "entities", None) or []
    text = getattr(msg, "text", "") or ""
    for entity in entities:
        etype = getattr(entity, "type", None)
        if etype == "text_mention":
            user = getattr(entity, "user", None)
            if user is not None and getattr(user, "id", None):
                return int(user.id), True
        elif etype == "mention":
            offset = getattr(entity, "offset", 0)
            length = getattr(entity, "length", 0)
            name = text[offset:offset + length].lstrip("@").lower()
            if name and name != (bot_username or "").lower():
                cached = _USERNAME_CACHE.get((int(msg.chat_id), name))
                if cached is not None:
                    return cached, True
                return None, False

    sender = getattr(msg, "from_user", None)
    if sender is not None and getattr(sender, "id", None):
        return int(sender.id), True
    return None, False


async def is_member(bot, chat_id: int, user_id: int) -> bool:
    """True when user_id is a member of chat_id. Fail-safe: any doubt
    (lookup failure, unknown status, bot not admin) counts as member."""
    key = (int(chat_id), int(user_id))
    cached = _MEMBER_CACHE.get(key)
    if cached is not None and time.monotonic() < cached[1]:
        return cached[0]
    result = True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        status = str(getattr(member, "status", "")).lower()
        if status in _NON_MEMBER_STATUSES:
            result = False
        elif status in _MEMBER_STATUSES:
            result = True
        else:
            logger.warning("getChatMember returned unknown status %r for "
                           "user %s — treating as member", status, user_id)
            result = True
    except Exception as e:
        logger.warning("getChatMember failed for user %s in chat %s (%s) — "
                       "treating as member", user_id, chat_id, e)
        result = True
    _MEMBER_CACHE[key] = (result, time.monotonic() + _MEMBER_TTL_SECONDS)
    return result


def reset_caches() -> None:
    _USERNAME_CACHE.clear()
    _MEMBER_CACHE.clear()
