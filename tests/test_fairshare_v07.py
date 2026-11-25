"""v0.7 fair-share quota — capacity formula, EWMA tokens/reply, active
set, fair-share math, hysteresis. Replaces the v0.6 fixed caps
(100/user/day, 1500/group/day, owner exempt): the owner now gets a 1.25
weight instead of an exemption, and capacity comes from live provider
budgets (compute_pool_remaining), never a fixed number.
"""
import sqlite3
import time

import pytest

from brain import memory

OWNER_ID = 1415214630
CHAT = 999


def _entry(name, family, cap_req=None, cap_tok=None, used_req=0,
           used_tok=0, disabled=False, exhausted_until=None):
    return {"name": name, "family": family, "model": "m",
            "daily_cap_requests": cap_req, "daily_cap_tokens": cap_tok,
            "requests_used": used_req, "tokens_used": used_tok,
            "disabled": disabled, "exhausted_until": exhausted_until}


def _seed_usage(tmp_db, user_id, chat_id, count):
    c = sqlite3.connect(tmp_db)
    c.execute("INSERT INTO daily_usage(user_id, chat_id, date, count) "
              "VALUES(?, ?, date('now'), ?)", (user_id, chat_id, count))
    c.commit()
    c.close()


def _active_15():
    return [OWNER_ID] + list(range(2, 16))  # owner + 14 members


# --- capacity formula -------------------------------------------------------

def test_capacity_binding_limit_is_min_of_rpd_and_tpd(tmp_db):
    # RPD 100, TPD 105,000 / 1,050 = 100 -> 100 replies, x0.8 = 80.
    entry = _entry("groq-120b", "groq", cap_req=100, cap_tok=105000)
    res = memory.compute_pool_remaining([entry], avg_tokens=1050)
    assert res["pool_replies"] == pytest.approx(80.0)
    assert res["full_pool_replies"] == pytest.approx(80.0)
    assert res["avg_tokens"] == pytest.approx(1050.0)
    assert res["per_entry"][0]["replies_remaining"] == pytest.approx(100.0)
    assert res["per_entry"][0]["requests_left"] == 100
    assert res["per_entry"][0]["tokens_left"] == 105000
    assert res["per_entry"][0]["excluded"] is False
    assert res["per_entry"][0]["disabled"] is False


def test_capacity_tpd_binds_over_rpd(tmp_db):
    # RPD 1000, TPD 10,500 / 1,050 = 10 -> 10 replies, x0.8 = 8.
    entry = _entry("groq-120b", "groq", cap_req=1000, cap_tok=10500)
    res = memory.compute_pool_remaining([entry], avg_tokens=1050)
    assert res["pool_replies"] == pytest.approx(8.0)


def test_capacity_haircut_is_20_percent(tmp_db):
    entry = _entry("flash-lite", "gemini", cap_req=100)
    res = memory.compute_pool_remaining([entry], avg_tokens=1050)
    assert res["pool_replies"] == pytest.approx(80.0)
    assert res["full_pool_replies"] == pytest.approx(80.0)


def test_capacity_dead_provider_zero_but_full_counts_it(tmp_db):
    entry = _entry("cerebras", "cerebras", cap_req=100, disabled=True)
    res = memory.compute_pool_remaining([entry], avg_tokens=1050)
    assert res["pool_replies"] == pytest.approx(0.0)
    assert res["full_pool_replies"] == pytest.approx(80.0)
    assert res["per_entry"][0]["replies_remaining"] == pytest.approx(0.0)
    assert res["per_entry"][0]["disabled"] is True


def test_capacity_exhausted_until_future_vs_past(tmp_db):
    now = time.time()
    future = _entry("g", "groq", cap_req=100, exhausted_until=now + 3600)
    assert memory.compute_pool_remaining(
        [future], avg_tokens=1050)["pool_replies"] == pytest.approx(0.0)
    past = _entry("g", "groq", cap_req=100, exhausted_until=now - 60)
    assert memory.compute_pool_remaining(
        [past], avg_tokens=1050)["pool_replies"] == pytest.approx(80.0)


def test_capacity_nvidia_nim_excluded_from_pool(tmp_db):
    nim = _entry("nvidia-nemotron", "nvidia", cap_req=10000)
    groq = _entry("groq-20b", "groq", cap_req=100)
    res = memory.compute_pool_remaining([nim, groq], avg_tokens=1050)
    assert res["pool_replies"] == pytest.approx(80.0)  # groq only
    assert res["full_pool_replies"] == pytest.approx(80.0)
    nim_row = [e for e in res["per_entry"] if e["name"] == "nvidia-nemotron"][0]
    assert nim_row["excluded"] is True
    assert nim_row["replies_remaining"] == pytest.approx(0.0)


