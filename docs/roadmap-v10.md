# Bahgat Bot — Roadmap to v10

Mission (Seif, 2026-11-27 03:38 EET): the best Telegram bot. Ship feature by
feature; each feature is DONE only when verified 100% — offline suite green
+ live test green + no regressions. Then the next feature starts. No
unverified version ships.

## The loop (per feature)

1. Implement + scenario tests (offline).
2. Full pytest green + ruff clean.
3. Commit + push → Cloady auto-redeploy → confirm Running.
4. Live verification in the test group via Seif's Telegram Web session (his
   account, test group only): scripted checks for the feature + core
   regression checklist (insult → comeback not search, roast targeting,
   prefixes, search, YouTube choice).
5. Green → version done, next feature. Red → fix, re-verify (max 5 rounds,
   then escalate to Seif).

## What "100%" means

- Deterministic behaviour (routing, triggers, buttons, downloads,
  member-safety): strict pass/fail, must be 100%.
- LLM reply quality (savagery, stance, dialect): scenario evals + rubric;
  a human ear (Seif) is the final judge for voice/tone — the loop flags,
  Seif confirms.
- A version is never declared done on offline tests alone.

## Queue

- **v1.7 — يا-vocative prefix fix (IN PROGRESS):** "يا بهجت قول/هات/دور ..."
  fires prefixes; query clean. Acceptance: scenario tests + live prefix
  checks.
- **v1.8 — YouTube 🎬/🎵 end-to-end live:** video + audio taps deliver real
  files on Cloady; cookies path; 50 MB limit handled. Acceptance: tap both
  buttons live, files arrive.
- **v1.9 — Roast coverage (PENDING, numbering shifted):** "cowardly" situation gets lines; mine the
  Telegram clip library for new real Bahgat lines (transcript confidence),
  situation-tagged, member-safe. Acceptance: bank grows, no regressions.
  (Was the v1.9 slot in the original queue; the slot was taken by the
  edge-tts voice fix, which shipped as v1.9 instead. Roast coverage is
  still next in the feature queue after v1.10.)
- **v1.10 — WARP in-container for YouTube downloads (IN PROGRESS):** wgcf + wireproxy baked into the
  image, profile persisted under /app/data/warp/, proxy on the download
  path only, WARP_ENABLED kill switch, enrolment cap 3. Acceptance:
  El Kholasa video + audio taps deliver real files live; voice ×3
  re-checked (new egress IP may also fix the v1.9 voice intermittency).
