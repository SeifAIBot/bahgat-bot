"""Failure-line pools + thinking lines (v1.9, Instinct flaw-fix).

Failure replies are random picks from small human-voiced pools — never
programmer-talk ("التنزيل فشل", "يوتيوب رافض الطلب من السيرفر").
The thinking bubble no longer announces processing ("بفكر يا عم،
استنى…") — short human lines cycled by spinner frame instead.
"""
import tg.handlers as h

_PROGRAMMER_TALK = ("التنزيل فشل", "يوتيوب رافض", "من السيرفر", "فشل")


def test_download_pool_has_no_programmer_talk():
    assert len(h._DOWNLOAD_FAILURE_LINES) >= 3
    for line in h._DOWNLOAD_FAILURE_LINES:
        assert line.strip()
        for bad in _PROGRAMMER_TALK:
            assert bad not in line


def test_search_pool_has_no_programmer_talk():
    assert len(h._SEARCH_FAILURE_LINES) >= 2
    for line in h._SEARCH_FAILURE_LINES:
        assert line.strip()
        assert "هدورلك" not in line
        assert "كابتشا" not in line


def test_voice_pool_has_no_programmer_talk():
    assert len(h._VOICE_FAILURE_LINES) >= 2
    for line in h._VOICE_FAILURE_LINES:
        assert line.strip()
        assert "نظام" not in line


def test_pickers_return_pool_lines():
    for _ in range(20):
        assert h._download_failure_line() in h._DOWNLOAD_FAILURE_LINES
        assert h._search_failure_line() in h._SEARCH_FAILURE_LINES
        # The voice note carries a leading newline before the line.
        assert h._voice_failure_note().startswith("\n")
        assert h._voice_failure_note()[1:] in h._VOICE_FAILURE_LINES


def test_search_fallback_reply_uses_pool():
    assert h._search_fallback_reply("[SEARCH FAILED] — مفيش نتائج.") in (
        h._SEARCH_FAILURE_LINES)


def test_thinking_lines_cycle_by_frame():
    assert h.status_line("thinking", 0)[2:] == h._THINKING_LINES[0]
    assert h.status_line("thinking", 1)[2:] == h._THINKING_LINES[1]
    assert h.status_line("thinking", 2)[2:] == h._THINKING_LINES[2]
    assert h.status_line("thinking", 3)[2:] == h._THINKING_LINES[0]
    assert "بفكر" not in h.status_line("thinking")
    assert h.status_line("nope") == h.status_line("thinking")
