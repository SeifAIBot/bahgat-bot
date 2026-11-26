# Telegram bot UX research — v0.8 (2026-11-26)

Seif asked for TeleClaw-style live status, a MIRAL-style YouTube pick-list,
and وعد-style video/audio choice buttons, and told us not to rely on
ourselves only. Findings below; sources are the pages actually read.

## Sources

- BotHero, "Telegram Bot Edit Message: 5 Proven Fixes for 2026"
  https://blog.bothero.ai/telegram-bot-edit-message-the-hidden-mechanic-behind-bots-that-feel-alive-and-the-4-failure-modes-that-make-yours-feel-broken
- Muftiev, "Streaming AI in Telegram Bots: Message Edit Rate Limits and
  Practical Fixes" https://telegram.muftiev.com/blog/ai-streaming-for-telegram-bot.html
- Hermes Telegram Platform architecture study (Liberty Labs)
  https://liberty-labs.org/document/notebook-hermes-telegram
- grokbot-telegram-bridge (Glama) — OpenClaw-style progress drafts
  https://glama.ai/mcp/servers/mia-oc/grokbot-telegram-bridge
- Aura, "Telegram Bot UI/UX Best Practices"
  https://github.com/chetto1983/Aura/blob/HEAD/docs/telegram-ux-best-practices.md
- Telegram Bot Guidelines https://core.telegram.org/bots/guidelines
- daviddaily telegram-music-bot (music.py) — 5-result pick-list pattern
  https://www.daviddaily.dev/zer0t3ch/telegram-music-bot/src/branch/master/music.py

## What the pros do (adopted)

1. **One editable status bubble, not a flood of messages.** Every source
   agrees: send ONE message and edit it in place as work progresses, then
   delete it before the final answer lands (OpenClaw calls this a
   "progress draft"; Hermes routes status callbacks through a single
   `send_or_update_status()` keyed by chat). Bots that edit in place see
   measurably higher retention than bots that only send new messages
   (BotHero). Adopted: `_StatusMessage` — one bubble per turn, edited per
   stage, deleted in a finally block.
2. **Status bubbles must not ring.** Hermes sends tool-progress bubbles
   with `disable_notification=true` so long agent turns don't spam the
   user's phone; only final answers ring. Adopted: the status message is
   sent with `disable_notification=True`.
3. **Don't edit on every token.** Muftiev: Telegram rate-limits edits
   (practical ceiling ~1 edit/sec per message); aggressive edit loops hit
   429 and the stream collapses. Adopted: we edit only on stage changes
   plus a slow spinner tick (1.5 s), never per token — our turns have at
   most a handful of stages, so we stay far under the limit.
4. **Keepalive / spinner while a stage runs long.** OpenClaw's bridge
   cycles the draft through short status lines on a ~2.5 s ticker until
   the agent's first real progress update. Adopted in spirit: a braille
   spinner (⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏) cycles in the bubble every 1.5 s while a
   stage runs, so a slow LLM/search never looks frozen.
5. **Pick-lists are numbered buttons, values resolved server-side.**
   Music bots fetch 5 results and show them as a vertical list; the
   universally recommended callback pattern is **never put the payload in
   callback_data — put a short index and resolve it server-side**
   (Aura's research note: `callback_data` is 1–64 BYTES of UTF-8, and
   long values 400 with BUTTON_DATA_INVALID). Adopted: `yt:pick:<index>`
   (a few bytes), results kept in the existing `yt_requests` state map,
   same 10-min TTL and requester-only guard as the existing callbacks.
6. **Inline keyboards for actions that change an existing message.**
   Telegram's own guidelines: inline buttons are ideal when the tap
   modifies the message in place (no new message appears). Adopted: the
   pick-list and the video/audio choice both edit/replace the same
   message instead of posting new ones.
7. **Button text short.** Button text is ~64 chars client-dependent;
   keep ≤ ~24 chars to be safe on mobile (agntdev skill / Aura note).
   Adopted with a compromise: pick-list buttons are truncated to 40
   chars (Arabic song titles are long; the full title stays in the
   message body above the buttons, MIRAL-style).

## Rejected / not done

- **Streaming the LLM reply token-by-token into the status bubble.**
  Muftiev's conclusion is that this is worth it only with heavy
  throttling and fallback machinery; our replies are short (≤600 tokens)
  and the turn is usually a few seconds, so stage edits are enough.
  The status bubble is deleted and the full reply sent at once.
- **Animated emoji / Telegram Premium effects.** Bots cannot use
  Premium animated emoji (they need custom-emoji IDs from sets the bot
  doesn't own), and there's no Bot API for "thinking" animations. The
  closest a bot can do is the spinner-frame edit + chat actions
  (`typing`, `record_voice`), which is what we do.
- **Converting the pick-list text message into a photo message via
  editMessageMedia.** The Bot API only lets you edit media on a message
  that already has media; a text message can't be turned into a photo
  in place. So on pick we send a new photo message (thumbnail +
  caption + the two buttons) and delete the list message — the same
  visible result وعد shows.
- **Inline mode (`@bot query`).** Telegram's guidelines suggest it for
  search, but this bot is triggered by natural talk in groups and
  inline mode needs a separate BotFather setting and flow; out of scope
  for v0.8.
- **Pinning the status message while the bot works** (Hermes does this).
  Rejected: pinning in a group is noisy and needs extra permissions;
  the bubble + typing indicator are enough.
