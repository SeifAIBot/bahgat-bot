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
- **v1.9 — Roast coverage:** "cowardly" situation gets lines; mine the
  Telegram clip library for new real Bahgat lines (transcript confidence),
  situation-tagged, member-safe. Acceptance: bank grows, no regressions.
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

- v1.6 live (82d3d25). Baseline live test of v1.6 running 2026-11-27
  03:36 EET. v1.7 fix in progress.
