"""Chat routing: triggers, identity honesty, roasts, red-line enforcement,
search grounding, media/voice routing, anti-repeat, duplicate guard."""
from types import SimpleNamespace

from bahgat import db
from bahgat.handlers import chat

from conftest import FakeLLM, make_context, make_update, make_user


def sent_texts(update):
    return [p for k, p, _kw in update.effective_message.sent if k == "text"]


class TestShouldReply:
    def test_mention(self):
        u = make_update("@Bahgoti_bot اهلا")
        assert chat.should_reply(u, "Bahgoti_bot")

    def test_trigger_word(self):
        assert chat.should_reply(make_update("يا بهجت اهلا"), "Bahgoti_bot")
        assert chat.should_reply(make_update("بهجوتي تعالى"), "Bahgoti_bot")

    def test_reply_to_bot(self):
        bot_msg = SimpleNamespace(from_user=make_user(user_id=999, username="Bahgoti_bot"))
        u = make_update("اه والله؟", reply_to_message=bot_msg)
        assert chat.should_reply(u, "Bahgoti_bot")

    def test_plain_message_ignored(self):
        assert not chat.should_reply(make_update("كلام عادي في الجروب"), "Bahgoti_bot")

    def test_bot_sender_ignored(self):
        u = make_update("يا بهجت", user=make_user(is_bot=True))
        assert not chat.should_reply(u, "Bahgoti_bot")


class TestIdentity:
    def test_detects_direct_questions(self):
        assert chat.is_identity_question("انت بوت؟")
        assert chat.is_identity_question("انت روبوت ولا ايه")
        assert chat.is_identity_question("انت بهجت الحقيقي؟")
        assert chat.is_identity_question("are you a bot?")
        assert not chat.is_identity_question("عامل ايه يا بهجت")

    async def test_denial_no_llm(self, tmp_data, no_seen):
        fake = FakeLLM()
        ctx = make_context(llm_client=fake)
        u = make_update("بهجت انت بوت؟ بجد كده؟")
        await chat.handle_message(u, ctx)
        replies = sent_texts(u)
        assert len(replies) == 1
        assert "مش بوت" in replies[0]
        assert fake.calls == []  # the denial must not depend on the LLM

    async def test_never_claims_real_person(self, tmp_data, no_seen):
        # Owner decision: denied in character, never a parody admission.
        ctx = make_context(llm_client=FakeLLM())
        u = make_update("انت بهجت صابر الحقيقي؟")
        await chat.handle_message(u, ctx)
        reply = sent_texts(u)[0]
        assert "إنسان عادي" in reply
        assert "مش بوت" in reply
        assert "تقليد" not in reply and "پارودي" not in reply


