"""Mood-based reply-delay jitter (v1.9, Instinct flaw-fix).

A human does not answer everything at the same speed: هزار 1–3s,
غضب 2–4s, استعجال immediate, حزن 4–7s, serious question 3–6s, then
±30% jitter. Bands are pure functions of (mood, text); the handler
pauses with a typing indicator during the sampled delay.
"""
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from brain.mood import reply_delay_band, reply_delay_seconds


class _FixedRng:
    """Uniform stub: returns the given values in order."""

    def __init__(self, values):
        self._it = iter(values)

    def uniform(self, a, b):
        return next(self._it)


def test_band_urgent_is_immediate():
    assert reply_delay_band(30, "رد بسرعه يا بهجت") == (0.0, 0.0)
    assert reply_delay_band(90, "حالا قولي") == (0.0, 0.0)
    assert reply_delay_band(30, "دلوقتي يا عم") == (0.0, 0.0)


def test_band_angry():
    assert reply_delay_band(70, "اهلا") == (2.0, 4.0)
    assert reply_delay_band(100, "اهلا") == (2.0, 4.0)
    # Anger dominates over a sad message — a furious Bahgat simmers.
    assert reply_delay_band(85, "انا زعلان") == (2.0, 4.0)


def test_band_sad():
    assert reply_delay_band(30, "انا زعلان النهارده") == (4.0, 7.0)
    assert reply_delay_band(69, "مخنوق يا عم") == (4.0, 7.0)


def test_band_serious_question():
    assert reply_delay_band(30, "ايه اللي حصل في حادثة الوراق؟") == (3.0, 6.0)
    assert reply_delay_band(30, "ليه الاسعار غاليه؟") == (3.0, 6.0)
    assert reply_delay_band(30, "مين كسب الماتش") == (3.0, 6.0)


def test_band_playful_default():
    assert reply_delay_band(30, "اهلا يا بهجت") == (1.0, 3.0)
    assert reply_delay_band(69, "هههههه") == (1.0, 3.0)


def test_delay_math_applies_jitter():
    # Band (2, 4): base 3.0, jitter +0.3 -> ~3.9.
    assert reply_delay_seconds(80, "اهلا", _FixedRng([3.0, 0.3])) == pytest.approx(3.9)
    # Jitter -0.3 -> ~2.1.
    assert reply_delay_seconds(80, "اهلا", _FixedRng([3.0, -0.3])) == pytest.approx(2.1)
    # Urgent -> 0 without touching the rng at all.
    assert reply_delay_seconds(30, "رد بسرعه", _FixedRng([])) == 0.0


def test_delay_stays_in_band_plus_jitter():
    rng = random.Random(7)
    for _ in range(200):
        d = reply_delay_seconds(30, "اهلا", rng)
        assert 0.7 <= d <= 3.9  # band 1–3s ±30%


async def test_human_delay_types_during_pause(monkeypatch):
    import tg.handlers as h

    monkeypatch.setattr(
        "brain.mood.reply_delay_seconds", lambda mood, text: 0.2)
    bot = SimpleNamespace(send_chat_action=AsyncMock())
    await h._human_delay(bot, -1001, 30, "اهلا")
    assert bot.send_chat_action.await_count >= 1
    assert bot.send_chat_action.await_args[0][1] == "typing"


async def test_human_delay_zero_skips_typing(monkeypatch):
    import tg.handlers as h

    monkeypatch.setattr(
        "brain.mood.reply_delay_seconds", lambda mood, text: 0.0)
    bot = SimpleNamespace(send_chat_action=AsyncMock())
    await h._human_delay(bot, -1001, 30, "رد بسرعه")
    bot.send_chat_action.assert_not_awaited()