def test_capacity_openrouter_shared_cap_counted_once(tmp_db):
    # Two entries, one account-wide 50 RPD cap; used 10 + 20 = 30.
    a = _entry("or-gemma", "openrouter", cap_req=50, used_req=10)
    b = _entry("or-nemotron", "openrouter", cap_req=50, used_req=20)
    res = memory.compute_pool_remaining([a, b], avg_tokens=1050)
    assert res["pool_replies"] == pytest.approx(16.0)  # (50-30) x 0.8
    assert res["full_pool_replies"] == pytest.approx(40.0)  # 50 x 0.8, once
    assert res["per_entry"][0]["replies_remaining"] == pytest.approx(20.0)
    assert res["per_entry"][1]["replies_remaining"] == pytest.approx(20.0)
    assert res["per_entry"][0]["requests_left"] == 20
    assert res["per_entry"][1]["requests_left"] == 20


def test_capacity_openrouter_smallest_cap_binds(tmp_db):
    # Caps differ (50 vs 1000 after a $10 purchase): smallest binds.
    a = _entry("or-gemma", "openrouter", cap_req=50, used_req=40)
    b = _entry("or-nemotron", "openrouter", cap_req=1000, used_req=0)
    res = memory.compute_pool_remaining([a, b], avg_tokens=1050)
    assert res["pool_replies"] == pytest.approx(8.0)  # (50-40) x 0.8


def test_capacity_empty_entries_fail_closed(tmp_db):
    for entries in ([], None):
        res = memory.compute_pool_remaining(entries, avg_tokens=1050)
        assert res["pool_replies"] == 0.0
        assert res["full_pool_replies"] == 0.0
        assert res["per_entry"] == []


def test_capacity_cold_start_avg_is_1050(tmp_db):
    entry = _entry("groq-120b", "groq", cap_tok=105000)
    res = memory.compute_pool_remaining([entry])
    assert res["avg_tokens"] == pytest.approx(1050.0)
    assert res["pool_replies"] == pytest.approx(80.0)


def test_capacity_avg_comes_from_ewma_table(tmp_db):
    memory.record_reply_tokens("chat", 2100)
    entry = _entry("groq-120b", "groq", cap_tok=105000)
    res = memory.compute_pool_remaining([entry])
    assert res["avg_tokens"] == pytest.approx((30 * 1050 + 2100) / 31)


# --- EWMA tokens/reply ------------------------------------------------------

def test_ewma_update_formula(tmp_db):
    memory.record_reply_tokens("chat", 1000)
    c = sqlite3.connect(tmp_db)
    row = c.execute(
        "SELECT ewma, n, total FROM token_stats WHERE intent='chat'").fetchone()
    c.close()
    assert row == (1000.0, 1, 1000.0)
    memory.record_reply_tokens("chat", 2000)
    c = sqlite3.connect(tmp_db)
    row = c.execute(
        "SELECT ewma, n, total FROM token_stats WHERE intent='chat'").fetchone()
    c.close()
    assert row[0] == pytest.approx(0.15 * 2000 + 0.85 * 1000)  # 1150
    assert row[1] == 2
    assert row[2] == pytest.approx(3000.0)


def test_ewma_unknown_intent_bucketed_as_chat(tmp_db):
    memory.record_reply_tokens("youtube", 500)
    memory.record_reply_tokens("voice", 700)
    c = sqlite3.connect(tmp_db)
    rows = c.execute("SELECT intent, n FROM token_stats").fetchall()
    c.close()
    assert rows == [("chat", 2)]


def test_ewma_ignores_bad_values(tmp_db):
    for bad in (0, -5, "abc", None):
        memory.record_reply_tokens("chat", bad)
    c = sqlite3.connect(tmp_db)
    rows = c.execute("SELECT COUNT(*) FROM token_stats").fetchone()[0]
    c.close()
    assert rows == 0


def test_avg_cold_start_blend(tmp_db):
    assert memory.avg_tokens_per_reply() == pytest.approx(1050.0)
    assert memory.avg_tokens_per_reply("chat") == pytest.approx(1050.0)
    memory.record_reply_tokens("chat", 1000)
    memory.record_reply_tokens("chat", 2000)
    # (30*1050 + 3000) / (30 + 2) = 1078.125
    assert memory.avg_tokens_per_reply("chat") == pytest.approx(1078.125)
    assert memory.avg_tokens_per_reply() == pytest.approx(1078.125)


