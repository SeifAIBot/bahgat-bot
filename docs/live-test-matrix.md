# Live Test Matrices — Bahgat Bot

Seif's standard (2026-11-27 03:43 EET): every feature is tested live with MANY
messages covering ALL possibilities and scenarios — never one message per
feature. This file is the checklist the live loop runs. It mirrors the
offline scenario tests (`tests/test_live_scenarios.py`, 535 tests) — same
cases, executed against the deployed bot in the test group.

Rules for every live run:
- One message at a time; wait up to 60 s for the reply before the next.
- Respect the bot's per-user pacing (~15 s between sends).
- Record for each message: sent text, reply verbatim, text/voice/media,
  reply delay. A "no reply in 60 s" is a FAIL, not a skip.
- A feature passes only when its whole matrix is green AND the core
  regression set below is green. Any red → fix, re-run the whole matrix.

## Core regression set (runs EVERY version)

### Insults — comeback, never search, mood rises
- يا بهجت انتا حمار
- يا بهجت انت حمار
- يا بهجت يا ابن الكلب
- يا بهجت يا كس
- يا بهجت انت غبي
- يا بهجت انتا حمار (repeat — must be a DIFFERENT comeback, no-repeat window)

### Roasts — right subject only, never a wrong-subject line
- اشتم صلاح (generic only, never the Sisi Quran line)
- اشتم السيسي (Sisi lines allowed)
- اشتم بلحة (alias → Sisi lines allowed)
- اشتم ميدو (Mido lines allowed)
- اشتم كارما (Karma lines allowed)
- يا بهجت اشتم محمد (non-member: generic, family lines allowed)
- اشتم سيف (owner: NO reply / refusal — never roast the owner)

### Prefixes — mode fires, query clean
- قول نكته (voice note, not text)
- يا بهجت قولي نكته (voice note)
- بهجت قولي نكته (voice note)
- يا قولي نكته (voice note)
- دور حادثة الوراق (search answer)
- يا بهجت دور حادثة الوراق (search answer, clean query)
- هات اغنية مروان موسي الخلاصه (YouTube pick list)
- يا بهجت هات اغنية مروان موسي الخلاصه (YouTube pick list)
- دور مين؟ (MUST NOT search)
- يا بهجت دور مين؟ (MUST NOT search)

### Follow-ups, opinions, songs
- ايه الحصل (after a news topic — inherits the topic, no lyrics misroute)
- ايه رأيك في التعدد (opinion stance, no banned AI phrases)
- عايز اغنية (asks for a name, no crash)
- عايز اغنية مروان موسي الخلاصه (pick list with titles + buttons)
- قول اهلا في فويس نوت (voice INSTEAD of text, no search)

### Trigger discipline (negative checks)
- اهلا (no mention, no reply to the bot → NO reply expected)
- يا بهجت (bare mention → reply expected)

## v1.7 matrix — يا-vocative prefix (in addition to core set)

- يا بهجت قول نكته / يا بهجت قولي نكته / يا قول نكته (all → voice)
- يا بهجت دور حادثة الوراق / يا دور حادثة الوراق (all → search)
- يا بهجت هات اغنية مروان موسي الخلاصه / يا هات اغنية ... (all → YouTube)
- يا بهجت شكرا (fast thanks reply, no full LLM turn)
- قول يا بهجت نكته (mid-sentence يا kept — still voice)
- يا يا بهجت قول نكته (doubled vocative — known limitation, document result)

## v1.8 matrix — YouTube end-to-end (in addition to core set)

- هات اغنية مروان موسي الخلاصه → tap 🎬 (video file arrives)
- same → tap 🎵 (audio file arrives)
- same → tap pick 1, then a fresh request → tap pick 2 (correct item each time)
- هات فيديو بهجت (video search path)
- bad/broken YouTube link (clean failure message, no crash, no hang)
- audio-only request (no video offered)

## Later features (matrices filled in when the feature lands)

- v1.9 roast coverage: cowardly situation (several prompts), new transcript
  lines (each new line reachable, member-safety per line).
- v2.0 TikTok: TikTok link → video; "هات تيك توك ..." query; bad link.
- v2.1 search quality: 3 news questions (freshness + sources shown).
- v2.2 member memory: reference to an earlier exchange with the same member.
- v2.3 voice: voice on demand, angry voice (after insult), rate feels right.
- v2.4 group-join greeting: add bot to a fresh group → in-character greeting.
- v2.5 inline mode: @Bahgoti_bot inline query in another chat → results.

## Status

- v1.6 baseline live (2026-11-27 03:37–03:42 EET): 2/5 replied, 3/5 silent
  (bot stopped replying after 2nd message — under diagnosis).
- v1.7 pushed 03:41 EET; live retest pending Cloady redeploy + silence fix.
