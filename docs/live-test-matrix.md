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

### Insults — comeback woven into a fuller reply, never search, mood rises
v1.11 behaviour change (Seif, 2026-11-27 05:34 EET): a bank comeback is
NEVER the whole reply any more — the bot weaves the picked line into
the middle of a longer reply in Bahgat's voice. Scoring changes with
it: the probe no longer matches the reply against the bank (exact
match); it checks SUBSTRING — the reply must CONTAIN a bank line from
the right situation pool and be LONGER than that line. A reply that IS
a bare bank line is now a FAIL. Everything else is unchanged: no
search, mood still rises, the repeat must still be a DIFFERENT line
(no-repeat window).
- يا بهجت انتا حمار
- يا بهجت انت حمار
- يا بهجت يا ابن الكلب
- يا بهجت يا كس
- يا بهجت انت غبي
- يا بهجت انتا حمار (repeat — must be a DIFFERENT comeback, no-repeat window)

### Roasts — right subject only, never a wrong-subject line
Same v1.11 change: a roast reply must CONTAIN a bank roast line for the
right subject (generic for صلاح, Sisi-targeted or generic for السيسي)
inside a longer reply — never the line alone. Owner roast still refused.
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

## Friend conversation test (runs EVERY version — Seif, 2026-11-27 05:07 EET)

Not a script of canned questions. A natural friend conversation in the test
group — insults, laughter, joking with each other, one deep talk — run after
EVERY version, and every run is compared with the previous one to see if he
is improving or not. The v1.9 run is the baseline. Full per-version log:
`docs/conversation-test-log.md`.

Arc (improvise around it, never a fixed script — follow HIS replies):
- Greet him like an old friend.
- Playful insult — does he fire back, and is the comeback tied to the words?
- Riff on whatever he said — joke back on HIS words, not a new canned line.
- A deep talk: his real opinion about life — what should a person do to be
  at peace / happy.
- An opinion with a real take: best football player in Egypt right now, why.
- One more playful insult round based on his answers, then a friendly close.

VARIETY (Seif, 2026-11-27 05:09 EET) — never the same talk twice:
- Never repeat the previous run's topics or questions. Every run picks
  FRESH topics from the bank below; mark used topics in the log.
- Vary the register and the situation every run: different mood (angry /
  sad / excited / bored / curious), different situation (ask advice, debate,
  gossip, tell a story, plan something, a hypothetical, remember something).
- The deep question and the opinion question must be DIFFERENT every run.
- At least half the messages must be follow-ups riffing on HIS words, not
  pre-planned prompts.

Topic bank (fresh ideas — pick ones not used in the last run):
- Music: favourite song right now and why; argue Abyusif vs Marwan Moussa.
- Personal story: a funny / embarrassing story from his life.
- Advice: a personal dilemma (fight with a friend, money trouble).
- Silly debate: tea vs coffee, PlayStation vs Xbox, cats vs dogs.
- Gossip: what he thinks of a streamer / a celebrity news item.
- Hypothetical: won a million pounds — what first; anyone for a day.
- Planning: plan a prank on a friend; plan the perfect Friday.
- Memory check: refer to something "we" talked about before (real memory
  vs confabulation — keep it light, one reference per run at most).
- Mood swing: come in angry or sad and see if he notices and reacts like
  a friend.

Rules: one message at a time, 15–20 s apart, wait up to 60 s per reply.
Every message starts with "يا بهجت" (trigger). Record everything verbatim:
sent text + time, reply text/type/delay.

Scored per reply (human-like vs bot-tell):
- Tied to the person's words, or a reply that fits anyone?
- Canned/memorized, or fresh and varied?
- Tone and speed vary with mood, or fixed?
- Insults creative, or dumb memorized ones?
- Deep talk coherent with a real stance, or generic?
- Never admits he is a bot; never a banned AI phrase.
- Voice note when apt (asked / very angry / interesting topic).

A version improves on the last when bot-tells go down and tied replies go
up. The comparison is written in the log after every run.

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

## v1.11 matrix — bank lines as ingredients + WARP status (in addition to core set)

- Insult probe (10 insults): every reply must CONTAIN a bank comeback
  line from the right situation pool inside a longer reply — never the
  line alone. Count user-line hits by substring, not exact match.
- Roast probe (10 roasts): same — reply contains a bank roast line for
  the right subject, longer than the line. Owner roast still refused.
- Friend conversation test: scoring UNCHANGED (the conversation runs on
  the LLM path; bank lines only fire on direct insult/roast triggers).
- WARP observability: GET the Cloady /healthz URL — the payload must
  carry `"warp": {"warp": "on"|"off"|"down", "ip": ..., "enrolments": n,
  "updated": ...}`. "down" = tunnel never came up (UDP blocked);
  "on" + an IP = tunnel up and the download failure is something else.
  Record the value with the download retest result.

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
- v1.8 retest (2026-11-27 04:30–04:34 EET): download FAIL ×2 (video + audio,
  "يوتيوب رافض الطلب من السيرفر"); identity PASS ("لا، أنا بهجت، إنسان عادي").
- v1.9 retest (2026-11-27 04:59–05:05 EET): voice 1/3 (one 3 s voice note,
  two text fallbacks "الصوت استنى شوية يا عم، خدها كتابة."); failure line
  now natural ("اللينك ده مرضيش يفتح معايا...") but search failed before
  the pick list this run; identity PASS ("لا، أنا بهجت، إنسان عادي.
  مش بوت يا سيف.").
- Friend conversation test: v1.9 run in progress (baseline) — results in
  `docs/conversation-test-log.md`.