- **v1.11 — Bank lines as ingredients + WARP status on /healthz (DONE, local — pushes after the v1.10 retest):** insulted/roast bank lines are woven into a fuller LLM reply, never sent standalone (Seif 2026-11-27 05:34 EET); owner gates untouched; LLM-down fallback is _TURN_ERROR, never the line. WARP writes data/warp/status.json on every state change (on/off/down + egress IP) and /healthz exposes it, so "tunnel never came up" and "tunnel up, YouTube flags the IP" are distinguishable from outside. Acceptance: live probe — insult/roast replies CONTAIN a bank line inside longer text (substring match, never the whole reply); GET /healthz shows the warp field. Non-insult categories (joke, greeting, opinion, condolence, challenge, dismiss) stay verbatim.
- **v1.12 — Football + religion identity (DONE, local — pushes after the v1.11 retest):** die-hard Ahly, hates the Ahly board, hates the national team (they fired Hossam Hassan), despises Mohamed Salah; Muslim, protective of his religion. Prompt 6.7, SYSTEM_BASE 1595 chars (budget < 1800). **Expansion (DONE, local, same version — prompt stays 6.7, SYSTEM_BASE 2465 chars, budget < 2800; NOT pushed — Seif is still adding persona facts):** Egyptian-American against injustice/oppressors, mission is awareness and freedom (especially freedom of expression); Jerusalem is Arab, anti-Zionism, hates Israel most, backs Palestine; hates Real Madrid and Mbappé, loves Vinícius; Messi is his GOAT (defend, never roast — code guard in the roast path), respects Cristiano but may roast him jokingly or seriously; loves macaroni béchamel and mahshi, hates boftik, cooked vegetables, fesikh and ringa; hates Saudi Arabia and Morocco; mocks eFootball and Egyptian rap (mockery is opinion-level — fetching a rapper's song still works); loves YouTubers Yehia Azzam, Mahmoud Mahdi, Loay Fawzy; loves deep cinema. Acceptance: live stance checks — Ahly-news question answered from search with a source, Salah/board/national-team contempt with no praise, Ahly pride, Salah roast weaving a bank line inside contempt, religion-mockery question answered with fierce defense, "انت مسلم؟" with a proud Muslim stance; Messi opinion (GOAT) + "اشتم ميسي" defended, never roasted; Ronaldo roast still weaves a line; Real Madrid / Mbappé hate; Vinícius love; Palestine / Jerusalem / Israel stances; food likes and dislikes; eFootball and Egyptian-rap mockery; YouTuber and deep-cinema love.
- **v2.0 — TikTok fetch:** "هات تيك توك ..." / TikTok link → video
  download + choice. Acceptance: TikTok URL → file live.
- **v2.1 — Search quality:** sourced answers, freshness, follow-up
  inheritance hardening. Acceptance: 3 live news questions with sources.
- **v2.2 — Member memory in replies:** bot uses what it remembers
  (grudges, tastes, running jokes) in replies. Acceptance: live reference
  to an earlier exchange.
- **v2.3 — Voice triggers + prosody:** rate ladder by mood, more voice
  moments (Edge TTS now; RVC wiring when the model lands from laptop
  training). Acceptance: voice note on demand + angry voice, live.
- **v2.4 — Group-join greeting:** when added to a group, Bahgat introduces
  himself in character. Acceptance: add to a fresh group → greeting live.
- **v2.5 — Inline mode:** @Bahgoti_bot usable inline in any chat
  (search/YouTube). Acceptance: inline query returns results live.
- **v2.6+ — Backlog:** RVC voice wiring (needs laptop training to land),
  Style RAG persona, neural fine-tune (later), more clip mining,
  catchphrase bank for dropped lines. Queue extends as features verify;
  versions advance per verified feature.

## Status

- v1.9 live (0d918a5, 2026-11-27 04:38 EET). Live retest 04:59–05:05 EET:
  voice 1/3 (edge-tts 7.3.1 works but intermittent — likely Edge
  rate-limiting the datacenter IP), failure lines pass (natural Egyptian),
  identity passes. v1.10 WARP in progress.
- v1.11 DONE locally (2026-11-27, not pushed — pushes after the v1.10
  redeploy + retest): bank lines as ingredients + WARP status on /healthz.
  625 tests pass. Live retest must check: insult/roast replies contain a
  bank line inside longer text (never the whole reply), and /healthz
  carries the warp field.
- v1.12 DONE locally (2026-11-27, not pushed — pushes after the v1.11
  redeploy + retest): football + religion identity in the persona
  (prompt 6.7 — die-hard Ahly, hates the board, hates the national
  team over Hossam Hassan, despises Salah; Muslim, protective of his
  religion). 651 tests pass. Live retest must check: Ahly-news question
  answered from search with a source, Salah/board/national-team contempt
  with no praise, Ahly pride, Salah roast weaving a bank line inside
  contempt, religion-mockery question answered with fierce defense.
- v1.12 EXPANSION DONE locally (2026-11-27, same version, second
  commit — prompt stays 6.7, SYSTEM_BASE 2465 chars, budget < 2800;
  NOT pushed — Seif is still adding persona facts): his cause and
  tastes — Egyptian-American against injustice/oppressors, mission is
  awareness and freedom (especially freedom of expression); Jerusalem
  is Arab, anti-Zionism, hates Israel most, backs Palestine; hates
  Real Madrid and Mbappé, loves Vinícius; Messi is his GOAT (defend,
  never roast — code guard in the roast path), respects Cristiano but
  may roast him jokingly or seriously; loves macaroni béchamel and
  mahshi, hates boftik, cooked vegetables, fesikh and ringa; hates
  Saudi Arabia and Morocco; mocks eFootball and Egyptian rap; loves
  YouTubers Yehia Azzam, Mahmoud Mahdi, Loay Fawzy; loves deep
  cinema. 705 tests pass. Live retest must check: Messi opinion
  (GOAT) + "اشتم ميسي" defended, never roasted; Ronaldo roast still
  weaves a line; Real Madrid / Mbappé hate; Vinícius love; Palestine /
  Jerusalem / Israel stances; food likes and dislikes; eFootball and
  Egyptian-rap mockery; YouTuber and deep-cinema love.
- v1.12 BATCH 3 DONE locally (2026-11-27, same version, third
  commit — prompt stays 6.7, SYSTEM_BASE 3106 chars, budget < 3600;
  NOT pushed — Seif is still adding persona facts): tech tastes,
  temperament, mockery targets — loves Android, mocks iPhone/Mac;
  slightly perverted, loves women; hates homosexuals; mocks
  feminists/women's-rights movements; mocks the army and the police
  in every country; impulsive, reckless, stubborn, sometimes a
  little wisdom; adventurous, free-spirited, brave, says what's on
  his mind; mocks Amr Diab and Tamer Hosny; loves Abo Treika. 739
  tests pass. Live retest must check: Android love + iPhone/Mac
  mockery; feminists/women's-rights mockery; army/police mockery;
  Amr Diab + Tamer Hosny mockery; Abo Treika love; temperament
  (speaks his mind, doesn't hedge). Open question: a Treika roast
  request still picks a generic bank line — no guard was asked for
  (unlike Messi, who is defended).