def test_avg_per_intent_separation(tmp_db):
    memory.record_reply_tokens("chat", 1000)
    memory.record_reply_tokens("search", 2400)
    assert memory.avg_tokens_per_reply("chat") == pytest.approx((31500 + 1000) / 31)
    assert memory.avg_tokens_per_reply("search") == pytest.approx((31500 + 2400) / 31)
    assert memory.avg_tokens_per_reply() == pytest.approx((31500 + 3400) / 32)
    assert memory.avg_tokens_per_reply("chat") != memory.avg_tokens_per_reply("search")


def test_avg_never_below_50(tmp_db):
    c = sqlite3.connect(tmp_db)
    c.execute("INSERT INTO token_stats(intent, ewma, n, total) "
              "VALUES('chat', 1, 1000, 0)")
    c.commit()
    c.close()
    # Raw blend would be 31500/1030 = 30.6 -> clamped to 50.
    assert memory.avg_tokens_per_reply("chat") == 50.0
    assert memory.avg_tokens_per_reply() == 50.0


# --- active set -------------------------------------------------------------

def test_active_users_window_7_days(tmp_db):
    memory.record_trigger(1, 10)
    memory.record_trigger(2, 10)
    assert set(memory.active_users(10)) == {1, 2}
    c = sqlite3.connect(tmp_db)
    c.execute("UPDATE last_triggered SET last_triggered_at=? WHERE user_id=2",
              (time.time() - 8 * 86400,))  # 8 days ago: outside the window
    c.commit()
    c.close()
    assert memory.active_users(10) == [1]
    c = sqlite3.connect(tmp_db)
    c.execute("UPDATE last_triggered SET last_triggered_at=? WHERE user_id=2",
              (time.time() - 6 * 86400,))  # 6 days ago: still active
    c.commit()
    c.close()
    assert set(memory.active_users(10)) == {1, 2}


def test_active_users_returning_user_instantly_active(tmp_db):
    assert memory.active_users(10) == []
    memory.record_trigger(7, 10)
    assert memory.active_users(10) == [7]


def test_active_users_scoped_per_chat(tmp_db):
    memory.record_trigger(1, 10)
    memory.record_trigger(1, 20)
    assert memory.active_users(10) == [1]
    assert memory.active_users(20) == [1]
    assert memory.active_users(30) == []


def test_active_set_empty_treated_as_just_the_user(tmp_db):
    info = memory.fair_share_info(42, CHAT, capacity_replies=100.0,
                                  active_users=[])
    assert info["active_count"] == 1
    assert info["share"] == pytest.approx(100.0)
    assert info["ceiling"] == pytest.approx(200.0)


# --- fair-share math --------------------------------------------------------

def test_fair_share_owner_weight_and_shares_sum_to_c(tmp_db):
    active = [OWNER_ID, 2, 3]
    owner = memory.fair_share_info(OWNER_ID, CHAT, owner_id=OWNER_ID,
                                   capacity_replies=1500.0, active_users=active)
    m1 = memory.fair_share_info(2, CHAT, owner_id=OWNER_ID,
                                capacity_replies=1500.0, active_users=active)
    m2 = memory.fair_share_info(3, CHAT, owner_id=OWNER_ID,
                                capacity_replies=1500.0, active_users=active)
    assert owner["share"] == pytest.approx(1500 * 1.25 / 3.25)  # ~577
    assert m1["share"] == pytest.approx(1500 / 3.25)            # ~462
    assert owner["share"] == pytest.approx(1.25 * m1["share"])
    assert owner["share"] + m1["share"] + m2["share"] == pytest.approx(1500.0)
    assert owner["ceiling"] == pytest.approx(2 * owner["share"])  # ~1154
    assert m1["ceiling"] == pytest.approx(2 * m1["share"])        # ~924


def test_fair_share_15_active_worked_example(tmp_db):
    owner = memory.fair_share_info(OWNER_ID, CHAT, owner_id=OWNER_ID,
                                   capacity_replies=1500.0,
                                   active_users=_active_15())
    member = memory.fair_share_info(2, CHAT, owner_id=OWNER_ID,
                                    capacity_replies=1500.0,
                                    active_users=_active_15())
    assert owner["share"] == pytest.approx(1500 * 1.25 / 15.25)  # ~123
    assert member["share"] == pytest.approx(1500 / 15.25)        # ~98
    assert owner["ceiling"] == pytest.approx(2 * owner["share"])  # ~246
    assert member["ceiling"] == pytest.approx(2 * member["share"])  # ~197