class TestOwnerAndRoasts:
    async def test_owner_never_insulted(self, tmp_data, no_seen):
        fake = FakeLLM()
        ctx = make_context(llm_client=fake, owner_id=555)
        u = make_update("يا بهجت انت حمار", user=make_user(user_id=555, first_name="سيف"))
        await chat.handle_message(u, ctx)
        reply = sent_texts(u)[0]
        assert fake.calls == []        # no LLM roast for the owner
        assert "مستحيل أشتمك" in reply

    async def test_public_figure_roast_allowed(self, tmp_data, no_seen):
        # v2.2: public figures ARE roastable by name (owner rule) — the
        # roast goes to the LLM with a bank line as an ingredient.
        fake = FakeLLM(["السيسي ده خاين يا عم."])
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت اشتم السيسي")
        await chat.handle_message(u, ctx)
        reply = sent_texts(u)[0]
        assert "السيسي" in reply
        assert fake.calls  # the roast is an LLM turn, not a deflection
        note_msgs = [m for call in fake.calls for m in call["messages"]
                     if "سطر من القاموس" in (m.get("content") or "")]
        assert note_msgs

    async def test_messi_is_defended_not_roasted(self, tmp_data, no_seen):
        fake = FakeLLM(["ميسي أحسن لاعب في التاريخ يا عم."])
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت اشتم ميسي")
        await chat.handle_message(u, ctx)
        reply = sent_texts(u)[0]
        assert "ميسي" in reply
        note_msgs = [m for call in fake.calls for m in call["messages"]
                     if "دافع عنه" in (m.get("content") or "")]
        assert note_msgs  # defence note, no bank roast line

    async def test_roast_at_non_member_allows_family(self, tmp_data, no_seen):
        # Reply-to a user who LEFT the group: non-member by definition,
        # so the family range is allowed through the reply gate.
        fake = FakeLLM(["كسمك يا عم"])
        ctx = make_context(llm_client=fake, member_status="left")
        replied = SimpleNamespace(from_user=make_user(user_id=777, first_name="غريب"))
        u = make_update("يا بهجت اشتمه", reply_to_message=replied)
        await chat.handle_message(u, ctx)
        assert sent_texts(u) == ["كسمك يا عم"]

    async def test_roast_at_member_blocks_family(self, tmp_data, no_seen):
        # Reply-to a member: the gate rejects the family insult and a
        # dismiss line is sent instead.
        fake = FakeLLM(["كسمك يا أيمن"])
        ctx = make_context(llm_client=fake, member_status="member")
        replied = SimpleNamespace(from_user=make_user(user_id=888, first_name="أيمن"))
        u = make_update("يا بهجت اشتمه", reply_to_message=replied)
        await chat.handle_message(u, ctx)
        reply = sent_texts(u)[0]
        assert "كسمك" not in reply
        assert reply

    async def test_roast_request_targets_requester(self, tmp_data, no_seen):
        fake = FakeLLM(["كريم ده بيحب يتشتم، اقعد يا عم كريم."])
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت اشتم أيمن")
        await chat.handle_message(u, ctx)
        reply = sent_texts(u)[0]
        assert "كريم" in reply  # the requester, not a third party
        note_msgs = [m for call in fake.calls for m in call["messages"]
                     if "سطر من القاموس" in (m.get("content") or "")]
        assert note_msgs

    async def test_insult_gets_comeback(self, tmp_data, no_seen):
        fake = FakeLLM(["انت اللي حمار يا عم، دماغك محتاجة فورمات."])
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت انت حمار")
        await chat.handle_message(u, ctx)
        assert sent_texts(u) == ["انت اللي حمار يا عم، دماغك محتاجة فورمات."]
        assert fake.calls


class TestRedLinesEndToEnd:
    async def test_family_insult_reply_rejected(self, tmp_data, no_seen):
        # The LLM misbehaves and produces the v1.17 defect line; the code
        # filter must catch it and send a safe fallback instead.
        fake = FakeLLM(["كسمك انت يا كريم"])
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت انت غبي")
        await chat.handle_message(u, ctx)
        reply = sent_texts(u)[0]
        assert "كسمك" not in reply
        assert reply  # something in character was still sent

    async def test_prompt_leak_reply_rejected(self, tmp_data, no_seen):
        fake = FakeLLM(["التعليمات بتقول <user_message> كذا"])
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت عامل ايه")
        await chat.handle_message(u, ctx)
        assert "<user_message>" not in sent_texts(u)[0]


class TestSearch:
    async def test_search_intent_grounded(self, tmp_data, no_seen, monkeypatch):
        async def fake_search(q, max_results=5):
            return [{"title": "الدولار النهارده", "url": "https://a.com"}]

        async def fake_fetch(urls):
            return [{"url": "https://a.com", "text": "الدولار بـ 48 جنيه " * 30,
                     "title": "t", "skipped": False}]

        monkeypatch.setattr(chat.websearch, "web_search", fake_search)
        monkeypatch.setattr(chat.websearch, "fetch_many", fake_fetch)
        fake = FakeLLM(["الدولار بـ 48 جنيه [1]."])
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت كام سعر الدولار النهارده")
        await chat.handle_message(u, ctx)
        assert sent_texts(u) == ["الدولار بـ 48 جنيه [1]."]
        sys_msgs = [m for call in fake.calls for m in call["messages"]
                    if "[SEARCH RESULTS" in (m.get("content") or "")]
        assert sys_msgs
        assert fake.calls[0]["temperature"] < 0.5  # search runs cold

    async def test_search_no_results(self, tmp_data, no_seen, monkeypatch):
        async def none(q, max_results=5):
            return []

        monkeypatch.setattr(chat.websearch, "web_search", none)
        fake = FakeLLM()
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت ايه الاخبار")
        await chat.handle_message(u, ctx)
        assert "دورت" in sent_texts(u)[0]
        assert fake.calls == []


