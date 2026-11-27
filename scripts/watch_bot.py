#!/usr/bin/env python3
"""Watch the Bahgat bot's live traffic in the Telegram test group — READ ONLY.

Polls Bot API getUpdates for a bounded window and prints, for the test
group, each incoming user message the bot received, each button tap
(yt:video / yt:audio / yt:pick:N) and — when a user replies to the bot —
the bot's own message as quoted in that reply, all with Cairo timestamps.

READ-ONLY GUARANTEES (do not weaken them):
- Only getUpdates is ever called, and NEVER with an offset: updates are
  never acknowledged/consumed, so the deployed bot on Cloady still
  receives every one of them. Passing an offset here would STARVE the
  live bot — that is why this script has no offset parameter at all.
- sendMessage is never called, from anywhere in this file.
- No state is written anywhere; seen update_ids live in memory only.

HONEST LIMITS (Bot API, not this script):
- getUpdates returns INCOMING updates only. The bot's own outgoing
  replies are never delivered back to the bot, so this watcher cannot
  print a bot reply directly. A bot reply becomes visible only when a
  user replies to it (then it arrives as reply_to_message) — those are
  printed as "[BOT, quoted]". If you need every bot reply verbatim,
  use the scenario tests (tests/test_live_scenarios.py) for the reply
  logic and this watcher for what the bot actually received.
- The deployed bot long-polls and acknowledges updates quickly, so a
  message is visible here only between its arrival and the bot's next
  acknowledgement. The default 3s interval catches most traffic while
  the group is active; a message the bot already answered may already
  be gone from the queue — that is normal, not a failure.
- Two concurrent getUpdates callers can 409-conflict only when both
  long-poll with a timeout; this script polls with no timeout (each
  call returns immediately), so conflicts are rare and are logged and
  retried, never fatal.

Usage:
  python3 scripts/watch_bot.py [--chat-id -1005812444791]
                               [--seconds 120] [--interval 3]
Run it, then type in the test group (or tap a button) while it watches.
"""
import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_CHAT_ID = -1005812444791  # test group "Bahgat bot"
DEFAULT_BOT_ID = 9106462211
DEFAULT_BOT_USERNAME = "Bahgoti_bot"
HELPER_PATH = Path.home() / "workspace" / "custom-connectors" / \
    "custom.telegram" / "bin" / "telegram.py"
CAIRO = ZoneInfo("Africa/Cairo")