def test_fair_share_floor_20_never_blocks(tmp_db):
    # Member share at C=100 with 15 active is 6.67 — but 19 used is
    # under the floor, so the share check never runs.
    _seed_usage(tmp_db, 2, CHAT, 19)
    allowed, reason = memory.check_and_consume_quota(
        2, CHAT, capacity_replies=100.0,
        active_users=list(range(2, 17)))
    assert allowed is True
    assert reason == "ok"


def test_fair_share_generous_borrow_ceiling_2x(tmp_db):
    # C=1500, 15 active, group used 200 (< 750 = generous): member
    # ceiling is ~197. 150 used -> allowed; 197 used -> denied.
    _seed_usage(tmp_db, 888, CHAT, 50)  # other users' burn
    _seed_usage(tmp_db, 7, CHAT, 150)
    allowed, _ = memory.check_and_consume_quota(
        7, CHAT, owner_id=OWNER_ID, capacity_replies=1500.0,
        active_users=_active_15())
    assert allowed is True


def test_fair_share_generous_ceiling_blocks_at_2x(tmp_db):
    _seed_usage(tmp_db, 888, CHAT, 50)
    _seed_usage(tmp_db, 7, CHAT, 197)
    allowed, reason = memory.check_and_consume_quota(
        7, CHAT, owner_id=OWNER_ID, capacity_replies=1500.0,
        active_users=_active_15())
    assert allowed is False
    assert reason == "fair share reached"


def test_fair_share_strict_at_50_percent_saturation(tmp_db):
    # Group used 750/1500 = exactly 50% -> strict: limit is the share
    # (~98.36). 98 used -> allowed; 99 used -> denied.
    _seed_usage(tmp_db, 888, CHAT, 652)
    _seed_usage(tmp_db, 7, CHAT, 98)
    allowed, _ = memory.check_and_consume_quota(
        7, CHAT, owner_id=OWNER_ID, capacity_replies=1500.0,
        active_users=_active_15())
    assert allowed is True


def test_fair_share_strict_blocks_over_share(tmp_db):
    _seed_usage(tmp_db, 888, CHAT, 651)
    _seed_usage(tmp_db, 7, CHAT, 99)
    allowed, reason = memory.check_and_consume_quota(
        7, CHAT, owner_id=OWNER_ID, capacity_replies=1500.0,
        active_users=_active_15())
    assert allowed is False
    assert reason == "fair share reached"
    # Denied replies do not consume.
    assert memory.get_usage_today()["per_user"][7] == 99


def test_fair_share_group_hard_ceiling(tmp_db):
    _seed_usage(tmp_db, 888, CHAT, 100)
    allowed, reason = memory.check_and_consume_quota(
        5, CHAT, capacity_replies=100.0, active_users=[5])
    assert allowed is False
    assert reason == "group daily limit reached"
    # A different chat is unaffected.
    assert memory.check_and_consume_quota(
        5, CHAT + 1, capacity_replies=100.0, active_users=[5])[0] is True


def test_fair_share_owner_not_exempt(tmp_db):
    # Strict mode (group 750/1500): owner share ~122.95. 123 used ->
    # denied even for the owner; 122 used -> allowed.
    _seed_usage(tmp_db, 888, CHAT, 627)
    _seed_usage(tmp_db, OWNER_ID, CHAT, 123)
    allowed, reason = memory.check_and_consume_quota(
        OWNER_ID, CHAT, owner_id=OWNER_ID, capacity_replies=1500.0,
        active_users=_active_15())
    assert allowed is False
    assert reason == "fair share reached"


def test_fair_share_owner_under_share_allowed(tmp_db):
    _seed_usage(tmp_db, 888, CHAT, 628)
    _seed_usage(tmp_db, OWNER_ID, CHAT, 122)
    allowed, reason = memory.check_and_consume_quota(
        OWNER_ID, CHAT, owner_id=OWNER_ID, capacity_replies=1500.0,
        active_users=_active_15())
    assert allowed is True
    assert reason == "ok"


def test_fair_share_capacity_none_fails_open_but_counts(tmp_db):
    allowed, reason = memory.check_and_consume_quota(2, CHAT)
    assert allowed is True
    assert reason == "ok"
    assert memory.get_usage_today()["per_user"][2] == 1


def test_fair_share_info_does_not_consume(tmp_db):
    _seed_usage(tmp_db, 2, CHAT, 5)
    info1 = memory.fair_share_info(2, CHAT, capacity_replies=1500.0,
                                   active_users=[2, 3])
    info2 = memory.fair_share_info(2, CHAT, capacity_replies=1500.0,
                                   active_users=[2, 3])
    assert info1 == info2
    assert info1["used_user"] == 5
    assert info1["used_group"] == 5
    assert info1["capacity"] == 1500.0
    assert info1["active_count"] == 2
    assert info1["saturated"] is False
    assert info1["mode_limit"] == "ceiling"
    assert memory.get_usage_today()["per_user"][2] == 5