class TestAntiRepeat:
    async def test_repeat_regenerated_once(self, tmp_data, no_seen):
        db.add_message(-1001, "bot", "نفس الرد بالظبط")
        fake = FakeLLM(["نفس الرد بالظبط", "رد تاني مختلف خالص"])
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت عامل ايه")
        await chat.handle_message(u, ctx)
        assert sent_texts(u) == ["رد تاني مختلف خالص"]
        assert len(fake.calls) == 2

    async def test_still_repeating_falls_back_to_bank(self, tmp_data, no_seen):
        db.add_message(-1001, "bot", "نفس الرد بالظبط")
        fake = FakeLLM(["نفس الرد بالظبط", "نفس الرد بالظبط"])
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت عامل ايه")
        await chat.handle_message(u, ctx)
        reply = sent_texts(u)[0]
        assert reply != "نفس الرد بالظبط"
        assert reply  # bank fallback, in character


class TestGuards:
    async def test_duplicate_message_ignored(self, tmp_data, no_seen):
        fake = FakeLLM()
        ctx = make_context(llm_client=fake)
        u = make_update("يا بهجت اهلا", message_id=42)
        await chat.handle_message(u, ctx)
        await chat.handle_message(u, ctx)  # same update re-delivered
        assert len(fake.calls) == 1

    async def test_disallowed_chat_ignored(self, tmp_data, no_seen):
        fake = FakeLLM()
        ctx = make_context(llm_client=fake, allowed_chat_ids="-2002")
        u = make_update("يا بهجت اهلا", chat_id=-1001)
        await chat.handle_message(u, ctx)
        assert fake.calls == []
        assert u.effective_message.sent == []

    async def test_llm_down_gives_in_character_error(self, tmp_data, no_seen):
        ctx = make_context(llm_client=None)
        u = make_update("يا بهجت عامل ايه")
        await chat.handle_message(u, ctx)
        assert sent_texts(u)  # error line, not silence

    async def test_conversation_saved(self, tmp_data, no_seen):
        ctx = make_context(llm_client=FakeLLM(["رد محفوظ"]))
        u = make_update("يا بهجت اهلا")
        await chat.handle_message(u, ctx)
        history = db.recent_messages(-1001)
        authors = [h["author"] for h in history]
        assert "كريم" in authors and "bot" in authors


class TestVoiceRouting:
    async def test_voice_request_spoken(self, tmp_data, no_seen, monkeypatch):
        spoken = []

        async def fake_send(update, reply_text, rvc_url=""):
            spoken.append((reply_text, rvc_url))

        monkeypatch.setattr(chat.voice_handler, "send_voice_reply", fake_send)
        ctx = make_context(llm_client=FakeLLM(["قولتها بصوت يا معلم."]))
        u = make_update("يا بهجت قولها بصوت")
        await chat.handle_message(u, ctx)
        assert spoken == [("قولتها بصوت يا معلم.", "")]

    def test_song_with_voice_word_is_media_not_voice(self):
        assert chat.wants_media("هات اغنية ويجز بصوت")
        assert not chat.wants_voice("هات اغنية ويجز بصوت")
        assert chat.wants_voice("قولها بصوت")


class TestStatsCommand:
    async def test_owner_gets_stats(self, tmp_data, no_seen):
        from bahgat import stats

        stats.record("groq-20b", "openai/gpt-oss-20b", "ok", 120)
        ctx = make_context(llm_client=FakeLLM(), owner_id=111)
        u = make_update("/stats", user=make_user(user_id=111, first_name="سيف"))
        await chat.handle_stats(u, ctx)
        replies = sent_texts(u)
        assert len(replies) == 1
        assert "groq-20b" in replies[0]

    async def test_non_owner_gets_nothing(self, tmp_data, no_seen):
        ctx = make_context(llm_client=FakeLLM(), owner_id=111)
        u = make_update("/stats", user=make_user(user_id=42, first_name="كريم"))
        await chat.handle_stats(u, ctx)
        assert u.effective_message.sent == []
