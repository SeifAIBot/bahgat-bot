# Changelog
## 2026-11-27 — v1.8: YouTube download chain reorder + node runtime, file logging to the volume, human identity rule

Diagnosis first (2026-11-27 04:04 EET): YouTube video AND audio downloads both fail live on Cloady (03:57 / 04:01 EET, "يوتيوب رافض الطلب من السيرفر") while the SAME chain works end to end in this VM (Marwan Moussa El Kholasa: video OK 10.6s / 5.07 MB mp4, audio OK 18.6s / 3.4 MB mp3). Root cause is the host, not the code: YouTube bot-checks Cloady's datacenter IP on the player API; the cookies are valid to Dec 2027 and even known-good cookies fail on the web client. Confirmed live the same day: Waad (@D7Bot, added to the test group) downloads the SAME song fine from another host (~1s) — its files carry an "@YYYYF" caption and a "بوت تحميل وعد" link, so they may come through a backend service/files channel rather than direct yt-dlp; that off-Cloady route is a FUTURE option, not this version. So v1.8 reorders and strengthens the chain instead of debugging it.

- Download chain (tools/youtube.py): plain android FIRST (VM probe: android+skip failed twice, plain android succeeded twice — v1.3 had the weaker variant first), then android+skip, ios+skip, web+skip; a second pass over the two android variants after a 5s sleep (the check is intermittent — a later independent ticket can pass); then a tv attempt with `-f best` (tv got a player response once where web was bot-checked); web+cookies LAST, unchanged. The v1.3 explicit-format attempt (android+skip+fmt18) is dropped — tv+best covers its job. Resolve uses the same reordered client order (4 attempts + cookies). Per-attempt outcomes are now logged at INFO on success too, not only on failure.
- JS runtime (Dockerfile + tools/youtube.py): the image installs `nodejs` (yt-dlp enables only deno by default, so without a runtime the web client runs degraded — JS challenges unsolved → bot-check). Web-client attempts pass `--no-js-runtimes --js-runtimes node` (the `--no-` flag must come first to clear the deno default). Flag combination verified against the installed yt-dlp 2026.11.23 (parses clean; a live fetch hit the VM's egress 429, not a flag error). Docker build itself is unverified locally (no Docker in the VM) — Cloady builds it on push.
- File logging (main.py): Cloady free tier shows no runtime logs, so a RotatingFileHandler (1 MB x 3 backups, ~4 MB max) now writes to `data/bot.log` on the root logger — every module logger (tools.youtube per-attempt warnings, tg.handlers errors) lands there in the same format as stdout. Never crashes the bot over logging: an unwritable volume falls back to console-only with a warning; re-configuring adds no duplicate handler. `data/` and `*.log` are gitignored, so the log file itself is never committed.
- Human identity (brain/prompt.py prompt 6.4 → 6.5, brain/verify.py): Seif's directive after the rival bot kept admitting it is a bot — Bahgat must NEVER admit being a bot/AI and considers himself a normal human. SYSTEM_BASE now opens "انت بهجت صابر، إنسان عادي — مش بوت، مش ذكاء اصطناعي، مش برنامج." and _HARD_RULES_END gains rule 4 (deny when asked, scoped: "ده عن نفسك انت بس — لو سألك عن بوت تاني جاوب عادي"). The verify filter enforces it in code: first-person self-admissions ("أنا بوت", "أنا ذكاء اصطناعي", "أنا مش بني آدم", "أنا برنامج", … — normalised, so alef variants match) replace the WHOLE reply with an in-character denial ("أنا بهجت يا عم، إنسان عادي، مش بوت."), and voice_check flags "self_bot_admission" so the handler regenerates once first. Scoping is the point: "سعد ده بوت" / "انت مش بني آدم" (about others) pass untouched — the bare word "بوت" is deliberately not banned. Prompt budgets grew for the rule (SYSTEM_BASE < 1100, dynamic tail < 400 tokens) with v1.8 notes in the tests.
- Also committed with this version: docs/roadmap-v10.md, docs/live-test-matrix.md, docs/lightning-runbook.md (were untracked).

**Verified:** 547 tests pass (535 baseline + 12 new: 2 chain order/sleep/JS-flags, 4 file logging, 3 verify scoping, 2 identity scenarios, 1 prompt identity), ruff check clean on changed files. Voice synthesis untouched (separate job).

## 2026-11-27 — v1.7: fix "يا" vocative blocking the prefix layer + live-scenario test harness

The new harness (tests/test_live_scenarios.py — 60 scenario tests through the real pipeline — plus scripts/watch_bot.py, a read-only getUpdates watcher for live diagnosis) pinned a real bug: `detect_prefix_mode` stripped "بهجت" but not the vocative "يا", so "يا بهجت قولي نكته" routed to just_chat (joke as text, no voice note) and "يا بهجت دور حادثة الوراق" searched via the classifier with the raw text ("يا بهجت دور حادثة الوراق") as the query. Seif's messages almost always start "يا بهجت", so the prefix feature he asked for barely ever fired.

Fix: the prefix layer — and the fast-reply path, which had the same asymmetry ("يا بهجت شكرا" missed the fast path and cost a full LLM turn) — now skips one leading "يا" via `_skip_leading_vocative()` in brain/intent.py. Only the leading vocative is stripped; mid-sentence "يا" is untouched ("قول يا بهجت نكته" → voice, remainder "يا نكته"). Guards unchanged: "دور مين؟" never searches, "يا بهجت" alone stays normal chat, member/owner gates untouched. The two harness tests that pinned the buggy behaviour now assert the fixed behaviour, plus a handler-level يا-form joke-voice test and يا-form fast-reply tests.

**Verified:** 535 tests pass (473 baseline + 60 harness scenarios + 2 new), ruff check clean on changed files (ruff format diffs are pre-existing repo-wide, not enforced).

## 2026-11-26 — v1.6 phase 1: ingest Seif's submitted insults, round 3

Seif added 12 more insult lines on the "قاموس شتايم بهجت" page (page total now 45: 24 round 1 + 9 round 2 + 12 round 3). 10 were banked: 5 insulted comebacks (in-41..in-45, served 39 → 44) and 5 roasts (ro-42..ro-46, served 40 → 45). Bank total 214 → 224 raw entries (202 → 212 served). Two family lines this round: ro-42 ("ابن متناكه و ماشي…", Seif marked it "للبرّه بس" — the detector agrees) and ro-44 ("بعبصو بعض في حته تانيه يا ولاد ال…" — the detector's "يا ولاد" branch flags it even though Seif tagged the line member_safe on the page; the detector wins, so it is banked member_safe: false in the roast pool, never served at a member). The Mido line is the first subject-targeted user roast (ro-43, target: ميدو — fires only for a ميدو roast, never as a generic comeback). Dropped 2 lines: "قوم يا مصري مصر دايما ب تناديك قوم يا ايبنللللللللل مش هنتحايل عليك" (near-duplicate of the round-1 dropped rallying line "قووم يا مصري مش هنتحايل عليك" — still a patriotic chant, not an insult) and "خخخخخ ايوه خخخخخخ ايوه" (mocking laughter only, not an insult). One resubmission ("ايه الشرمطه دي") was skipped by the page itself as an exact duplicate of round-2's in-34. The round-1/round-2 dropped lines stay out. Note: this is phase 1 of v1.6; phase 2 follows.

**Phase 2 — contextual insult selection (same day):** every served insulted/roast line now carries `situations:` tags in the YAML (insulted: mocked 10, dismissed 8, sworn-at 6, general 11, called-dumb 4, family-attacked 4, repeated-insult 4, threatened 3; roast: general 18, perv 14, stupid-statement 9, arrogant 4, annoying 2 — roast `cowardly` has no line yet and falls back to `general`). Detection is deterministic keywords in `brain/intent.py` (`detect_insult_situation` / `detect_roast_situation`, normalised Arabic, word-boundary — no new LLM call on any message); a bare "اشتم X" has no situation → `general`. `_pick()` prefers lines tagged with the detected situation, then `general` lines, then any unused line, then — pool exhausted — the least-recently-used line (deterministic, so small pools rotate in full cycles). The no-repeat window replaces the in-memory last-5: last 25 lines per (chat, category) + last 10 lines per user, persisted in `bot_state` via `brain/memory.py` (`get_recent_bank_lines` / `record_bank_line`), so it survives restarts; the in-memory last-5 is still consulted as a union. Mood is severity-weighted: `update_mood()` takes an optional `insult_bump` (default 40 = old flat bump), wired in the handler via `SITUATION_MOOD_BUMP` (family attack +60, threatened/repeated +50, sworn-at +45, called-dumb/general +40, dismissed +35, mild mock +30). **Real bug fixed on the way:** the insult regex only knew 5 tame nouns, so the commonest Egyptian insults — "يا معرص", "يا شرموط", "يا وسخ", "يا خول", "يا ابن الكلب", "يا ولاد الكلب", threats ("هقتلك") — never reached the bank at all, and the family-attacked situation could never fire; the regex now covers the usual nouns, the "يا ابن …" family vocatives, bare "امك"/"ابوك", and threat verbs (friendly "يا ابن عمي" and innocent "ابن خلدون"/"أم كلثوم" still verified clean). The LLM prompt context was NOT given the situation (skipped as optional — the bank path returns before the LLM, and the non-bank turns don't need it). in-38 stays feminine-addressed with no gender gating (flagged, same as ro-23).

**Verified:** 473 tests pass (458 baseline + 15 new in tests/test_situations_v16.py), py_compile + ruff clean. Detector/tag agreement checked: the family detector flags exactly ro-40, ro-42 and ro-44 among the user lines.

## 2026-11-26 — v1.5: ingest Seif's submitted insults, round 2

Seif added 9 more insult lines on the "قاموس شتايم بهجت" page (page total now 33: 24 round 1 + 9 round 2). All 9 were banked: 8 insulted comebacks (in-33..in-40, served 31 → 39) and 1 generic roast (ro-41, served 39 → 40). Bank total 205 → 214 raw entries (202 served). All 9 are member-safe (no family line this round — the detector flags none of them, verified independently); nothing was dropped this round — all 9 are insults, none one-word, none near-duplicates. Caveat, flagged not fixed: in-38 is feminine-addressed ("انتي ست... يا وليه") and is served at whoever insults the bot — gender gating is out of scope (same as ro-23). The round-1 dropped lines ("يا حبيبي يا مصر…", "قووم يا مصري…", "مصممممممص") stay out.

**Verified:** 451 tests pass (446 baseline + 5 new in tests/test_bank_user_ingest_v15.py), py_compile + ruff clean.

## 2026-11-26 — v1.4: ingest Seif's submitted insults into the reply bank

Seif wrote 24 insult lines on the "قاموس شتايم بهجت" page. 21 were banked: 17 insulted comebacks (in-16..in-32, served 14 → 31) and 4 generic roasts (ro-37..ro-40, served 35 → 39). Bank total 184 → 205 raw entries (193 served). New confidence level `user` for owner-authored lines (source: user-submitted) — served like verbatim/cleaned, never presented as Bahgat transcript lines; only `approximate` is never served. All user lines carry an explicit `member_safe` tag; the one outsiders-only family line (ro-40, "يا ولاد الزنوه احترمو عقولنا", Seif marked it "للبرّه بس") is `member_safe: false` and can only serve at resolved non-member targets. Dropped 3 lines: "يا حبيبي يا مصر…" (patriotic chant) and "قووم يا مصري…" (rallying line) — not insults, no pool fits them; "مصممممممص" — single-word exclamation, breaks the bank's no-one-word-padding rule and duplicates in-30's "مصمص".

**Verified:** 446 tests pass (439 baseline + 7 new in tests/test_bank_user_ingest_v14.py), py_compile + ruff clean. Detector/tag agreement checked: the family detector flags exactly the one tagged family line among the user lines.

## 2026-11-26 — v1.3 live-test fixes: insult misroute, roast targeting, savagery, download fallbacks + cookies env var

Seif's live test of v1.2 in the group (screenshot 19:53–19:56 EET) + his verdict: the bot "مش اجريسف خالص" (not aggressive at all) — he wants a savage bot ("عايزه بوت متوحش"), the insults are weak/ordinary, and he wants them all varied and creative. He warned that if we cannot fix the savagery he will take the code and make it more savage himself. Three live failures in the same test: (1) "يا بهجت انتا حمار" was answered with the search-empty line; (2) "اشتم صلاح" got the incoherent roast "عاوز يغير في القرآن يا متناك؟"; (3) the YouTube download STILL fails live post-v1.1 ("يوتيوب رافض الطلب من السيرفر").

**Root causes:**
- Bug 1 — two compounding defects: `looks_like_insult()` only knew `(انت|انته)` + insult-noun, so the Egyptian spelling **انتا** was missed and the insult fast-path never fired; then the v0.9 unknown-retry (which excluded only voice intents) ran a web search on the insult turn and ended with `_SEARCH_EMPTY`. `detect_intent()` itself was innocent — it returned `just_chat`.
- Bug 2 — the roast branch used the target name only for the member/owner gates, then picked at random from the whole 35-line pool. 25 of the 35 lines are target-specific (11 about السيسي, 4 لينا, 2 الجيش, 2 ندوش, 2 المسيحي, 1 كيسنجر, 1 كارما, 2 situational) — so a Sisi line (ro-21, "on Sisi saying Quran texts must change") could land on صلاح.
- Bug 3 — the bot-check is intermittent and has tightened since v1.1: plain-android metadata went 0/4 in the VM; `android+player_skip=configs` was the only variant that ever downloaded (Marwan 1/2 through the new chain vs 0/5 single-variant). The no-cookies chain raises the odds but cannot guarantee a download from a flagged IP.

**Fixes:**
- Insult turns never search: "انتا" added to the insult regex; new `looks_like_insult_turn()` (insult at the bot OR roast request); an insult-turn guard in `detect_intent()` before the search check; `دور`-prefix refuses an insult remainder; BOTH unknown-retry branches gated on insult turns (gating only the first would let the `elif` fire `_SEARCH_EMPTY` with no search at all).
- Roast targeting: new optional `target:` field on roast entries (absence = generic); `_pick()` filters to generic + subject-matching lines (aliases: بلحه/بلحة → السيسي) and returns `None` rather than a non-sequitur when nothing fits. Roast pool unchanged: 36 raw / 35 served.
- Savagery: prompt 6.3 → 6.4 — aggression is now the default tone ("أسلوبك الافتراضي وحشي… والرد المهذب استثناء"); `voice_check()` bans service-politeness markers (`soft_polite`, always on) and flags edgeless replies on provoked turns (`soft_reply_to_provocation`, wired in the handler for insult/roast/challenge turns); insulted pool 7 → 14 served (honest ceiling from the transcripts — the rest is family insults, already-banked lines, garble, or guests' words; further growth needs Seif's own submitted insults).
- Downloads: 5-attempt no-cookies chain (android+skip=configs → android plain → ios+skip → web+skip → android+skip with explicit format 18/bestaudio), then cookies only if configured. New `YT_COOKIES_CONTENT` env var (approved by Seif 20:03 EET, throwaway account only): the bot writes the content once to `data/youtube_cookies.txt` (0600, gitignored) and passes it to yt-dlp on the final attempt only. No account created yet, no cookies file anywhere — account creation + export is a browser job, and Seif pastes the content into Cloady himself (see docs/YOUTUBE_COOKIES.md).
- Real bug note: the old test `test_handler_roast_member_gets_person_only_line` pinned the buggy behaviour (a السيسي line served as a roast of محمد) — updated to the correct generic line "فاشلين! فاشلين!" (ro-09). One old handler test updated for the provoked regeneration (a provoked turn with an edgeless draft now regenerates once, so 2 router calls instead of 1).

**Verified:** 439 tests pass (365 baseline + 74 new), py_compile + ruff clean, VM end-to-end downloads (Rick Astley video 11.83 MB / audio mp3 3.71 MB; Marwan video 5.07 MB once, then all-5-attempts bot-check on the retry). Live confirmation still needed: 🎬/🎵 taps from Cloady, with and without cookies.

## 2026-11-26 — v1.1 live-test fixes + Bahgat reply bank (persona)

Seif's live test of v1.0 in the group (screen recording 18:05–18:10
EET) + his verdict: "مش حاسس اني بتكلم مع بهجت، مش بيتكلم زيه، مش
بيقول لزماته، ومش اجريسف زيه" — and his idea: memorized replies from
Bahgat's most famous videos, disrespectful like him. **Correction
from Seif 18:24 EET: BOTH YouTube download taps FAIL live — video
AND audio — with "فشل التنزيل هات لينك تاني". The media-player bar
in the video was NOT a successful download.** Downloads are the top
priority of this version.

**Root causes (all from the code, confirmed against the video
frames):**
- Bug 1 — downloads died before any network request: `download()`
  passed `--no-thumbnail` and `--no-subs` to yt-dlp, both REMOVED
  in newer yt-dlp (the pinned range `>=2026.7.4` installs the
  latest; 2026.11.23 has only `--no-write-thumbnail` /
  `--no-write-subs`). yt-dlp exited with "no such option:
  --no-thumbnail" on every tap, video and audio, while search
  (which never passed those flags) worked. Reproduced in the VM.
- Bug 2 — even with the flags fixed, the player/format step hits
  YouTube's bot-check on a datacenter IP. Fix: Android player
  client (`--extractor-args youtube:player_client=android`, the
  same bypass that worked for the training downloads) on
  `download()` and `resolve_query()`; format selectors now fall
  back to `best` (Android serves only format 18 + storyboards,
  no audio-only format) and the audio path uses
  `bestaudio[ext=m4a]/bestaudio/best` with ffmpeg extraction.
  Verified end-to-end in the VM (video 5.07 MB, audio mp3 3.40 MB)
  — Cloady has no MITM proxy so odds there are better, but ONLY
  Seif's live test can confirm. If it still fails, the fallback is
  a cookies file from a THROWAWAY Google/YouTube account (never
  Seif's own — his cookies file stays off the host; see
  docs/YOUTUBE_COOKIES.md). The code path (`YT_COOKIES_FILE`) is
  built; no cookies file is on the host, no account was created,
  Seif has not approved either cookies route.
- Bug 3 — the failure path hid the cause: `_run_yt_dlp` returned
  the first 300 chars of stderr (usually SSL/progress warnings).
  Now `_pick_error_detail()` prefers the last ERROR line, the
  callback logs the real error, and the OWNER gets a short
  classified hint (bot-check / too large / no format / unavailable
  / bad settings / timeout).
- Bug 4 — bare "هات مروان موسي" asked a confused question: the
  "هات" guard sent a non-media remainder to the classifier and a
  bare artist name is non-media → just_chat. Now a short bare
  artist name (≤3 words, no question, no non-media noun) after
  "هات"/"هاتلي" goes to YouTube; "هات ملخص" still falls through.
- Hardening, NOT a live bug (video worker's correction) —
  opinion challenge: the brief's "restated the theory" quote was
  the SEARCH answer's opening, mixed up with the opinion reply.
  The actual opinion reply (6:06 PM) was sharp and in-character:
  "رأيك في إيه يا غبي؟ النظرية دي مؤامرات فارغة، وأنت لسه فاكرها
  حقيقة؟ روح ركز في حياتك بدل ما تضيع". The prompt had NO stance
  instruction, so that sharpness was luck, not a guarantee — the
  machinery below makes it reliable: `looks_like_opinion_ask()` +
  a stance line in SYSTEM_BASE + an 8th few-shot pair + a
  user-role stance note in the handler; PROMPT_VERSION 6.3.
- Bug 6 — "قول نكته" (6:09 PM) and "قول اهلا في فويس نوت"
  (6:10 PM) never produced a voice note. THREE holes: (a)
  `_try_send_voice` had a single synthesis attempt — any failure
  fell back to text with only a log line; now retried once (2
  attempts) with per-attempt logging; (b) a FAILED attempt still
  recorded the 5-minute voice cooldown — the cooldown is now
  recorded ONLY on success; (c) the "قول" prefix itself was
  vetoed by the voice-words guard ("فويس" in the remainder made
  `detect_prefix_mode` return None, so `voice_only` was False and
  the turn sent text first + trailing voice) — the "قول" branch
  now runs before that guard, which stays for "دور"/"هات" only;
  (d) the unknown-retry search fired on voice turns, so the
  6:10 PM request came back as `_SEARCH_EMPTY` text — voice
  intents are now excluded from both unknown-retry branches.
  A "قول" that still doesn't go out as voice is now VISIBLE: the
  text fallback carries "الصوت مش راضي يطلع دلوقتي" (failed) or
  "الصوت استنى شوية" (cooldown), short replies only.
- Correction — the pick-list "duplicate": the frames show NO
  EL 3NWAN double. "النظام" (3:40) and "EL 3NWAN" (2:58) are
  different songs; the apparent double was EL 3NWAN at different
  positions in two separate renderings of the الخلاصه list (6:07
  vs 6:08 PM). The REAL duplicate was in the فرعون list: the same
  song twice under different uploads ("Marwan Moussa - Fr3on
  (Official Audio)" vs "MARWAN MOUSSA - FR3ON | ...", both 3:47)
  — video ids cannot catch that, so `search_query()` now also
  drops a later entry when its title tokens are a subset of an
  earlier entry's (or vice versa) with equal duration (≥3-token
  floor; video-id dedupe stays as the first pass).
- Observation, no fix — the LLM path is mildly rude to the owner
  by name in heated exchanges: the 6:06 PM opinion reply opened
  "رأيك في إيه يا غبي؟" and the 6:10 PM text joke ended "دمك
  تقيل يا سيف". The owner-never-insulted rule as implemented
  covers targeted insults and bank lines (the bank never serves
  the owner an insult/challenge line); spontaneous mild rudeness
  toward the owner in an LLM exchange is not blocked. Seif asked
  for a disrespectful bot, so this is his call, not a fix.

**Persona (Part B):** research in docs/research-persona-methods.md
(27 sources; ranked: reply bank first, Style RAG second, structured
prompt third, post-generation voice check fourth — fine-tuning
blocked on free tier, logit bias unsupported by Groq/Gemini).
New `persona/bahgat/reply_bank.yaml`: 36 lines from Bahgat's OWN
transcripts (8 videos, 4,562 segments), 22 verbatim / 11 cleaned /
3 approximate, source video marked per line; family insults
deliberately dropped (only person-only insults banked). New
`brain/reply_bank.py` fast-path (insulted > joke > opinion >
challenge > greeting; owner never served an insult/challenge line;
insult comebacks only when the insult targets the bot; opinion
lines topic-gated; rotation never repeats within 5) checked BEFORE
the LLM, no quota/LLM/bubble. Prompt rewritten (PROMPT_VERSION
6.3, 872 chars): behaviour-as-verbs, agenda, challenge line,
anti-softening, lazma as calibration not quota. New
`brain/verify.py::voice_check()` + one regeneration for replies
that come out polite/Fusha/apologetic/restating. Full dynamic
Style RAG is deferred to v1.2.

**What changed:** `brain/intent.py` (bare artist, opinion
detection, قول prefix order), `brain/prompt.py` (6.3, stance, 8
examples), `brain/reply_bank.py` (new), `brain/verify.py`
(voice_check), `tools/youtube.py` (dedupe, download repair,
cookies path, error detail), `tg/handlers.py` (bank fast-path,
opinion note, voice retry/cooldown/notes, voice-check regen,
download error hints), `persona/bahgat/examples.md` (8th pair),
`persona/bahgat/reply_bank.yaml` (new),
`docs/research-persona-methods.md` (new),
`docs/YOUTUBE_COOKIES.md` (new), `.env.example`
(`YT_COOKIES_FILE`), `.gitignore` (cookies files),
`tests/test_v11_fixes.py` (new, 27 tests).

**Tests:** 342 passed (315 baseline + 27 new), py_compile + ruff
clean, secret audit clean, no training data staged. Commit local
only — NOT pushed (no token in context).

## 2026-11-26 — v1.0 router rework: fast chat, bubble only for slow work, prefix modes

Seif's request (phone video 07:32–07:35 EET): "انا حاسس ان الموضوع معقد
عليه في التفرقه بين التدوير علي الانترنت و التدوير علي اليوتيوب و الكلام
العادي… عايزين مود ل البحث عن الانترنت و مود ل فيديوهات و صوت اليوتيوب
و مود الكلام العادي يكون اسرع شويه" — plus his own design idea (07:51
EET): start a sentence with **"دور"** → internet search, **"هات"** →
YouTube, **"قول"** → voice note. **The modes question, answered in one
line: no modes UI and no slash commands — the router does it.** The
three prefixes are deterministic tier-1 routing (hybrid routing:
rules first, classifier for the ambiguous tail — see
docs/research-intent-routing.md §§1, 6); normal chat is unchanged, and
anything that implies a mode without the prefix word still routes to
that mode.

**Root causes (all from the code, confirmed against the video):**
- Bug 1 — "شكرا يا بهجت" ran a full LLM turn behind a "بفكر يا عم،
  استنى…" bubble: `_run_llm_turn` (tg/handlers.py) started the status
  bubble unconditionally for ALL intents, and there was no fast path
  for trivial chat — every "شكرا"/"تمام"/"اهلا" paid a model call.
- Bug 2 — "دورلي علي اغنية مروان موسي الخلاصه" got no pick-list:
  `detect_intent` (brain/intent.py) classified it as `search`, not
  `youtube` — "دورلي" was in `_SEARCH_WORDS` and "اغنيه" alone was not
  a YouTube trigger — so the song ran a web search instead of YouTube.
- Latent bug, same class as v0.9: `_has()` matched *raw* keyword
  strings against normalised text, so list entries written with ى/ة
  (e.g. "دور على", "على النت") could never match — verified:
  `_has("دور علي", ["دور على"])` was False. And the YouTube search
  itself got the raw message ("دورلي علي اغنية مروان موسي الخلاصه
  @Bahgoti_bot") as its ytsearch query, request words and all.

**What changed:**
- `brain/intent.py` — `_has()` normalises the keywords too (the
  duplicate spellings are gone); new media-noun + request-verb rule
  ("دورلي علي اغنية" → youtube, "دورلي علي حادثة" → search; bare
  "اغنية"/"تراك"/"فيديو" + short message → youtube, a question about
  a song is not); "هاتلي"/"جبلي"/"نزل" are no longer standalone
  YouTube triggers (they are request verbs — "هاتلي ملخص" is a summary,
  "نزل سعر الدولار" is a price question; they only fire with a media
  noun). New `detect_fast_reply()` — instant Bahgat-voiced canned
  replies for greetings/thanks/acks/laughter/bare "بهجت" (≤3 words,
  no question, no insult, no apology, mood < 70). New
  `detect_prefix_mode()` — "دور" → search, "هات" → YouTube,
  "قول"/"قولي" → voice, checked first in `detect_intent()`, with
  guards: empty remainder, question remainder ("دور مين؟" is "whose
  turn?", not a search), media noun after "دور" (a song request),
  non-media remainder after "هات" ("هات ملخص" is a summary), and voice
  still outranks every prefix ("هات فيديو بصوتك" → voice).
- `tg/handlers.py` — fast path at the top of `_run_llm_turn`: no quota
  consumed, no LLM call, no bubble, no search; mood + history still
  updated. The status bubble is created always but `start()`ed only
  for search/youtube intents (new lazy `ensure_started()` for the
  unknown-retry search); plain chat LLM turns get the typing indicator
  only. YouTube query smoothing (`_yt_query` strips request words,
  trigger, @mention, media nouns; `_yt_query_retry` retries once with
  query + "اغنية" on 0 results); the pick-list header and stored state
  use the winning query. A "دور" prefix query is self-contained — it
  never gets the follow-up topic inheritance. "قول" prefix: the reply
  goes out as a voice note *instead of* text (new `_try_send_voice`
  helper), with the text as fallback if synthesis/send fails. Voice is
  the current Edge TTS voice — RVC is NOT wired yet.
- Tests: new `tests/test_router_v10.py` (exact video phrases + prefix
  phrases + normalisation + smoothing + handler-level fast-path and
  voice-only tests); `tests/test_status_ux_v08.py` error test updated
  to the new bubble contract (plain-chat error = normal message, no
  bubble); `tests/test_cache_quota_v06.py` quota tests switched from
  greeting probes to real questions (greetings take the fast path now).
  Full suite: 315 tests pass, py_compile + ruff clean.
- Docs: `docs/research-intent-routing.md` (§§1–5: layered/cascade
  routing, fast paths, Arabic normalisation, YouTube robustness,
  status indicators; §6: the prefix layer + hybrid-routing verdict).

**Untouched:** v0.9 one-turn search, edit-in-place status, no deletes,
quota/pacing/persona/insult rules, voice training files.


Seif's exact request (video, test group 03:24–03:27 EET): "عايز لما اقوله
يدور علي النت و يقولي استني بفكر النتيجه تطلع في نفس الرساله بتاعت
استني بفكر مش اقوله ايه الحصل عشان النتيجه تطلع" — plus "اغلب الحجات
مش شغاله صح" and, in the follow-up, "مش بيجيب فيديو اليوتيوب لا صوت
ولا فيديو صوره بس".

**Root causes (all from the code, confirmed against the video frames):**
- Search: "سيرش على النت على حادثة الوراق" matched NO `_SEARCH_WORDS`
  entry (no "سيرش", no "على النت", no "حادثه" — and the normaliser does
  NOT map على -> علي, so "دور على" missed "دور علي" too), so it fell to
  just_chat and no search ran before the first LLM call.
- The prompt TAUGHT the stall: the few-shot pair in
  `persona/bahgat/examples.md` (and the fallback copy in
  `brain/prompt.py`) answered a news question with "يا عم أنا مش جوجل،
  بس هدورلك واجيبلك الخلاصة", and the deflection line in
  `build_system_prompt` called that dodge "correct". The LLM imitated
  it, `looks_unknown` did not catch it, and the handler shipped it as
  the final reply.
- The old `_UNKNOWN_DEFLECTION` was sent AFTER a search had already run
  in every path that used it — a promise of a search no later turn
  delivers. The follow-up "ايه الحصل" then got an LLM "لسه بدور… لما
  اجيبلك الخلاصه" stall (history contained the promise), also uncaught.
- Download: v0.8's pick flow sends the choice view as a PHOTO, but the
  `yt:video`/`yt:audio` callback calls `edit_message_text` on it — the
  Bot API rejects that on a media message, the callback died before the
  download even started, and the tap went silent with the picture just
  sitting there (buttons already removed). The download-failure branch
  had the same crash, so failures were silent too.
- Clutter: the status bubble was deleted on every turn and the list
  message deleted on every pick — a "Deleted message" tombstone each
  time (visible all over the chat in the video).

**What changed:**
- `brain/intent.py`: `_SEARCH_WORDS` gains "سيرش", "على النت"/"علي
  النت", "دور على", "حادثه", "خبر", "عايز اعرف"/"عاوز اعرف"; new
  `looks_stalling()` ("لسه بدور", "لسه قالك", "اجيبلك/هجيبلك الخلاصه",
  "استنير") and "مش جوجل"/"بس هدورلك" added to the unknown markers.
- `brain/prompt.py` + `persona/bahgat/examples.md`: the news-question
  example now answers from the search ("دورت في الأخبار ومفيش حاجة
  كبيرة… [1]"); the deflection line is replaced by a ban on promising
  a search ("ممنوع تقول إنك هتدور أو لسه بتدور…"). PROMPT_VERSION
  6.0 -> 6.1 (dynamic part still < 300 tokens).
- `tg/handlers.py` — search endgame: an unanswered reply (unknown or
  stalling) after a search ran gets ONE firm retry from the grounding;
  if it still will not answer, the reply is built from the passages
  directly (`_search_fallback_reply`, extractive) or says plainly that
  the search found nothing (`_SEARCH_EMPTY`). The old deflection is
  retired. Fallback replies are never cached. A search question now
  always ends with an answer in the same turn.
- `tg/handlers.py` — edit-in-place: `_StatusMessage.finalize()`
  replaces `delete()`; the final reply, the pick-list, the choice view
  and the error line all EDIT the bubble. New `_send_final()` (first
  chunk edits the bubble, the rest go as plain messages; falls back to
  a normal message when the bubble never went up). Cache hits and quota
  denials still skip the bubble entirely. Typing indicator unchanged.
- `tg/handlers.py` — no deletes: a pick EDITS the list message into
  the text choice view (same message id, same state key). Trade-off,
  documented: the photo choice view is gone — a text message can never
  be edited into a photo, and the photo was the reason the list had to
  be deleted. The thumbnail is dropped.
- `tg/handlers.py` — download callback: new `_edit_choice_message()`
  (caption for photo choice views, text otherwise) for the progress /
  failure / done edits, plus an outer safety net so any failure edits
  the choice message into an in-character error instead of going
  silent. A tap now always produces the file or an error line.
- Tests: `tests/test_search_one_turn_v09.py` (10 new: grounding parse
  + extractive/empty fallback, one-turn answer in the bubble, empty
  search, stall-twice fallback, photo-caption download, download
  failure answers in chat, text-choice edit); `test_status_ux_v08.py`
  (finalize + error-edit, no delete), `test_youtube_list_v08.py`
  (pick edits in place, no photo, no delete),
  `test_cache_quota_v06.py` (search-ran turns retry once now),
  `test_intent.py` (سيرش keywords + stall detection).
- 295 tests pass (285 + 10 new), py_compile + ruff clean on the bot
  code (the 21 ruff hits in `training/colab/*.ipynb` are pre-existing,
  not touched here).
- NOT verified live in this VM: the yt-dlp download itself from Cloady
  (the callback died before `download()` was ever called, so the
  format/cookies question is still open — the search calls prove
  yt-dlp reaches YouTube from Cloady, the download is the untested
  part). First live test after deploy: song → pick → tap فيديو (video
  arrives) and tap صوت (audio arrives). If the download fails live,
  the next step is a cookies file on the host — Seif already supplied
  one for the voice downloads; do NOT reuse it without asking him.

## 2026-11-26 — v0.8 live status + YouTube pick-list (deploy target: Cloady, no card)
- **Live status message (`tg/handlers.py`, `_StatusMessage`).** Long turns
  now show ONE editable status bubble (OpenClaw-style progress draft —
  research in `docs/research-bot-ux.md`): sent with
  `disable_notification` so the group isn't pinged, edited in place as
  the stage changes, a braille spinner (⠋⠙⠹…) cycling every 1.5 s
  while a stage runs long, and deleted when the final reply lands — and
  in a `finally` block on errors — so no stale bubble is ever left
  behind. Never raises: if the bubble can't be sent, the turn continues
  without it. Skipped entirely for instant paths (cache hits, quota
  denials). The existing `_typing_loop` chat action is kept alongside
  it. Stage lines are Bahgat-voiced Egyptian dialect: "بفكر يا عم،
  استنى…" (thinking) → "بدورلك على النت، يا عم…" (searching) →
  "بجيبلك من يوتيوب، استنى…" (YouTube) → "بنزلها لك دلوقتي، استنى
  شوية…" (downloading).
- **YouTube pick-list (MIRAL-style).** `tools/youtube.py` gains
  `search_query(query, limit=5)` (yt-dlp `ytsearchN:` + `--flat-playlist`,
  same URL/option validation as `resolve_query`). Text queries now
  return up to 5 results shown as "• نتائج البحث ← <query>" with
  numbered full titles and one inline button per result (button text
  truncated to 40 chars). New callback `yt:pick:<index>` (index only —
  `callback_data` is 1–64 BYTES, values resolve server-side) renders
  the وعد-style choice view: the video's thumbnail as a photo message
  with title + duration caption and the two buttons "🎬 فيديو" /
  "🎵 ملف صوتي" (falls back to editing the list in place if the
  thumbnail can't be sent — a text message can't be edited into a photo
  via editMessageMedia). Same requester-only guard, 10-min TTL and
  callback dedup as the existing YouTube callbacks. One result skips
  the list and goes straight to the choice view; a pasted YouTube URL
  does the same; zero results answers in character ("دورت يا عم ومفيش
  حاجة بالاسم ده، جرب اسم تاني.").
- Tests: `tests/test_status_ux_v08.py` (5 tests: stage lines, bubble
  lifecycle + idempotent delete, send-failure never raises, spinner
  cycling, bubble deleted when the LLM turn raises) and
  `tests/test_youtube_list_v08.py` (10 tests: duration/button helpers,
  list text + keyboard + 64-byte callback cap, pick parsing,
  search_query parsing + validation, pick photo view + state re-keying,
  requester-only guard, expiry, thumbnail-failure fallback).
- 285 tests pass (270 + 15 new), py_compile + ruff clean.
- Not verified live in this VM: yt-dlp is not installed here, so the
  real `ytsearch5:` call was exercised only with a mocked runner; the
  Cloady Docker image installs it from requirements.txt
  (yt-dlp>=2026.7.4). First live test after deploy: ask for a song and
  tap through list → photo choice → download.

## 2026-11-26 — v0.7e Cloady deploy + search follow-up fix (deploy target: Cloady, no card)
- **Deploy moved Render → Cloady.** Render's "Add Card" modal blocked the
  free deploy on Seif's brand-new account (account-level anti-fraud check;
  Render's docs say no card, but the check fires anyway and no config
  bypasses it). Cloady free workspace (0.5 vCPU / 1 GB RAM / 5 GB SSD,
  Germany EU1, no card, no expiry) now hosts the bot; deploy went LIVE
  2026-11-26 02:03 EET and the bot replied in the test group 02:10 EET.
- `docker-compose.yml`: bind mount `./data:/app/data` rejected by Cloady
  ("volumes must mount a declared named volume") — now a declared named
  volume `bahgat-data:/app/data` (also the persistence layer: memory
  survives redeploys, unlike Render free). `env_file: .env` dropped (the
  platform injects env vars; a missing .env would fail the parse),
  `cpus: 1.0` → `0.5` to stay inside the free tier. `ALLOWED_CHAT_IDS`
  deliberately left unset in Cloady per Seif's call — the bot answers in
  any group it is added to.
- **Search follow-up fix (`tg/handlers.py`, `_search_query`).** Live bug:
  Seif asked about the Waraq incident, then "ايه الحصل" — the bot
  searched the literal follow-up and answered with song lyrics about
  "عمره ما غنى ولا عرف الهوى". Short follow-ups (<= 4 words) now inherit
  the most recent substantive user turn from history, so the query keeps
  the topic. Both search call sites (search intent + unknown-retry loop)
  use it. Tests: `tests/test_search_followup_v07e.py` (5 tests).
- **Intent keywords (`brain/intent.py`).** Two more live misses from the
  same session: "ايه الحصل" (without اللي) did not match `_SEARCH_WORDS`
  (only "ايه اللي حصل" was there), so follow-ups fell to just_chat and
  only got searched via the unknown loop; "عايز اغنيه" did not match
  `_YOUTUBE_WORDS`, so a song request never offered the video/audio
  choice. Added "ايه الحصل"/"ايه حصل" to search words and
  "عايز اغنيه"/"عاوز اغنيه"/"عايز فيديو"/"عاوز فيديو" to YouTube words.
  Tests in `tests/test_intent.py`.
- Test fix: `test_gemini_skipped_when_daily_requests_at_cap` seeded usage
  by UTC date while the router keys Gemini by Pacific date — it passed at
  23:44 UTC and failed at 00:18 UTC the same night. Now seeds by Pacific
  date, like the router.
- 268 tests pass (263 + 5 new), py_compile + ruff clean.

## 2026-11-25 — v0.7d Render free web service conversion (deploy target: Render, no card)
- `render.yaml` converted from Background Worker to **free Web Service**:
  `type: web`, `plan: free`, `numInstances: 1`, `env: docker` (Dockerfile
  runtime — the image carries ffmpeg, which the native Python env lacks),
  `region: frankfurt`, `dockerfilePath: ./Dockerfile`,
  `healthCheckPath: /healthz`. Render Free does NOT cover workers
  (docs.render.com/free), so the old worker config could never deploy free.
- `DROP_PENDING_UPDATES=false` is now a literal env var in `render.yaml`
  (messages sent while the bot slept are delivered on wake — Telegram
  holds updates 24h — instead of discarded). Secrets stay out of the file:
  `TELEGRAM_BOT_TOKEN` / `GEMINI_API_KEY` / `GROQ_API_KEY` /
  `NVIDIA_API_KEY` are declared with `sync: false`, so Render asks for them
  in the dashboard; `OWNER_ID=1415214630`,
  `ALLOWED_CHAT_IDS=-1005812444791`, `LOG_LEVEL=INFO` are literal values.
- Verified the $PORT path end to end: `main.py` starts the v0.7c health
  server (tg/health.py) BEFORE `run_polling`, so the Docker CMD
  `["python", "main.py"]` binds `0.0.0.0:$PORT` at boot; the heartbeat file
  is first written in `post_init`, so `/healthz` turns 200 within seconds
  of startup (brief 503 in the first seconds is normal — documented in
  DEPLOY.md). `resolve_port()` reads Render-injected `$PORT`, default 8080.
  No code change was needed for the port; only a `main.py` comment now
  names Render free alongside Northflank.
- `docs/DEPLOY.md` rewritten as a complete Render deploy checklist in
  Egyptian Arabic: free-tier trade-offs stated plainly (sleeps after 15 min
  idle; SQLite wiped on every redeploy/restart — memory loss is EXPECTED on
  this first deploy; 750 free hours/month = exactly one service 24/7),
  prerequisites, exact env-var table, dashboard steps (New → Web Service →
  Docker → Free → 1 instance), verification (logs + GET /healthz),
  cron-job.org pinger setup (every 10 min, free, 1-min granularity — better
  than UptimeRobot's 5-min GET-only), live-test messages for the test group
  (-1005812444791), and the next step flagged, NOT built: Turso/R2
  persistence (docs/research-deploy-state-persistence.md).
- Tests: **263 pass in .venv, py_compile clean, ruff clean.** Smoke tests:
  health server binds `$PORT` in a subprocess (`/healthz` 200 fresh,
  `/health` alias 200, 503 stale); `import main` + `build_application()`
  builds 6 handlers; `DROP_PENDING_UPDATES=false` parses to False.
  Docker image build NOT verified — docker is not installed in this VM.
- Open blockers (not done here): (1) no GitHub repo exists yet — Render
  builds from a GitHub repo on branch main; (2) no Render account yet
  (free, no card); (3) Seif must paste his 4 keys into the Render
  dashboard himself (Vault keys are not available to Render). Nothing was
  deployed; no account created; no credentials touched.

## 2026-11-25 — v0.1 scaffold
- Modular scaffold: config-driven persona/providers/rules, plugins, multi-LLM router stub, SQLite memory schema, Docker.
- Training video lists compiled (voice vs style). Audio cleanliness NOT verified yet.
- Waiting: Telegram bot token (secure link sent), owner ID, test group.

## 2026-11-25 — v0.2 core + tools (no token yet, untested live)
- Brain router: Gemini -> Groq -> OpenRouter, OpenAI-compatible, auto-fallback on error.
- Memory: SQLite per-member (mood, grudge, notes), recent 12 messages context.
- Mood: insult +40, praise -20, voice when asked / mood>=90 / random 12%.
- Intent from normal talk (no slash commands): search / youtube / voice / just_chat.
- Tools: DuckDuckGo search + page fetch, yt-dlp 480p / mp3 with 50 MB limit, Edge TTS ar-EG-ShakirNeural -> ogg voice note.
- Handlers: reply only on mention / "بهجت" / reply-to-bot, owner-only control phrases for Seif.
- Tests: insult rules + mood + intent pass locally (pytest not installed, run via python -c).
- Still blocked: Telegram token, owner ID, test group, Gemini/Groq keys — needed for live test + deploy.

## 2026-11-25 — Telegram connected, bot verified
- Token submitted via secure link and verified with getMe: @Bahgoti_bot, id 9106462211, first name بهجت.
- Connector doc + helper at ~/workspace/custom-connectors/custom.telegram/ (getMe / getUpdates / sendMessage).
- getUpdates empty — bot not in any group yet.
- Known: can_read_all_group_messages is false, so bot must be admin in test group (or privacy disabled in BotFather) to see plain "بهجت" messages.
- Still waiting: owner ID, test group link, Gemini/Groq keys.

## 2026-11-25 — Gemini connected and verified
- Gemini key submitted, models list works via OpenAI-compatible endpoint.
- gemini-3-flash-preview generates replies (verified). Primary model updated to it.
- gemini-2.5-flash/pro retired (404), gemini-3.1-pro-preview free-tier quota 0 (429).
- Still waiting: Groq key, adding @Bahgoti_bot as admin to test group.

## 2026-11-25 — Groq connected and verified
- Groq key submitted, models list works, openai/gpt-oss-120b generates Egyptian Arabic replies.
- Groq needs a browser User-Agent header, otherwise Cloudflare returns 403 error 1010.
- Brain is now complete: Gemini (gemini-3-flash-preview) primary, Groq (gpt-oss-120b) fallback.
- Still waiting: adding @Bahgoti_bot as admin to the test group, then live test + deploy.

## 2026-11-25 — v0.3 code review + brain hardening (P0, from professional research)
- Router v3: classified retries (only 408/429/5xx), exponential backoff + full jitter, honour Retry-After, circuit breaker (3 failures -> OPEN 60s), SQLite quota table (skip exhausted provider until midnight UTC), token counting, simple->Groq first / hard->Gemini first, temperature per intent (search 0.25, chat 0.85).
- Prompt v3: dynamic system prompt assembly (role, objective, constraints early, memory/mood/search/style, few-shot escape hatch), user text wrapped in <user_message> tags, guardrails in code not prompt.
- Verification in code: family-insult enforcement for members, banned AI phrases, HTML escaping, 4096-char split on sentence boundaries.
- Telegram reliability: dedup on update_id (INSERT OR IGNORE first), per-chat rate limit (1 msg/s, 20/min/group), YouTube video/audio inline buttons (yt:video / yt:audio) instead of pretending to download, callback answers.
- Memory schema: processed_updates, provider_usage, pinned_facts, outbox tables.
- Added .gitignore (.env, data/, *.db), tenacity in requirements (documented, hand-rolled retry kept for now).
- Tests: verify, prompt, router circuit breaker — all pass locally.
- Still open (from research, P1/P2, not yet built): LLM tool-calling replacing keyword intent, structured BotPlan, LLM-as-judge for search answers only, RAG over Bahgat transcripts for style, rolling summarisation, /stats owner command, CI with ruff/mypy.

## 2026-11-25 — v0.4 code review fixes (C1-C11, M1-M12)
- Router v4: max_completion_tokens=4000, reasoning_effort=low (Groq), thinking low (Gemini), temp 0.7 chat / 0.25 search, one client per provider + close() on shutdown, no raw exception leak to group (log only).
- Search: resolve DDG uddg redirects, raise_for_status, content-type check, Lite fallback, realistic UA.
- Search-when-unknown loop: if reply says "مش عارف" and no search ran, search once and retry with results.
- YouTube: inline video/audio buttons now actually download in to_thread, per-request UUID folder, --no-playlist --max-filesize 50M, capture real filepath, delete after send.
- Insult enforcement: post-filter in code, plus owner commands normalised and checked before trigger gate, mute/clear-memory owner commands.
- Memory/mood: history fetched BEFORE inserting current message, assistant stored with bot id, mood time-decay -10/hour, prune messages to last 200/chat, index on messages(chat_id,id).
- Blocking work: yt-dlp in to_thread, voice split at sentence boundaries, file handles closed, files deleted.
- Config: persona.yaml + examples.md now loaded at startup, OpenRouter removed (no key, never ran), providers.yaml honoured, render.yaml (Background Worker) + docs/DEPLOY.md + .dockerignore added.
- Tests: 17 tests pass in .venv (verify, prompt, router, intent, insult rules). System pip install fails (PEP 668) — use .venv, documented in DEPLOY.md.
- Still open (P1/P2, not built yet): LLM tool-calling replacing keyword intent, structured BotPlan, LLM-as-judge for search only, RAG over Bahgat transcripts, rolling summarisation, /stats owner command, CI ruff/mypy.

## 2026-11-25 — v0.4b search fix (live verified)
- Search rewritten from httpx to urllib: httpx mis-parses NO_PROXY in this VM and fails SSL through the egress proxy. Live test now returns 5 results with real URLs (not DDG redirects) and fetches pages.
- Split-message hard-split fix: long single sentences now split at 4000 chars (test was failing).

## 2026-11-25 — v0.5 review rounds 2–6 (five independent reviews, deduplicated)
Five independent review rounds were run against v0.4 and their overlapping findings
deduplicated; v0.5 implements the highest-priority fixes. **127 tests pass in .venv
(pytest tests/ -q), py_compile clean, ruff check passes. `import main` + `build_application()`
verified (6 handlers).**

### Fixed — security (round 2)
- SSRF in search: `validate_url()` — https only, hostname resolved and rejected if
  private/loopback/link-local (169.254/10/172.16/192.168/::1/fc00), redirects re-validated
  (max 3), body capped ~1 MB. Note: `ipaddress.is_private` is NOT used — in this VM the
  egress proxy returns 198.18.0.0/15 for ordinary public hosts, which it flags.
- yt-dlp argument injection: host allowlist {youtube.com, www.youtube.com, youtu.be,
  music.youtube.com}, leading `-` rejected, `--` inserted before the URL, yt-dlp pinned
  `>=2026.7.4`. Plain text is resolved via code-built `ytsearch1:` first, never passed raw.
- Prompt injection layers: sandwich guardrail after the user message, search results
  labelled untrusted data with `[n]` citations required, grudge/notes never in the system
  prompt (moved to a user-role `[MEMORY]` block, instruction patterns stripped at write
  time), output filter for system-prompt/owner-id/key leakage in `verify.py`.
- Group allowlist `ALLOWED_CHAT_IDS` (env, comma-separated; empty = allow all + startup
  warning, because the test group's numeric chat id is not known yet — only the invite
  link is). Checked before any LLM/search/voice call.
- Real insult-target resolution via `get_chat_member` + `insult_level()` wired into prompt
  AND verify; target == owner (1415214630) is never insulted.

### Fixed — quotas / cost (rounds 2, 5, 6)
- Durable SQLite per-user-per-group daily budget: 30/user/day, 150/group/day, checked
  before LLM/search/voice.
- Groq TPM-429 (ban for Retry-After only) vs TPD-429 (ban to midnight UTC) distinguished;
  Groq-first routing for everything with Gemini reserved (hard cap 15 Gemini req/day,
  stopped before 429); `openai/gpt-oss-20b` added for simple chat.
- Per-chat in-flight lock (one LLM call per chat); typing renewed every 4s; output cap
  400–600 tokens for chat (600 search), Groq `max_completion_tokens` 1500–2000, Gemini 4000,
  `include_reasoning=False` for Groq, `reasoning_effort="low"` both providers.
- Token estimate fixed to `len//2` (len//3 undercounted Arabic ~2x).

### Fixed — brain (round 3)
- Arabic normalisation in intent (diacritics stripped, أ/إ/آ→ا, ة→ه, ى→ي); verb patterns
  (مين كسب/كسب مين/كام/امتى/فين/بكام, هاتلي/هاتيلي/جبلي/شغلي) and insult patterns
  (انت حمار/غبي/كلب/عبيط); `looks_like_praise` implemented (was hardcoded False).
- Real few-shot examples: `persona/bahgat/examples.md` now has 7 real User/Bahgat exchange
  pairs (person-only insult, correct deflection, search answer with [1] citation, praise,
  song request); `persona.yaml` is now wired into `build_system_prompt` (was dead config).
- Grounding v2: top 3 results fetched in parallel, youtube/tiktok skipped for facts, best 2
  kept with URLs, `[n]` citations required, unknown markers widened, in-character
  deflection when still ungrounded.
- Speaker-tagged history (`[name]: text`); single mood-decay mechanism (time-based on read,
  persisted — per-message −5 removed); one canonical `FAMILY_WORDS` list shared by
  `core/rules.py` and `brain/verify.py` with hamza normalisation; `check_reply` rewrites
  silently instead of appending meta-commentary naming the owner/rule.

### Fixed — YouTube / voice (rounds 2, 5, 6)
- Callback state keyed (chat_id, message_id, requester_id), TTL 10 min, non-requester clicks
  rejected, buttons disabled after first click, callback ids deduped, Semaphore(1) per group,
  non-URL query resolved via `ytsearch1:` with title/duration/size shown before download,
  `youtube_files` file_id cache so repeats re-send by file_id.
- Voice: random 12% → 5% only if reply <200 chars, never forced on mood>=90, cap 1/user/5min,
  ffmpeg via `asyncio.to_thread`, Edge TTS timeout 15s, text sent before voice.

### Fixed — reliability / ops (rounds 2, 4, 5, 6)
- `run_polling(timeout=30, allowed_updates=["message","callback_query","chat_member",
  "my_chat_member"], drop_pending_updates=True, bootstrap_retries=-1)`.
- Schema created once at startup (`init_db()`), `processed_updates` pruned >48h, startup disk
  sweeper for `data/downloads` + `data/voice` >1h.
- Telegram `RetryAfter` caught explicitly (sleep `retry_after`, retry once, never send a
  generic fallback on rate limit); structured JSON log line per LLM call (provider, model,
  latency, tokens in/out, reasoning, finish_reason, retries, status); owner-only `/stats`
  (provider usage today, remaining estimates, per-user counts).
- `setMyDescription`/`setMyShortDescription` parody text at startup from `rules.yaml`;
  `my_chat_member` handler (parody+privacy note on add, purge chat data on remove);
  owner-only `/reload` for persona/examples/rules (provider changes still need restart —
  `router.reload_config()` does not exist).
- `.gitignore` now ignores `.venv/`; `requirements-dev.txt` split out (pytest, pytest-asyncio,
  ruff); yt-dlp pinned; unused tenacity/google-genai/httpx removed; `providers.yaml`
  timeout/retries/log_level honoured (or the fields documented); Dockerfile non-root `USER app`
  + HEALTHCHECK (heartbeat file) + `PYTHONUNBUFFERED=1`; `render.yaml` `numInstances: 1`.
- Docs drift fixed: README OpenRouter line, status, and `/reload`/member-list claims now true;
  ARCHITECTURE.md rewritten short and true (plugins marked aspirational/stub, pinned_facts/
  outbox marked dead tables); DEPLOY.md gains ALLOWED_CHAT_IDS, Render Free SQLite-wipe
  warning, single-instance warning, webhook-secret note; `.env.example` cleaned
  (OPENROUTER_API_KEY / RENDER_EXTERNAL_URL removed, ALLOWED_CHAT_IDS added).
- **Pre-existing blocker found and fixed during v0.5:** the local `telegram/` package
  shadowed the installed python-telegram-bot library, so v0.4 could never have run as-is
  (`ImportError: cannot import name 'InlineKeyboardButton'`). Local package renamed to
  `tg/`; `from telegram import …` now always means the installed library.

### Deferred (explicitly NOT built in v0.5, with reason)
- Full RAG over Bahgat transcripts — needs audio download + Whisper transcription + manual
  cleanup (~1 day); keyword/prompt/grounding fixes were worth more first; do after live test.
- Voice-clone training (RVC/GPT-SoVITS) — needs Seif's explicit go/no-go on deepfake risk
  (impersonation/right-of-publicity); flagged, NOT trained.
- LLM-as-judge for search answers — useful but second-order once citations + grounding v2 exist.
- Structured BotPlan via LLM classifier — keyword intent + the v0.5 fixes are sufficient for v1;
  revisit if intent misses persist in live testing.
- Postgres migration — Render Free wipes SQLite on redeploy/restart; documented in DEPLOY.md
  (Neon free Postgres / Oracle Always Free VPS path + startup DB backup note) instead of
  migrating now, before the first live test proves the bot works.
- Full plugin-system rewrite — plugins/ stays a stub; service-layer extraction likewise deferred.
- PTB v22 upgrade — evaluated only: the venv already has PTB 22.8 and tests pass with it
  (`filters.ChatType.GROUPS` works on 21.x and 22.x); requirements still pin 21.11.1, upgrade
  is a one-line decision for deploy time.
- CI workflow — DONE after all: `.github/workflows/ci.yml` (ruff + pytest) was added in v0.5.

### Still blocks the live group test
- Seif must add @Bahgoti_bot as admin to the test group
  (https://t.me/+RN2Fksh8-KU3NWI0) so plain "بهجت" messages are delivered
  (can_read_all_group_messages is false).
- Seif must confirm the test group's numeric chat id so `ALLOWED_CHAT_IDS` can be set
  (currently empty = allow all, with a startup warning).
- Seif must paste the same three keys (Telegram token, Gemini, Groq) into Render env vars
  himself — Muse's Secure Vault keys are NOT available to Render.
- Unverified in this VM: real yt-dlp download/resolve (yt-dlp not installed here — only
  mocked), real Edge TTS + ffmpeg voice (edge_tts not installed here), live LLM calls
  against the new caps, `get_chat_member` with a username string, heartbeat/HEALTHCHECK
  observed live. The VM's `NO_PROXY` env breaks httpx (bracketed IPv6 entries) — smoke
  tests need a clean env; does not affect Render.

## 2026-11-25 — v0.7 fair-share quota core (brain/memory.py only)
Dynamic quota: the fixed caps are gone (100/user/day, 1500/group/day,
owner exemption — all retired, with `USER_DAILY_LIMIT` /
`GROUP_DAILY_LIMIT`, `group_pool_remaining()`, and the "user daily
limit reached" reason). Capacity C is now computed live from provider
budgets (`compute_pool_remaining`: per entry replies = min(RPD left,
TPD left / avg tokens per reply), pool = sum x 0.8 planning haircut)
and divided among the ACTIVE users by weighted max-min fair sharing
(docs/research-quota-fairshare.md, docs/research-quota-capacity.md).

### The scheme
- Config (`config/providers.yaml`, `quota:` section; mirrored as
  `QUOTA_*` module defaults in `brain/memory.py`): owner_weight 1.25,
  member_weight 1.0, active_window_days 7, saturation_threshold 0.50,
  borrow_multiple 2.0, floor_replies 20, planning_haircut 0.20.
- Active set: `last_triggered` table — a user is active if they
  triggered the bot within the rolling 7 days (returning users are
  instantly active; empty set counts as just the triggering user).
- Per-request decision (`check_and_consume_quota`, recomputed every
  turn): share = C x w / sum(w); ceiling = 2x share. Group hard
  ceiling first (used_group >= C -> "group daily limit reached"), then
  the floor (used_user < 20 -> always allow), then the binding limit:
  share when saturated (group used >= 50% of C), else the 2x ceiling
  ("fair share reached"). Already-consumed replies are never clawed
  back. `fair_share_info()` exposes the same numbers without consuming
  (for /stats). The owner is NO LONGER EXEMPT — he gets the 1.25
  weight instead (an exemption would break sum-to-C and let one user
  drain the pool). Capacity unknown (None) fails OPEN with a logged
  warning — a chat bot must not go silent over a missing number.
- Tokens/reply: `token_stats` table, EWMA lambda 0.15 per intent
  (chat/search, anything else bucketed as chat), cold-start blend
  avg = (30x1050 + total) / (30 + n), clamped >= 50. Only successful
  replies are recorded — cache hits and failed calls must never call
  `record_reply_tokens()`.
- Capacity rules: NVIDIA NIM is EXCLUDED from the planning pool
  entirely (trial terms: testing/evaluation only); disabled /
  exhausted entries contribute 0; OpenRouter entries share ONE
  account-wide 50 RPD cap (smallest cap among them, summed usage,
  counted once). Empty entries -> pool 0.0 (fail-closed; no fixed
  fallback number exists in the quota path).
- Degrade mode (`update_degrade_mode` / `get_degrade_mode`, persisted
  in `bot_state`): enter "cheap" when pool/full < 20%, exit only when
  > 30% (dead band), 15-min dwell once a mode is entered.

### NVIDIA NIM model corrected (live verification 2026-11-25)
Seif submitted the NVIDIA NIM key; verified live (models list returns 30
models, key works). BUT the v0.6-configured model
`nvidia/nemotron-3-super-120b-a12b` is RETIRED — it returns HTTP 410 Gone
and is not in the models list. The NIM entry in `config/providers.yaml`
now uses the verified working replacement
`nvidia/nemotron-3.5-super-vl-120b-a12b` (tested: replied in Egyptian
Arabic, 215 total tokens). Also verified NOT to use: `google/gemma-3-12b-it`
(404 on chat despite being listed) and
`nvidia/nemotron-3.5-lightning-30b-a3b` (returns None content —
reasoning-only with default params). Connector doc
`~/workspace/custom-connectors/custom.nvidia-nim/CONNECTOR.md`, helper
`bin/nim.py`. The key lives in the Secure Vault; at deploy time Seif
still pastes it into Render env vars himself (Vault keys are not
available to Render).

### Worked examples (C = 1,500)
| Active | Owner share | Member share | Borrow ceilings (owner / member) |
|---|---|---|---|
| owner + 2 (W=3.25) | 577 | 462 | 1,154 / 924 |
| owner + 14 (W=15.25) | 123 | 98 | 246 / 197 |

### Gemini timezone trap
Gemini RPD resets at midnight Pacific (08:00 UTC), NOT midnight UTC
like Groq/OpenRouter. The router workstream keys Gemini usage rows by
Pacific date; `memory.py` itself stays date-agnostic (it consumes the
entries snapshot it is handed).

### Router + handler integration (landed same day)
- Router: `_date_for(family)` keys Gemini usage rows by Pacific date
  (see trap above), all other families UTC; `pool_snapshot()` /
  `pool_remaining_replies()` expose the live pool; `chat(cheap_only,
  intent)` filters to cheap tiers {groq-20b, cerebras-120b,
  gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-gemma} — never
  gemini-3-flash-preview or nvidia-nemotron as primary; successful
  replies record EWMA tokens exactly once (`record_reply_tokens`).
  Provider order, 10s pacing, insult rules, persona untouched.
- Handlers: triggers recorded after the trigger gate (cache-hit turns
  count as activity); quota computed once per turn from live pool +
  active set + `quota:` config; hysteresis degrade replaces the old
  single 20% low-pool threshold (notice only on transition into cheap,
  ≤ once/hour/chat); `/stats` rewritten on live data — pool remaining
  in replies, per-user fair share used/limit, active users, avg
  tokens/reply (chat/search), per-provider remaining, cache hit rate,
  degrade mode + dwell hold. No more hardcoded "150k Groq" / "15 Gemini".
- Known follow-up (not fixed in v0.7): `_classify_429`'s TPD ban still
  computes seconds-until-midnight-UTC, so a Gemini TPD ban lasts until
  UTC midnight, not Pacific midnight.

### Tests
New `tests/test_fairshare_v07.py` (capacity formula, EWMA, active
set, fair-share math, hysteresis, retired surface) + new
`tests/test_router_handlers_v07.py` (Pacific-date keying, pool
snapshot, cheap-only filtering, EWMA-once-per-success, trigger
recording, hysteresis wiring, /stats) + the old fixed-cap tests in
`tests/test_cache_quota_v06.py` / `tests/test_memory_v5.py` /
`tests/test_pacing_v06b.py` replaced with fair-share equivalents.
**255 tests pass in .venv** (was 192), py_compile clean, ruff clean.

## 2026-11-25 — v0.6b: no hourly cap, 10s per-user reply pacing (Seif's call)
- **20/hour burst cap REMOVED** (`brain/memory.py`: `check_and_consume_quota`
  no longer takes `limit_hourly`, no hourly enforcement). Quota is now only
  100/user/day + 1,500/group/day, owner exempt. `hourly_usage` is still
  written (per-hour counts for /stats) but never blocks.
- **Anti-spam is now pacing, not dropping** (`tg/handlers.py`):
  `USER_REPLY_PACE_SECONDS = 10.0` — one reply per user per 10s in a chat.
  A second message is QUEUED: the handler waits until 10s have passed
  since that user's last reply was sent, then runs the turn. The timestamp
  is recorded when the reply is SENT (finally block), not when the message
  arrived, so replies stay >= 10s apart even when the LLM turn takes
  seconds. Replaces the old 3s drop-cooldown ("استنى ثانية" + drop).
  Pacing is per (chat, user); other users are unaffected.
- Tests: 192 pass in .venv (was 187), py_compile clean, ruff clean. New
  tests/test_pacing_v06b.py (pace math, per-user isolation, quota signature
  has no hourly parameter); burst-cap tests rewritten to assert 25 calls
  in one hour are all allowed.

## 2026-11-25 — v0.6 quota expansion (100 replies/user/day, FREE only, within ToS)
Two parallel workstreams (router/providers + prompt/cache/quota), integrated and
verified by the coordinator. **187 tests pass in .venv (pytest tests/ -q, ~15s),
py_compile clean, ruff check passes. `import main` + `build_application()` verified
(6 handlers).** No provider accounts or keys were created; nothing was deployed.

### The hard constraint (from research, non-negotiable)
Multi-account / multi-project rotation to multiply ONE provider's quota is an
explicit ToS violation (Groq AUP bars registering multiple accounts or
orchestrating usage between organisations; Google APIs ToS §2(d) bars
circumventing API limitations; OpenRouter governs capacity globally, so extra
accounts gain literally zero). The bot pools DIFFERENT providers only, one key
per provider, each inside its own published limits. No custom model was built:
no free hosted model has an unlimited quota, and a fine-tune does not raise
limits (limits are GPU-hours, not model quality).

### Fixed — the v0.5 Groq bug (efficiency research)
- `provider_usage` was keyed by provider name ("groq"), so the 150k daily token
  cap was counted COMBINED across gpt-oss-120b + gpt-oss-20b. Groq limits are
  PER MODEL (200k TPD each). Usage is now keyed per (provider, model, date):
  runtime migration in `brain/router.py` (`provider_usage_v2`, old rows preserved
  with `model=''` and counted conservatively toward every entry of that family).
  Caps are now 180k tokens/day per Groq model (safety margin under the real 200k).

### New providers (all OpenAI-compatible, base-URL swap; all OPTIONAL)
- Groq: added `qwen/qwen3.8-27b` as a third Groq tier (strongest Arabic of the
  three Groq models).
- Cerebras: `gpt-oss-120b`, base `https://api.cerebras.ai/v1`, env
  `CEREBRAS_API_KEY`, cap 1M tokens/day. Free-tier status CONFLICTS across
  sources (permanent 1M/day vs card-gated $5/30-day trial since Oct 2026) — on
  401/403/404 the entry is disabled in-memory with a server-side log only, and
  the router continues. Do NOT count its ~950 replies/day until console
  verification.
- NVIDIA NIM: `nvidia/nemotron-3-super-120b-a12b`, base
  `https://integrate.api.nvidia.com/v1`, env `NVIDIA_API_KEY`, cap 10,000
  req/day. FLAG: NIM trial terms say testing/evaluation only, NOT production —
  it is an overflow tier, never the primary (comment in code + providers.yaml).
- OpenRouter :free: env `OPENROUTER_API_KEY`, cap 50 req/day unfunded, models
  `google/gemma-4-31b-it:free` / `nvidia/nemotron-3-super:free`, with required
  `HTTP-Referer` + `X-Title` headers. Emergency spare only (last in every order).
- Gemini (same `GEMINI_API_KEY`, no new key): added `gemini-3.5-flash-lite` and
  `gemini-3.1-flash-lite` (500 RPD each) and `gemma-4-31b-it` (14,400 RPD,
  TPM-managed: in-router rpm guard ~9s between calls, ~7 calls/min sustained).
  `gemini-3-flash-preview` demoted to LAST resort, cap 20 RPD.
- Routing: Tier 1 simple chat Groq-20b → Qwen → Cerebras → NIM → Flash-Lite;
  Tier 2 hard/search Groq-120b → Qwen → Cerebras → Flash-Lite → Gemma →
  Gemini-Flash last; OpenRouter last everywhere. Least-used provider first
  within a tier (most remaining daily budget wins); Retry-After honoured per
  entry; exhausted providers skipped. Missing key = entry skipped silently
  (startup log lists enabled/disabled entries); `NO_KEYS_MSG` only when no
  provider has any key.

### Prompt compression + Groq prefix caching
- `PROMPT_VERSION = "6.0"`. Static prefix is now byte-identical across calls:
  `SYSTEM_BASE` (634 → 448 chars, −29%, all hard rules kept) + hard rules +
  `[STYLE EXAMPLES]` (ALL 7 few-shot pairs — they are static text, so they
  belong in the prefix). Dynamic blocks ([PERSONA CONFIG], [MEMBER], [MOOD],
  [INSULT RULE], [SEARCH RESULTS], deflection line) come AFTER, hard rules
  repeated at the very end. Verified: static prefix 1,444 chars / 722 tokens
  (len//2), identical for two different members/moods/search texts.
- Measured: full system prompt no-search 1,853 chars / 926 tokens (len//2);
  first call ~1,600 tokens, repeat calls pay only the dynamic part (~900 tokens
  incl. history/memory) once the 722-token prefix is a Groq cache hit
  (cached tokens do not count toward Groq rate limits).
- History 8 → 6 messages in the LLM turn; search excerpt stays capped at 800
  chars.

### Exact-match response cache
- New `response_cache` table (normalised_text, intent, mood_bucket, reply,
  created_at; TTL 1h; pruned to last 500 rows). Normalisation reuses
  `core.rules.normalize_arabic`. Mood bucket calm <70 / angry ≥70.
- Greetings/small-talk only — NEVER for search / YouTube / voice / insults /
  grudge replies / replies with citations. Cache is checked BEFORE quota:
  hits cost 0 tokens and 0 quota, are logged (`cache_hit=true`), and counted
  in `get_cache_stats()` (hits/misses/hit_rate, persisted in `bot_state`).

### Kill the wasteful double call + new quota scheme
- Factual questions (intent == search) already searched BEFORE the first LLM
  call; the unknown-retry second call now runs ONLY when no search ran. If
  search ran and the reply is still unknown, the in-character deflection is
  sent directly. Retry rate is logged (`record_unknown_retry` /
  `get_unknown_stats()` in `bot_state`).
- Quota (config-driven defaults in `brain/memory.py`: `USER_DAILY_LIMIT=100`,
  `GROUP_DAILY_LIMIT=1500`, `USER_HOURLY_LIMIT=20`): per-user 100 replies/day
  hard cap + 20/hour burst cap + per-group 1,500 replies/day shared pool (the
  real ceiling). Cached replies do not count; search/YouTube/voice DO count;
  owner (1415214630) is exempt (still counted for /stats). Group exhaustion
  gets its own reply ("يا عم الجروب خلص حصته النهاردة، بكرا نكمل").
- Graceful degrade: when the group pool drops below 20%, cheap tiers only
  (router), cached replies keep working, at most ONE in-character "battery
  low" notice per hour per chat — never a silent dead bot.

### Output caps + /stats
- Chat 600 tokens, search synthesis 600, Groq `max_completion_tokens` 1500
  (was 1500–2000), Gemini 4000 unchanged, Cerebras/NIM/OpenRouter 1500.
- `/stats` (owner-only) now lists ALL providers in `provider_usage` with
  requests/tokens today + remaining-replies estimate at current average,
  per-user top counts, cache hit rate, group-pool remaining %, unknown-retry
  rate.

### Capacity math (at ~1,050 tokens/reply after compression)
| Pool | Budget | Replies/day |
|---|---|---|
| Groq 3 models × 180k tok | 540k tok | ~514 (571 at real 200k) |
| Gemini Flash-Lite ×2 | 500 RPD each | 1,000 |
| Gemini Gemma 4 | 14,400 RPD, 15k TPM, ~7/min | ~9,600 (TPM-bound in practice) |
| Gemini Flash-preview (last) | 20 RPD | 20 |
| OpenRouter :free | 50 RPD shared | 50 |
| **Standing pool (no Cerebras, no NIM)** | | **~11,184/day** |
| + Cerebras (if free tier exists) | 1M tok/day | +~950 |
| + NVIDIA NIM (trial terms only) | 10,000 RPD | +10,000 |
Target is 1,500/day. Even WITHOUT Gemma the standing pool is ~1,584/day —
just above target; with Gemma ~7× headroom. Apply the research's ~50% haircut
for free-tier churn (models deprecated, limits moved without notice):
**~5,500/day expected-pessimistic, ~11,000/day expected** — comfortably above
1,500 either way, PROVIDED Gemma/Flash-Lite numbers hold in Seif's own AI
Studio project. The real binding constraint in practice is TPM/RPM bursts
(Groq 8k TPM window, Gemma 15k TPM), not daily totals — the router spreads
load across providers and the per-user 20/hour burst cap absorbs spikes.
Without Cerebras AND without Gemma the pool is ~1,584/day, i.e. exactly at
target with no headroom — Gemma is the load-bearing addition after Groq.

### Keys needed from Seif (new providers only — code + config ready, no key = entry skipped)
- `CEREBRAS_API_KEY` — console.cerebras.ai (or cerebras.ai dashboard → API Keys).
  Adds ~950 replies/day IF the permanent free tier still exists (verify in the
  console: 1M tokens/day; if it asks for a card / $5 trial, the tier is the
  30-day trial, not permanent — the bot still works, it just disables itself
  after the trial ends).
- `NVIDIA_API_KEY` — build.nvidia.com (NVIDIA Developer Program, phone
  verification; API key under the NIM model page). Adds up to 10,000 req/day
  as an OVERFLOW tier only (trial terms: testing/evaluation, not production).
- `OPENROUTER_API_KEY` — openrouter.ai/keys (free, no card). Adds 50 req/day
  unfunded as an emergency spare. (One-time $10 credit purchase would raise
  this to 1,000 RPD — a paid option, NOT built or required.)
Existing keys (Telegram, Gemini, Groq) unchanged. All three new keys are
optional — the bot starts and runs fine without any of them.

### Deferred (explicitly NOT built in v0.6, with reason + design note)
- Self-hosting (Modal $30 credits / Oracle Always Free VPS + Ollama small
  model): the only truly unlimited path, but it is a hosting project (VPS
  provisioning, hardening, model serving, restarts), not a router change; and
  the pooled free-API capacity above already covers 1,500/day with headroom.
  Design if ever needed: llama-server + Qwen3-8B Q4 (Modal T4, ~6s/reply,
  ~1,000/day within free credits) as Tier 1 bulk chat, Nile-Chat-4B on Oracle
  CPU as always-on fallback; Groq/Gemini keep hard/search. Revisit only if
  live traffic proves the API pool insufficient.
- Semantic cache (local sentence-transformers + FAISS, similarity ≥0.90):
  exact-match cache first (built now); semantic cache adds 20–30% on free-form
  banter per literature but risks stale/wrong-context roasts and needs an
  embeddings model in the image. Revisit after measuring real exact-cache hit
  rate in live traffic.
- Mistral La Plateforme: free-tier status CONFLICTS across sources (one says
  ~1B tokens/month Experiment tier, another says the free API was removed
  Nov 2026 and API needs billing). NOT added as a provider; re-check the
  console before ever adding it — if the Experiment tier exists it would be a
  large simple-chat overflow tier (2 RPM binds, so ~1,000–2,000/day max).
- LLM-as-judge for search, structured BotPlan classifier, Postgres migration,
  plugin rewrite, PTB v22 upgrade — still deferred as in v0.5 (see v0.5 entry).

### Still unverified live (flag in every report, not just here)
- Cerebras free-tier status (conflict above); NIM trial terms (production-use
  clause); Gemma 4 / Flash-Lite live RPD in Seif's own AI Studio project
  (Google publishes no per-model table; limits vary per project, "not
  guaranteed"); real Groq prefix-cache hit rates and actual token savings;
  real yt-dlp download, real Edge TTS/ffmpeg voice, live LLM calls against the
  new caps. No live LLM calls were made in v0.6 — all new-provider
  verification is adapter construction + mocked-error tests only.
- Still blocks the live group test: deploy (Render — Seif pastes his own keys
  in the Render dashboard; Vault keys are NOT available to Render), then live
  test in the group. The test group id is now known (-1005812444791) and the
  bot is already admin there (verified 2026-11-25 22:30 EET).

## 2026-11-25 — v0.7c Northflank deploy prep (health endpoint + BAHGAT_DATA_DIR)
- Health endpoint: new stdlib-only module tg/health.py — ThreadingHTTPServer
  in a daemon thread started from main.py next to run_polling, binds
  0.0.0.0:$PORT (default 8080). GET /healthz (alias /health) returns 200
  {"status":"ok","last_poll_age_seconds":N} when data/heartbeat.json is
  <300s old, else 503; other paths 404. Shuts down cleanly on SIGTERM via
  finally in main(). No new dependency, no secrets in logs (access logs
  silenced). Dockerfile HEALTHCHECK unchanged (still reads the heartbeat
  file); only its comment now mentions /healthz.
- BAHGAT_DATA_DIR env var (core/config.py data_dir()): the data dir was
  hardcoded in 4 places (brain/memory.py, tg/handlers.py, brain/router.py,
  tg/app.py) — now all four resolve from the env var, default
  <project root>/data. Set BAHGAT_DATA_DIR=/data on Northflank so bahgat.db
  lives on the persistent volume; without it the volume is useless.
- DROP_PENDING_UPDATES env var (core/config.py Settings, default true):
  drop_pending_updates was hardcoded True in main.py; set false on the
  deployed instance so messages sent while the bot was down are delivered
  on wake (Telegram holds updates 24h) instead of discarded.
- .env.example documents BAHGAT_DATA_DIR / DROP_PENDING_UPDATES / PORT.
- Deploy guide: docs/DEPLOY-NORTHFLANK.md (Egyptian Arabic) — Combined
  service, Dockerfile build from GitHub main, 1 instance, nf-compute-50
  (0.5 vCPU / 1 GB, $12/mo inside the $20 Sandbox credit), 1 GB volume at
  /data, HTTP port 8080, health check /healthz, all env vars to paste.
- Tests: 8 new in tests/test_health.py (200 fresh / 503 stale / 503 missing /
  /health alias / 404 / $PORT binding / data_dir() override / subprocess
  end-to-end proving all four modules resolve under BAHGAT_DATA_DIR).
  **263 tests pass in .venv, py_compile clean, ruff clean.**
- Verified: import main + build_application() builds 6 handlers;
  DROP_PENDING_UPDATES=false parses to False, default True preserved.
- Pre-existing VM quirk (NOT caused by this change): httpx.Client() raises
  InvalidURL on this VM's NO_PROXY value (bracketed IPv6 literals like
  [::1]); build_application() needs NO_PROXY unset in this VM. Deploy
  target is unaffected.
- Open blockers (not done here): (1) no GitHub repo exists yet for the bot —
  must be created + code pushed to branch main before Northflank can build;
  (2) Northflank requires a payment method for verification even on free
  Sandbox (billing docs, verified); Seif has no international Visa —
  options researched in docs/research-payment-cards-egypt.md (EverTry ~$4
  best, RedotPay, Pyypl, QNB/CIB USD debit; fake/generated cards cannot
  pass Stripe auth). No-card fallback: Render free web service.
