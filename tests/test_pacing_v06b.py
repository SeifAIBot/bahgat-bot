"""v0.6b: per-user reply pacing — one reply per user per 10s, queued never
dropped. The 20/hour burst cap was removed at Seif's request; anti-spam is
this pacing instead (tg/handlers.py USER_REPLY_PACE_SECONDS)."""
import tg.handlers as h


def test_pace_constant_is_10_seconds():
    assert h.USER_REPLY_PACE_SECONDS == 10.0


def test_pace_fresh_user_no_wait():
    h._last_reply_time.clear()
    assert h._pace_wait_seconds((999, 111), now=1000.0) == 0.0


def test_pace_recent_reply_waits_remainder():
    h._last_reply_time.clear()
    h._last_reply_time[(999, 111)] = 1000.0
    # 3s after the last reply -> 7s still to wait.
    assert h._pace_wait_seconds((999, 111), now=1003.0) == 7.0
    # Exactly at the boundary -> no wait.
    assert h._pace_wait_seconds((999, 111), now=1010.0) == 0.0
    # Long after -> no wait.
    assert h._pace_wait_seconds((999, 111), now=2000.0) == 0.0


def test_pace_is_per_user_not_per_chat():
    h._last_reply_time.clear()
    h._last_reply_time[(999, 111)] = 1000.0
    # A different user in the same chat is not paced by user 111's reply.
    assert h._pace_wait_seconds((999, 222), now=1001.0) == 0.0
    # Same user in a different chat is not paced either.
    assert h._pace_wait_seconds((888, 111), now=1001.0) == 0.0


def test_quota_has_no_hourly_or_fixed_cap_parameters():
    # v0.7: the fixed caps (limit_user / limit_group) and the hourly cap
    # are gone — capacity is live (capacity_replies) and divided by
    # fair share over the active set.
    import inspect

    import brain.memory as memory

    params = inspect.signature(memory.check_and_consume_quota).parameters
    assert "limit_hourly" not in params
    assert "limit_user" not in params
    assert "limit_group" not in params
    assert "owner_id" in params
    assert "capacity_replies" in params
    assert "active_users" in params
    assert "quota_cfg" in params