def _load_helper():
    """Import the custom.telegram helper module by path (it is not on
    sys.path). Only its read-only `call` is used."""
    if not HELPER_PATH.exists():
        sys.exit(f"telegram helper not found: {HELPER_PATH}")
    spec = importlib.util.spec_from_file_location("telegram_helper", HELPER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ts(unix_ts):
    """Unix timestamp -> 'HH:MM:SS' in Cairo time."""
    try:
        return datetime.fromtimestamp(int(unix_ts), tz=CAIRO).strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return "?"


def _sender(user):
    if not isinstance(user, dict):
        return "?"
    name = user.get("first_name") or user.get("username") or "?"
    if user.get("username"):
        name = f"{name} (@{user['username']})"
    return f"{name} [{user.get('id', '?')}]"


def _text_of(msg):
    """Message text or caption, one line."""
    text = (msg or {}).get("text") or (msg or {}).get("caption") or ""
    return " ".join(str(text).split())


def _describe_message(msg, bot_id, bot_username, chat_id):
    """One line per message, or None when it is not test-group traffic."""
    if not isinstance(msg, dict):
        return None
    if msg.get("chat", {}).get("id") != chat_id:
        return None
    sender = msg.get("from") or {}
    is_bot = sender.get("is_bot") is True or sender.get("id") == bot_id
    tag = "BOT " if is_bot else "USER"
    line = (f"[{_ts(msg.get('date'))}] [{tag}] {_sender(sender)} "
            f"(msg {msg.get('message_id')}): {_text_of(msg)}")
    out = [line]
    reply_to = msg.get("reply_to_message")
    if isinstance(reply_to, dict):
        r_sender = reply_to.get("from") or {}
        r_is_bot = r_sender.get("is_bot") is True or \
            r_sender.get("id") == bot_id
        if r_is_bot:
            out.append(
                f"[{_ts(reply_to.get('date'))}] [BOT, quoted in reply] "
                f"{bot_username} (msg {reply_to.get('message_id')}): "
                f"{_text_of(reply_to)}")
    return "\n".join(out)


def _describe_update(update, bot_id, bot_username, chat_id):
    """Human-readable lines for one update dict, or [] when irrelevant."""
    if not isinstance(update, dict):
        return []
    if "message" in update:
        line = _describe_message(update["message"], bot_id, bot_username,
                                 chat_id)
        return [line] if line else []
    if "callback_query" in update:
        q = update["callback_query"] or {}
        msg = q.get("message") or {}
        if msg.get("chat", {}).get("id") != chat_id:
            return []
        return [f"[{_ts(q.get('date') or msg.get('date'))}] [TAP] "
                f"{_sender(q.get('from'))} tapped {q.get('data')!r} on "
                f"msg {msg.get('message_id')}: {_text_of(msg)}"]
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Read-only watch of the Bahgat bot's test-group traffic.")
    ap.add_argument("--chat-id", type=int, default=DEFAULT_CHAT_ID,
                    help="Telegram chat id to watch (default: test group)")
    ap.add_argument("--seconds", type=int, default=120,
                    help="how long to watch (default: 120)")
    ap.add_argument("--interval", type=float, default=3.0,
                    help="seconds between getUpdates polls (default: 3)")
    ap.add_argument("--bot-id", type=int, default=DEFAULT_BOT_ID)
    ap.add_argument("--bot-username", default=DEFAULT_BOT_USERNAME)
    args = ap.parse_args(argv)

    helper = _load_helper()
    # getMe first: proves the token works, reads only, changes nothing.
    try:
        me = helper.call("getMe")
    except Exception as e:  # noqa: BLE001 — report and stop, nothing to watch
        print(f"getMe failed, cannot watch: {e}", file=sys.stderr)
        return 1
    result = (me or {}).get("result") or {}
    print(f"Watching as @{result.get('username', args.bot_username)} "
          f"(id {result.get('id', args.bot_id)}) — chat {args.chat_id} "
          f"for {args.seconds}s, polling every {args.interval:g}s.")
    print("Read-only: getUpdates without offset (never consumes updates), "
          "no sends. Ctrl+C to stop early.")
    print("Note: bot replies appear here only when quoted in a later "
          "reply; direct replies are not delivered via getUpdates.")
    print("-" * 80, flush=True)

    seen = set()
    counts = {"user": 0, "bot_quoted": 0, "tap": 0, "polls": 0, "errors": 0}
    deadline = time.time() + max(0, args.seconds)
    while True:
        if time.time() >= deadline:
            break
        try:
            resp = helper.call("getUpdates")
            counts["polls"] += 1
        except Exception as e:  # noqa: BLE001 — transient; log and retry
            counts["errors"] += 1
            print(f"[{datetime.now(CAIRO).strftime('%H:%M:%S')}] "
                  f"poll failed ({e}), retrying…", flush=True)
            time.sleep(min(args.interval, 5))
            continue
        if not isinstance(resp, dict) or not resp.get("ok"):
            counts["errors"] += 1
            print(f"poll returned not-ok: {json.dumps(resp)[:200]}",
                  flush=True)
            time.sleep(args.interval)
            continue
        for update in resp.get("result") or []:
            uid = update.get("update_id")
            if uid in seen:
                continue
            seen.add(uid)
            lines = _describe_update(update, args.bot_id,
                                     args.bot_username, args.chat_id)
            for line in lines:
                print(line, flush=True)
                if "[USER]" in line:
                    counts["user"] += 1
                elif "[BOT, quoted" in line:
                    counts["bot_quoted"] += 1
                elif "[TAP]" in line:
                    counts["tap"] += 1
        sleep_left = deadline - time.time()
        if sleep_left <= 0:
            break
        time.sleep(min(args.interval, sleep_left))

    print("-" * 80)
    print(f"Done. Polls: {counts['polls']}, errors: {counts['errors']}, "
          f"user messages seen: {counts['user']}, "
          f"bot replies quoted: {counts['bot_quoted']}, "
          f"button taps: {counts['tap']}.")
    print("If a message you sent does not appear above, the deployed bot "
          "already acknowledged it — re-send it while watching, or check "
          "the scenario tests for the reply logic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
