"""Target resolution + membership (v2.2): reply > TEXT_MENTION >
@mention-cache > sender; getChatMember with fail-safe unknown=member."""
from types import SimpleNamespace

import pytest

from bahgat import targets
from conftest import make_update, make_user


def _msg(text, user=None, reply_to=None, entities=None):
    u = make_update(text, user=user, reply_to_message=reply_to)
    msg = u.effective_message
    if entities is not None:
        msg.entities = entities
    return msg


class TestResolveTarget:
    def test_reply_to_wins(self):
        replied = SimpleNamespace(from_user=make_user(user_id=777, first_name="أيمن"))
        msg = _msg("اشتمه", reply_to=replied)
        assert targets.resolve_target(msg, "Bahgoti_bot") == (777, True)

    def test_text_mention(self):
        ent = SimpleNamespace(type="text_mention", offset=0, length=5,
                              user=make_user(user_id=77, username="ayman"))
        msg = _msg("اشتم", entities=[ent])
        assert targets.resolve_target(msg, "Bahgoti_bot") == (77, True)

    def test_mention_from_cache(self):
        targets.remember_user(-1001, make_user(user_id=55, username="ayman"))
        ent = SimpleNamespace(type="mention", offset=5, length=6)
        msg = _msg("اشتم @ayman", entities=[ent])
        assert targets.resolve_target(msg, "Bahgoti_bot") == (55, True)

    def test_unknown_mention_unresolved(self):
        # An @mention nobody has seen: unresolvable (None, False) — the
        # caller treats it as a member (fail-safe), it does NOT fall back
        # to the sender.
        ent = SimpleNamespace(type="mention", offset=5, length=7)
        msg = _msg("اشتم @nobody", entities=[ent])
        assert targets.resolve_target(msg, "Bahgoti_bot") == (None, False)

    def test_sender_default(self):
        # No target at all: the sender is always known.
        msg = _msg("اشتم")
        assert targets.resolve_target(msg, "Bahgoti_bot") == (42, True)

    def test_bot_mention_not_a_target(self):
        # @Bahgoti_bot in the text is the trigger, not a roast target.
        ent = SimpleNamespace(type="mention", offset=0, length=12)
        msg = _msg("@Bahgoti_bot اشتم", entities=[ent])
        user_id, known = targets.resolve_target(msg, "Bahgoti_bot")
        assert user_id == 42  # falls back to the sender


class TestIsMember:
    def _bot(self, statuses):
        async def get_chat_member(chat_id, user_id):
            status = statuses.get(user_id, "member")
            if isinstance(status, Exception):
                raise status
            return SimpleNamespace(status=status)

        return SimpleNamespace(get_chat_member=get_chat_member)

    @pytest.mark.parametrize("status", ["creator", "administrator", "member",
                                       "restricted"])
    async def test_member_statuses(self, status):
        bot = self._bot({7: status})
        assert await targets.is_member(bot, -1001, 7) is True

    @pytest.mark.parametrize("status", ["left", "kicked"])
    async def test_non_member_statuses(self, status):
        bot = self._bot({7: status})
        assert await targets.is_member(bot, -1001, 7) is False

    async def test_api_error_is_fail_safe_member(self):
        bot = self._bot({7: RuntimeError("chat not found")})
        assert await targets.is_member(bot, -1001, 7) is True

    async def test_unknown_status_is_fail_safe_member(self):
        bot = self._bot({7: "weird-status"})
        assert await targets.is_member(bot, -1001, 7) is True

    async def test_result_cached(self):
        calls = []

        async def get_chat_member(chat_id, user_id):
            calls.append(user_id)
            return SimpleNamespace(status="member")

        bot = SimpleNamespace(get_chat_member=get_chat_member)
        assert await targets.is_member(bot, -1001, 9) is True
        assert await targets.is_member(bot, -1001, 9) is True
        assert calls == [9]  # second call served from the 5-minute cache


class TestPublicFigureNames:
    def test_known_figures(self):
        assert targets.is_public_figure_name("السيسي")
        assert targets.is_public_figure_name("محمد صلاح")
        assert targets.is_public_figure_name("ميسي")

    def test_members_are_not_figures(self):
        assert not targets.is_public_figure_name("كريم")
        assert not targets.is_public_figure_name("أيمن")
        assert not targets.is_public_figure_name("")
        assert not targets.is_public_figure_name(None)