def test_fair_share_info_capacity_none(tmp_db):
    info = memory.fair_share_info(2, CHAT, active_users=[2, 3])
    assert info["capacity"] is None
    assert info["share"] is None
    assert info["limit"] is None
    assert info["mode_limit"] == "unknown"


def test_fair_share_quota_cfg_override(tmp_db):
    # Strict mode at C=100 (group 60 used): default floor 20 lets a
    # 10-use member through; floor 5 holds them to the ~6.67 share.
    _seed_usage(tmp_db, 888, CHAT, 50)
    _seed_usage(tmp_db, 2, CHAT, 10)
    allowed, _ = memory.check_and_consume_quota(
        2, CHAT, capacity_replies=100.0, active_users=list(range(2, 17)))
    assert allowed is True
    _seed_usage(tmp_db, 2, CHAT + 1, 10)
    _seed_usage(tmp_db, 888, CHAT + 1, 50)
    allowed, reason = memory.check_and_consume_quota(
        2, CHAT + 1, capacity_replies=100.0,
        active_users=list(range(2, 17)),
        quota_cfg={"floor_replies": 5})
    assert allowed is False
    assert reason == "fair share reached"


def test_check_records_trigger(tmp_db):
    assert memory.active_users(77) == []
    memory.check_and_consume_quota(42, 77, capacity_replies=100.0)
    assert memory.active_users(77) == [42]


def test_no_hourly_cap_25_in_one_hour_allowed(tmp_db):
    # v0.6b still holds under fair share: 25 calls in the same hour,
    # generous capacity, all allowed (pacing is the handler's job).
    for _ in range(25):
        allowed, _ = memory.check_and_consume_quota(
            222, CHAT, capacity_replies=1500.0, active_users=[222])
        assert allowed is True


# --- hysteresis -------------------------------------------------------------

def _expire_dwell(tmp_db):
    memory.set_state("degrade_mode_since", str(time.time() - 1000))


def test_hysteresis_enter_below_20_percent(tmp_db):
    assert memory.update_degrade_mode(0.10) == "cheap"
    mode, since, held = memory.get_degrade_mode()
    assert mode == "cheap"
    assert since > 0
    assert held is True
    assert memory.get_state("degrade_mode") == "cheap"


def test_hysteresis_dwell_holds_mode(tmp_db):
    memory.update_degrade_mode(0.10)  # enter cheap
    assert memory.update_degrade_mode(0.90) == "cheap"  # dwell: still cheap
    assert memory.update_degrade_mode(0.0) == "cheap"


def test_hysteresis_exit_above_30_after_dwell(tmp_db):
    memory.update_degrade_mode(0.10)
    _expire_dwell(tmp_db)
    assert memory.update_degrade_mode(0.90) == "normal"
    mode, _since, held = memory.get_degrade_mode()
    assert mode == "normal"
    assert held is True  # fresh dwell on the new mode


def test_hysteresis_dead_band_holds_current_mode(tmp_db):
    assert memory.update_degrade_mode(0.25) == "normal"  # 20-30%: stay
    memory.update_degrade_mode(0.10)  # enter cheap
    _expire_dwell(tmp_db)
    assert memory.update_degrade_mode(0.25) == "cheap"  # dead band: stay
    assert memory.update_degrade_mode(0.29) == "cheap"


def test_hysteresis_threshold_boundaries(tmp_db):
    assert memory.update_degrade_mode(0.20) == "normal"  # not < 0.20
    memory.update_degrade_mode(0.19)
    assert memory.get_degrade_mode()[0] == "cheap"
    _expire_dwell(tmp_db)
    assert memory.update_degrade_mode(0.30) == "cheap"  # not > 0.30
    assert memory.update_degrade_mode(0.31) == "normal"


def test_hysteresis_defaults_to_normal(tmp_db):
    assert memory.get_degrade_mode()[0] == "normal"
    assert memory.get_degrade_mode()[1] == 0.0
    assert memory.get_degrade_mode()[2] is False
    assert memory.update_degrade_mode(None) == "normal"


# --- retired v0.6 surface ---------------------------------------------------

def test_retired_fixed_cap_surface_is_gone(tmp_db):
    assert not hasattr(memory, "USER_DAILY_LIMIT")
    assert not hasattr(memory, "GROUP_DAILY_LIMIT")
    assert not hasattr(memory, "group_pool_remaining")
    usage = memory.get_usage_today()
    assert "group_limit" not in usage
    assert "user_limit" not in usage
