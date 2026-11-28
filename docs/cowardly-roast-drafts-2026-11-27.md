# Cowardly roast lines — DRAFT candidates for Seif's approval (NOT in the bank)

Written 2026-11-27 13:47 EET, while Seif is asleep. The bank's roast situation
`cowardly` has ZERO lines (it falls back to the generic pool) — Seif was asked
2026-11-26 to add cowardly lines on the insult page and never answered.

Mining the existing transcripts found NOTHING usable for this situation:
- training/transcripts/ (24 files, ~25,676 words, faster-whisper-small, no
  diarization, garbled on fast slang) — the only "جبان" hits are one garbled
  line duplicated in short_01/short_05 ("جبان اوه اكبن منه ملعجش") that cannot
  be reconstructed with confidence.
- The v1.2 bank-expansion job (training/work/bank_expansion/worker-A..D.yaml,
  144 entries) already mined everything usable from these transcripts and it
  is already in the bank (224 entries).

So these 5 lines are DRAFTED by Muse in Bahgat's voice — they are NOT
Bahgat's attested words and must NOT go into the bank unless Seif approves
them (then they enter as confidence `user`, like his page submissions).
All 5 are member_safe (no father/mother/family words — pure cowardice mockery).

## Candidates (situation: cowardly, trigger: roast)

1. "انت جبان لدرجة إن الخوف نفسه بيخاف منك"
   — you're so cowardly even fear is afraid of you.

2. "يا جبان، انت بتجري من خيالك"
   — you run away from your own shadow.

3. "لو الحرب قامت انت أول واحد هيستخبى تحت السرير"
   — if war broke out you'd be the first one hiding under the bed.

4. "يا جبان، قلبك بيدق من صوت الباب"
   — your heart pounds at the sound of a door.

5. "انت مش جبان بس، انت التعريف بتاع الجبن في القاموس"
   — you're not just a coward, you're the dictionary definition of cowardice.

## How to use

- If Seif approves one or more: add to persona/bahgat/reply_bank.yaml as
  roast entries with `situation: cowardly`, `member_safe: true`,
  `confidence: user`, `source: user-submitted` (his approval), following the
  v1.4/v1.5/v1.6 ingest pattern (tests, commit, push with a fresh token).
- If Seif rejects them: delete this file. Do not bank them.
- If Seif adds his own cowardly lines on the insult page instead: use those
  (his lines always win over drafts).
