# Bahgat voice-clone (deepfake) training — report

**Date:** 2026-11-26. **Go-ahead:** Seif's explicit go-ahead, 2026-11-26 00:04 EET
("دربه علي الديب فيك"). **Cost:** $0 — no paid services, no paid GPU.
**Status: pipeline prepared, training NOT yet run.** Everything below is local
under `~/workspace/bahgat-bot/training/`; nothing was uploaded anywhere public.
The bot stays labelled a parody bot (`setMyDescription`), not the real Bahgat Saber.

## Headline numbers

| Item | Result |
|---|---|
| Voice-set videos downloaded | **6 of 8 retried** (Karma, Sheikh, Komanda, Lagan, committee-girl, Christian) — see §1; Lina videos still bot-checked |
| Clean solo-Bahgat audio kept | **66.23 min (630 clips)** — 396 high / 234 medium. Was 66.01 min (628 clips); the 2026-11-26 shorts batch (§16) added 2 clips (13.1 s) from Seif's short videos. Sad/crying clips NOT found in reachable sources. |
| Transcript | 1,866 segments across 3 cleaned videos (karma 654 + sheikh 683 + komanda 529; faster-whisper small, Arabic) — plus 399 (lagan) + 694 (committee-girl) + 234 (christian) + 1057 (funny-komanda) + 312 (train-accident) + 2002 (lina-live, assessed only) + 35 segments across the 15 shorts |
| Curated RVC set | **38.11 min (361 clips), 48 kHz mono** — best-of selection from the 630-clip pool, audit-driven (§16, post-audit finals in §18); `training/curated/` + `~/workspace/bahgat_dataset_curated.zip` |
| XTTS v2 zero-shot | **REJECTED by Seif on listen (2026-11-26 02:48 EET): does not sound like Bahgat at all, does not speak Egyptian dialect — XTTS zero-shot is OUT** (see §4) |
| OmniVoice zero-shot | **Generated on Colab T4 (2026-11-26 04:23 EET), 5.67 s, 24 kHz** — Seif's verdict 05:33 EET: timbre close to Bahgat, speaking style mediocre, feels slow (see §11). XTTS was skipped in the comparison (doesn't install on Colab's Python 3.13; already rejected by ear). |
| RVC / GPT-SoVITS training | **NOT run** — package ready, needs the interactive Colab GPU run |
| Bot tests after this work | 315 pass — no bot runtime code was changed |
| Dataset zip | `~/workspace/bahgat_dataset.zip` — rebuilt 2026-11-26 after the shorts batch: 114,410,770 bytes, 683 files (630 clips + transcripts) (see §16) |
| Curated dataset zip | `~/workspace/bahgat_dataset_curated.zip` — 190,973,322 bytes (~182 MB), 362 files (361 clips, 38.11 min, 48 kHz mono; 44.1 kHz for the 2 shorts) — the RVC training set (§16, post-audit §18). Bigger than the full zip because 48 kHz is 3× the samples of 16 kHz. |

## 1. Download — per-video verdicts

Source list: `docs/training-videos.md` (section A). Audio-only, best quality
(yt-dlp 2026.11.23, installed in the bot venv). Manifest:
`training/raw/manifest.json`, `training/raw/MANIFEST.md`.

| # | Video | Status | Duration / size |
|---|---|---|---|
| 1 | Karma conversation (`wjz_JxcJTiM`) | ✅ ok | 28:41, 20.5 MB, Opus 48 kHz stereo, ffprobe-verified |
| 2 | Debate with a Sheikh (`-F3b9XGrrbs`) | ✅ ok (cookies) | 28:27, 20.4 MB, Opus 48 kHz, ffprobe-verified — cleaned, +3.50 min |
| 3 | Live 6/11/2026 (`9cldVFbHJ5g`) | ❌ removed | "This video has been removed by the uploader" — searched again for a re-upload 2026-11-26, none found |
| 4 | الحوار الأجرأ مع كوماندا (`mixpWS-TGm8`) | ✅ ok (cookies) | 26:21, 14.5 MB, Opus 48 kHz, ffprobe-verified — cleaned, +12.10 min |
| 5 | مداخلات مع لجان (`MML3TRN72NQ`) | ✅ cleaned | 23:14, 12.5 MB — transcription redone cleanly (399 segments, 796 s, no repeat SIGTERM); +7.62 min (71 clips) — see §12 |
| 6 | نقاش ساخن مع بنت لجنة (`y8UR7BHh0bo`, style set) | ✅ cleaned | 29:09, 15.5 MB — +11.76 min (104 clips) — see §12 |
| 7 | بهجت يفحم ضيفاً مسيحياً (`qdOtUjTTLZs`, style set) | ✅ cleaned | 9:22, 5.6 MB — +3.85 min (38 clips) — see §12 |
| 8 | بهجت صابر ولينا (`Oli_neDUV_Y`, style set) | ⚠️ downloaded, NOT cleaned | Downloaded via Android client on the one allowed retry (1:45:59, 67.4 MB); 2002 segments, 0 sad/cry hits, speaker clusters unusable (both speakers in both clusters) — stage B deliberately not run, would inject Lina's voice — see §13 |
| 9 | حقيقة عمل لينا (`solcRS6dsjs`, style set) | ❌ bot-check | Failed twice with cookies (first attempt used a mistyped ID; correct-ID retry also bot-checked) — not retried; gaps it might fill are already covered |
| 10 | تجميعة كوماندا المضحكة (`dBjN21s49vQ`) | ✅ cleaned | 44:27, 25.7 MB — +14.06 min (141 clips), laughing/jokes — see §13 |
| 11 | بث حادثة القطار 8/11/2026 (`t5kaaMzZBj8`) | ✅ cleaned | 20:57, 12.9 MB — +6.18 min (56 clips), shouting rant — see §13 |

**Update 2026-11-26 ~01:00 EET — the bot-check is NO LONGER a hard blocker.**
Seif sent his YouTube cookies (26 lines, YouTube-only) and the 3 blocked
videos were retried with `--cookies` + `--remote-components ejs:github
--js-runtimes node` (the n-challenge solver script, one file from GitHub —
not a Hugging Face download) + `-f 18` (progressive format: the web
client's DASH audio URLs are SABR-only for this account, so `bestaudio`
resolves to nothing) + `--retries 30` (the egress proxy drops connections
mid-download; resume works). Two environment fixes came first: the egress CA
bundle had rotated (one cert missing from the venv's certifi store →
`SSL CERTIFICATE_VERIFY_FAILED` on every yt-dlp call; re-appended the
current bundle, backup now at `training/work/certifi-cacert-backup.pem`),
and node exists at `/usr/bin/node` (no Deno install needed). The android
player client was also tried: it skips cookies entirely ("Skipping client
android since it does not support cookies") — useless with auth. The
bot-check still bites intermittently: the two Lina videos failed twice each
with cookies while 5 other videos downloaded fine with the same file, so the
cookies are good and the failures are YouTube-side rate/session flakiness,
not bad credentials. **Update 2026-11-26 ~05:30 EET — the web client + cookies route now bot-checks on every attempt** (cookies NOT expired — expiries 2027; a public control video downloaded fine without cookies, so this is per-video YouTube-side gating, not bad credentials). **The Android player client (`--extractor-args youtube:player_client=android`, no cookies) bypasses the bot-check for public videos** — all three diversity downloads used it. iOS also bypasses but is SABR-only (no audio). The egress CA bundle had rotated again; re-appended (certifi now 476 certs). Full log: `training/work/cookies-retry-log.txt`, `training/work/style-download-log.txt`, `training/raw/MANIFEST.md`.

One environment fix (original job): yt-dlp initially failed TLS verification against the VM's
egress proxy (self-signed cert in chain); the egress CA bundle
(`/run/hatch/egress-tls/ca-bundle.pem`) was appended to the venv's certifi
store (backup at `/tmp/certifi-cacert-backup.pem` — that backup is gone with
/tmp; the current backup is `training/work/certifi-cacert-backup.pem`). If certifi is ever
upgraded/reinstalled in the venv, re-apply the append.

**The job is viable from the one success:** 28:41 already exceeds the 10-min
RVC minimum and the 5–10 min GPT-SoVITS target as raw audio — the shortfall
came later, in cleaning (see §2).

## 2. Clean dataset — 6.94 min kept (below the 10-min target)

> **Update 2026-11-26:** this section is the karma-only result. With the
> sheikh + komanda expansion the total reached 22.54 min (218 clips); two
> further expansions took it to **66.01 min (628 clips)** — see §12–§13 and
> the expansion sections at the top of
> `training/clean/cleaning_report.md`.

Full report: `training/clean/cleaning_report.md`. Files:
`training/clean/bahgat_0001.wav` … `bahgat_0075.wav` (16 kHz mono WAV,
3.02–10.00 s each, all ffprobe-verified, 0 failures),
`training/clean/filelist.txt` (75 lines),
`training/clean/xtts_reference.wav` (7.16 s, best clip, excluded from
`filelist.txt` to avoid double-counting).

| | Clips | Duration |
|---|---|---|
| Audio in (Karma file) | — | 1721.1 s (28.68 min) |
| Whisper-segmented speech | 654 segments | 1336.2 s (22.27 min) |
| **Kept — clean solo Bahgat** | **75** | **416.6 s (6.94 min)** |
| of which high confidence | 45 | 235.1 s (3.92 min) |
| of which medium confidence | 30 | 181.6 s (3.03 min) |
| Rejected (in `training/work/rejected/`) | 171 | 811.9 s (13.53 min) |
| Dropped as too-short fragments | 94 | 132.7 s (2.21 min) |
| Untranscribed audio (no Whisper segments) | — | 384.9 s (6.41 min) |

Audio measured: −13.84 LUFS integrated, RMS −14.35 dB, 98.8% speech (only
21.1 s of silence ≥0.5 s — silence-splitting was useless, Whisper boundaries
were used instead). Source stereo is dual-mono (no separation to exploit).

**Why under 10 min — structural, not a threshold choice.** 118.7 s of
labelled Bahgat speech exists only as isolated <3 s interjections between the
guest's turns and cannot form 3 s clips without including her voice; 95 s of
loud audio (two gaps, 60.8 s + 34.3 s) got no Whisper segments at all and is
unlabelled. The worker did not loosen the bar to chase the number — that is
exactly how guest audio leaks into a voice model. 6.94 min is inside the
5–10 min GPT-SoVITS target; for RVC it is usable but under the recommended
10 min. What reaches 10 min: (1) a second source video cleaned the same way
(best option — needs the YouTube cookies unblocker above); (2) the 19
"conflict" clips (63.1 s, probably mostly Bahgat shouting) would bring it to
~8 min, still short, at the cost of possible female contamination — only
after a human listens to them. Do NOT lower the clip floor below 3 s or
bridge across guest turns.

**Diarization did NOT work as true diarization.** pyannote-audio is gated —
verified live, unauthenticated download returns `GatedRepoError 401`; no
account/token was created. Instead, labelling used three cheap numpy signals
(librosa was skipped: too heavy for ~400 MB free RAM): per-segment median F0
(autocorrelation, cross-checked with a cepstral estimator, ratio 0.98),
spectral centroid, and MFCC-means + 2-means clustering (stable 97–99%
across seeds; cluster 0 = deeper/darker male voice = Bahgat, cluster 1 =
Karma). F0 alone cannot separate them — Bahgat shouts at high pitch much of
the time. Text cues were nearly useless (Whisper-small garbles this fast
slang/profanity-heavy dialect badly; "كارما" appears once, "بهجت" zero
times). Confidence is tiered honestly in the report; **0 of 75 kept clips
contain any guest/conflict segment**.

## 3. Transcripts

- Tool: faster-whisper 1.2.1, model `small`, language `ar`, word timestamps
  on, int8 CPU — 654 segments in 1000 s. (Workaround needed: pip pulled av
  19.0.2, incompatible with faster-whisper's decoder — the WAV was decoded
  with stdlib `wave` + numpy and passed as an ndarray; documented in
  `training/work/transcribe.py`.)
- Files: `training/transcripts/karma_full.json` (segments + word timestamps),
  `training/transcripts/karma_full.txt` (readable, 2,344 words). Detected
  language ar, p=1.00.
- **Transcript quality caveat:** Whisper-small on this material is heavily
  garbled — many words are nonsense guesses. Use the transcript for style
  examples only with caution, and never trust a single segment's wording; the
  audio is the ground truth. These transcripts feed the bot's text style
  examples later (persona examples/RAG) — that step is not done yet.
- Two loud stretches got no segments at all (209.8–270.6 s and 1245.8–1280.1
  s) — probably heavy overlap/shouting or music. Excluded as unlabelled.

## 4. XTTS v2 zero-shot — RAN, sample produced, REJECTED by Seif on listen

> **Update 2026-11-26 02:48 EET — Seif listened and rejected it: the voice
> does not sound like Bahgat at all and does not speak Egyptian dialect.
> XTTS zero-shot is OUT.** The transcription proxy below measured word
> intelligibility only, not accent or timbre (sample F0 129.7 Hz vs
> reference 158.4 Hz) — the human verdict overrules it. Do not re-propose
> XTTS zero-shot. The remaining zero-shot candidate is OmniVoice (§5),
> still untested; the main path is now RVC training on the 22.54 min
> dataset (§6–§7).

Full measured notes: `training/samples/zero_shot_notes.md`.

- Reference: `training/clean/xtts_reference.wav` (7.16 s, RMS −13.1 dB,
  median F0 158.4 Hz by the coordinator's estimator; clean job reported mean
  161.9 Hz).
- Test sentence (Egyptian Arabic, exact): "يا عم انت بتقول ايه؟ انا مش فاهم
  حاجة من اللي انت بتقوله ده خالص"
- Output: `training/samples/xtts_sample.wav` — **5.75 s, 24 kHz mono, PCM
  s16le, 276,044 bytes**, ffprobe-verified. RMS −15.6 dB, median F0 129.7 Hz.
- How: Coqui TTS, `tts_models/multilingual/multi-dataset/xtts_v2`,
  language `ar`, CPU, in a separate venv (`training/work/venv-xtts/`, 5.5 GB
  on disk). It took 4 runs: run 1 `ImportError: BeamSearchScorer` from
  transformers; run 2 torch 2.6 `weights_only` UnpicklingError; run 3
  torchaudio `TorchCodec is required`; run 4 succeeded — model loaded in
  28.4 s, processing 27.4 s, real-time factor 4.38 (slow CPU, as expected).
- **Intelligibility (objective proxy):** the sample was transcribed back with
  faster-whisper small (cached model, offline) as "يا عمانت بتقول ايه انا مش
  فهم حاجة من اللي انت بتقوله ده خالص" — nearly identical to the input
  sentence (one merged word, one dropped letter). By the transcription proxy,
  the sample is highly intelligible Egyptian Arabic.
- **Pitch vs reference:** 129.7 Hz vs 158.4 Hz median — about 29 Hz lower
  (deeper). Possible causes: XTTS's rendering, the sentence's prosody, or the
  reference clip being a higher-pitched excited stretch. A measurement, not a
  similarity verdict.
- **Verdict (measured only):** XTTS v2 zero-shot works end-to-end from a
  7.16 s Bahgat clip and produces intelligible Egyptian Arabic. **Voice
  similarity is UNVERIFIED — no human has listened to the sample.** Do not
  quote the XTTS result as "sounds like him" until the Colab listening test
  is done.

## 5. OmniVoice vs XTTS comparison — verdict section

This is a first-class test, not a side note (Seif confirmed: use the
VoiceStudio deepfake trick from the X posts if it is useful). Full
evaluation: `training/colab/voicestudio_evaluation.md`. Comparison notebook:
`training/colab/bahgat_zeroshot_omnivoice_vs_xtts.ipynb` (13 cells,
validated JSON/nbformat).

### What VoiceStudio is

`github.com/debpalash/VoiceStudio` — free open-source ElevenLabs replacement,
118,357 stars, AGPL-3.0, Electron app + FastAPI backend, Docker images
CPU + CUDA on GHCR, local API + MCP, no account needed. Default engine is
**OmniVoice (k2-fsa)** with zero-shot voice cloning; the engine catalog lists
**21 engines** including CosyVoice 3, IndexTTS 2.5, and GPT-SoVITS (external
server). **XTTS is NOT in the catalog** — the XTTS side of the comparison
comes from Coqui's own `TTS` package.

### What was verified in the repo (read first-hand, 2026-11-26)

- OmniVoice: zero-shot cloning across 600+ languages, 24 kHz mono, reference
  clip sweet spot 3–10 s, ~6 GB VRAM floor, CPU works but slow, GGUF variant
  for low-VRAM/CPU. Invoked via the app's local API (`127.0.0.1:3900`,
  `POST /generate`, OpenAI-compatible `POST /v1/audio/speech`) or — the key
  finding — as a **standalone pip package** (`pip install omnivoice`, PyPI
  0.1.5, `OmniVoice.from_pretrained("k2-fsa/OmniVoice")`), no Electron or
  Docker needed. Docker cannot run on Colab, so the pip route is the Colab
  route.
- GPT-SoVITS "external server" = **not bundled**: you run the upstream
  RVC-Boss server yourself; VoiceStudio is only an HTTP client (`POST /tts`,
  api_v2). Languages: zh/en/ja/yue/ko only — **no Arabic**, independently
  confirming the training-package worker.
- Licence: default OmniVoice weights are **CC-BY-NC** (code Apache-2.0); the
  app is AGPL-3.0. A Pro commercial licence covers the code only, not the
  weights. XTTS v2 is also non-commercial (CPML) — the licence position does
  not favour either engine.
- Arabic: the language catalog lists Standard Arabic `arb` (1,483.53 h) **and
  Egyptian Arabic `arz` (23.23 h)** — plus Gulf, Najdi, Levantine, Saidi.
  But `arz` has ~64× less data than `arb`, voice design is EN/ZH-only and
  unstable in low-resource languages, and there is no Arabic quality claim
  anywhere. **Egyptian-dialect quality is genuinely unknown until the
  listening test.** XTTS v2 supports Arabic as generic `ar` only (17
  languages) — no dialect code at all, a structural disadvantage vs
  OmniVoice.

### Verdict: COMPLEMENT — do not replace the RVC/GPT-SoVITS training setup

**One-line reason:** VoiceStudio adds a strong zero-shot engine (OmniVoice,
with an `arz` Egyptian option XTTS lacks) and a handy offline-generation API,
but it contains no RVC at all and its GPT-SoVITS is only a client to an
external server that does not support Arabic — so it cannot replace the
trained-voice pipeline the bot's runtime depends on.

| Piece of the current setup | Does VoiceStudio replace it? |
|---|---|
| RVC training (primary) | **No.** RVC is not in VoiceStudio at all. RVC is language-agnostic by design (converts acoustic features, does not need to *speak* Arabic) — exactly why it is primary for an Egyptian-dialect voice. |
| GPT-SoVITS training (fallback) | **No.** VoiceStudio does not train GPT-SoVITS; it talks HTTP to a separately-run server that does not support Arabic. |
| Colab training workflow | **No — heavier, not lighter.** Electron app + backend cannot run on Colab (no Docker) or Render free (512 MB, no GPU). |
| Runtime voice path (Edge TTS → RVC) | **No.** VoiceStudio is an offline/batch tool, not a runtime component. |

What VoiceStudio IS useful for: (1) the zero-shot comparison (its engine is
the strongest zero-shot candidate, with `arz`); (2) offline batch generation
later if OmniVoice wins (backend Docker on any GPU machine, or the pip
package in a script; local API built for scripted use); (3) the 21-engine
catalog as a discovery shortlist (IndexTTS 2.5, CosyVoice 3, VoxCPM2 — none
verified for Arabic either). What it is NOT useful for: runtime on Render
free, Arabic GPT-SoVITS training, commercial use under CC-BY-NC.

### Comparison status — NOT YET RUN

- XTTS side: sample exists (`training/samples/xtts_sample.wav`, §4).
- OmniVoice side: **not run anywhere yet.** The in-VM attempt was stopped
  before it could run (see §8). The comparison runs on free Colab GPU via
  the notebook: same reference clip + same test sentence, OmniVoice tried
  with `language_id="arz"` first (fallback auto/`arb`), both WAVs exported to
  Drive, listening scorecard (similarity / intelligibility / dialect
  accuracy / artefacts, 1–5 each) filled in by ear, with a stated decision
  rule. The notebook does not test VoiceStudio's mastering chain — if
  OmniVoice wins, one confirmation run through the real VoiceStudio backend
  on a GPU machine is worth doing before committing.
- If both engines fail the listening test: zero-shot is not good enough; the
  trained RVC model stays the only voice path (record the result in
  `docs/voice-plan.md`).

### Consent note (separate from copyright)

Both VoiceStudio's README and the upstream model disclaimer prohibit
unauthorised voice cloning / impersonation. Bahgat Saber is a real living
person and has not consented to having his voice cloned. The project
mitigates this the only way it currently can: the bot is labelled a parody
bot, does not claim to be him, and is a private joke among ~15 people, not a
public impersonation. That labelling does not create consent — it is a
mitigation, and the residual risk stays visible here. (Seif gave the
go-ahead for the training itself on 2026-11-26 00:04 EET.)

## 6. Training package — ready, not run

`training/colab/` — RVC notebook + configs + README, and the zero-shot
comparison notebook + VoiceStudio evaluation.

- **RVC (primary):** official repo `RVC-Project/Retrieval-based-Voice-
  Conversion-WebUI`, pinned commit, v2, **40 kHz** (48 kHz needs ~24 GB VRAM
  and buys nothing audible for Opus-compressed Telegram voice notes; source
  is 16 kHz anyway), F0 on with **RMVPE** on CUDA, **batch 4, 150 epochs**,
  save every 10. ~45–75 min training for ~15 min audio on a free T4;
  ~1.5–2 h total. Expected output: `bahgat_rvc_v2_40k_<date>.zip` with
  `bahgat.pth` (~70–80 MB) + `.index`.
- **GPT-SoVITS (fallback):** official repo `RVC-Boss/GPT-SoVITS`, **v2**
  (v4 needs 8 GB min / 16 GB recommended — marginal on a 15 GB T4), SoVITS
  8 epochs batch 4, GPT 15 epochs batch 4. ~1–1.5 h total. **Arabic is not
  officially supported** — the notebook works around it with `LANG = "en"`.
- **Notebook:** `bahgat_rvc_gpt-sovits_training.ipynb` (33 cells: GPU check →
  clone/install/pretrained → Drive mount + dataset audit → RVC training →
  GPT-SoVITS → export → resume/troubleshooting → next steps). Validated as
  JSON/nbformat only — **not executed end-to-end** (no GPU here; Colab needs
  an interactive session). Two spots depend on upstream filenames at run time
  and have verification/fallback cells (pretrained `hf download` lists,
  GPT-SoVITS prep/train flag names).
- **Colab free-tier limits** (documented in the README): 12 h max session;
  ~90 min idle disconnect; GPU not guaranteed (retry off-peak); no
  background execution (tab must stay open); VM disk ephemeral; Drive 15 GB
  free (export weights only, not full `logs/`); Gradio WebUI blocked (hence
  headless CLI). Resume-from-checkpoint procedure is documented.
- **Dataset contract for the notebook:** `bahgat_dataset.zip` = a zip of
  `training/clean/` + `training/transcripts/`, uploaded to the root of Google
  Drive. The dataset on disk is now **66.01 min (628 clips)** — rebuilt
  2026-11-26 05:45 EET, 113,387,893 bytes, 651 files (see §12–§13).

## 7. What remains — the clear next steps (in order)

1. **Colab GPU run #1 — zero-shot comparison** — ✅ DONE 2026-11-26 04:23 EET:
   OmniVoice generated on T4 in 90 s (5.67 s, 24 kHz, same reference clip +
   test sentence); XTTS skipped (doesn't install on Colab's Python 3.13, and
   Seif had already rejected it by ear). Export on Drive:
   `bahgat_voice_models/zeroshot_comparison_2026-11-26`. Seif's verdict
   05:33 EET: timbre close, style mediocre, feels slow — measured in §11
   (it is NOT slow in words/sec; the dead air + flat prosody make it feel
   slow). Scorecard still blank — it is filled in by ear, and only Seif's
   ear can close it. If OmniVoice is re-tested, use the speed×reference grid
   in §14, not the default settings.
2. **Dataset top-up to 10+ min** — ✅ DONE, then overshot: 22.54 min
   (218 clips) after sheikh + komanda; **45.77 min (431 clips)** after
   lagan + committee-girl + christian (§12); **66.01 min (628 clips)** after
   the diversity expansion (§13). Research consensus (§14) is that minutes
   past ~30 add almost nothing — diversity is what mattered, and the set now
   covers conversation, debate, call-ins, argument, laughing, and shouting
   rants. **Stop adding videos.** The only gap left is sad/crying clips,
   not found in any reachable source (Telegram library unexplored — see §13).
3. **Colab GPU run #2 — RVC training** (interactive, stays with Seif):
   `training/colab/bahgat_rvc_gpt-sovits_training.ipynb`, T4 GPU, ~1.5–2 h,
   export `bahgat.pth` + `.index` to Drive. GPT-SoVITS fallback only if RVC
   fails or sounds wrong.
4. **Wire the trained voice into the bot** (separate task, not done here):
   runtime path stays Edge TTS `ar-EG-ShakirNeural` → RVC conversion with
   `bahgat.pth` + `.index`. Voice inference must stay OFF the Render free
   deploy (512 MB, no GPU) — generation/conversion is a batch/offline step.
   Decide then: convert on a GPU machine and ship audio, or run RVC on the
   deploy host if it ever moves off Render free.
5. **Style examples from transcripts** (later): the Karma transcript
   (654 segments) feeds persona examples/RAG for the bot's text style — not
   done yet, and the transcript is garbled in places (see §3), so it needs
   human cleanup before use.

## 8. Blockers and incidents (honest log)

- **YouTube bot-check (hard blocker in this VM):** 3 of 5 voice-set videos
  un-downloadable without authenticated cookies; 1 removed by the uploader.
  Voice set is 1 of 5 (Karma only).
- **Hugging Face approval flood → STOP order:** during the in-VM zero-shot
  attempt, model downloads from Hugging Face triggered ~30 approval cards
  for the user in a few minutes. The parent agent ordered an immediate stop:
  no more downloads from Hugging Face or any network request that triggers
  approval prompts. The zero-shot worker was closed mid-task (its OmniVoice
  attempt never ran; its XTTS sample had already been produced and is kept).
  This report was finished using only work already on disk. **Do not resume
  HF downloads in this VM without a different mechanism (pre-approved
  downloads, a Colab session, or the user's explicit per-download approval).**
- **Clean dataset 6.94 min < 10 min RVC target:** structural (see §2), not a
  quality compromise. RVC can still train on it; topping up is step 2 in §7.
- **No true diarization:** pyannote gated (401); labelling is acoustic
  clustering with tiered confidence (see §2).
- **Transcript garbling:** Whisper-small on fast slang/profanity-heavy
  Egyptian dialect is heavily garbled in places; audio is the ground truth.
- **Notebook not executed:** both Colab notebooks are validated JSON only;
  no training or comparison run has happened on a GPU yet.
- **Disk:** `training/work/venv-xtts/` (the separate XTTS venv) is 5.5 GB on
  disk. It can be deleted once the Colab comparison is done — it is not
  needed by the bot (the bot venv is untouched by it).
- **av workaround:** faster-whisper's decoder conflicts with av 19.0.2
  pulled by pip; the clean job decoded WAVs with stdlib `wave` + numpy
  instead (see `training/work/transcribe.py`).

## 9. Verification

- Every downloaded file ffprobe-verified (karma.opus: 1721.06 s, Opus).
- All 75 kept clips ffprobe-verified (16 kHz mono, 3.02–10.00 s, 0
  failures); `xtts_reference.wav` verified (7.16 s); `xtts_sample.wav`
  verified (5.75 s, 24 kHz mono).
- Transcript length matches audio roughly (654 segments over 1721 s;
  22.27 min segmented of 28.68 min in).
- Both Colab notebooks validated with `json.load` + `nbformat.validate`.
- Bot test suite run after this work: **263 pass**
  (`.venv/bin/python -m pytest tests/ -q`) — no bot runtime code was changed
  in this job (only `training/` files and this report were added).

## 11. OmniVoice — generated on Colab; Seif's verdict: close timbre, mediocre style, feels slow

**Run:** 2026-11-26 04:23 EET, Colab T4, fixed comparison notebook
(`training/colab/bahgat_zeroshot_omnivoice_vs_xtts.ipynb` — §1
transcript-lookup bug fixed: the cell tried to read the WAV itself as UTF-8
text; now checks `.endswith('.txt')`). §0 GPU check passed (Tesla T4,
15,360 MiB). §1 clip verified (16 kHz mono, 7.16 s; no transcript file, so
Whisper auto-transcription was used). §2 XTTS **skipped** (Coqui TTS does
not install on Colab's Python 3.13; Seif had already rejected XTTS by ear).
§3 OmniVoice completed in 90.32 s with no error (weights ~2.98 GB + Whisper
~1.61 GB downloaded on Colab). §4 scorecard + §5 export ran after the
earlier VM XTTS sample was uploaded to satisfy the export cell. Export:
Drive `bahgat_voice_models/zeroshot_comparison_2026-11-26`
(`comparison_notes.json`, `omnivoice_sample.wav`,
`reference_xtts_reference.wav`, `xtts_sample.wav`). Sample on disk:
`training/samples/omnivoice_sample.wav` — **5.67 s, 24 kHz mono, 272,204
bytes**. Playback verified in the notebook: intelligible Egyptian Arabic
saying the test sentence. **The scorecard is blank** (all scores `None`,
winner `None`) — it is filled in by ear, and only Seif's ear can close it.

**Seif's verdict (2026-11-26 05:33 EET, his words):** "الصوت قريب منه بس
طريقة الكلام نص نص و حاسه بيتكلم ببطء" — the voice is close to him, but
the speaking style is mediocre and it feels slow.

### Measured: is it actually slow? No — in words/sec it is FASTER than Bahgat

Measured 2026-11-26 with cached faster-whisper `small` (word counts are
approximate — Whisper garbles this dialect, but counts are roughly
preserved; silence via ffmpeg `silencedetect` at −40 dB):

| Sample | Duration | Speech | Words | w/s total | w/s speech-only |
|---|---|---|---|---|---|
| OmniVoice sample | 5.67 s | 2.81 s | 16 | **2.82** | **5.69** |
| Reference clip (Bahgat) | 7.16 s | 4.42 s | 15 | 2.09 | 3.39 |
| XTTS sample (rejected) | 5.75 s | 3.37 s | 14 | 2.43 | 4.16 |
| Bahgat natural (24 clean clips, pooled) | 153.9 s | — | 304 | **1.98** | 2.82 |

Median per-clip Bahgat rate: 2.14 w/s (range 0.00–3.36; one clip
transcribed 0 words). **OmniVoice runs at 1.43× Bahgat's natural
words/sec.** The "slow" feeling is not a rate deficit — it is three other
things: (a) **~50% of the OmniVoice file is dead air** (2.81 s speech in
5.67 s, vs 62% speech in the reference clip) — leading/trailing silence
makes it feel slow; (b) **flat, even prosody** — no Bahgat-style bursts,
rushes, or emphasis; the words come out at a metronome pace; (c) **the test
sentence itself is a calm, confused line** ("يا عم انت بتقول ايه؟ انا مش
فاهم حاجة…"), not a fast Bahgat rant — the wrong sentence to judge speed
on. Also: the comparison ran OmniVoice at **default `speed=1.0` with one
calm reference clip** — its speed/prosody was never actually tested (see
§14: the `speed` knob and the reference-clip choice are the two biggest
style levers, both left at default).

## 12. Second expansion — 3 more videos cleaned (→ 45.77 min)

Same pipeline (extract → faster-whisper small, cached only → F0/MFCC
clustering → clean solo clips, continuing numbering). Full per-video detail
in `training/clean/cleaning_report.md` (expansion section).

| Video | Bahgat cluster (evidence) | Clips kept | Clean added |
|---|---|---|---|
| Lagan (`MML3TRN72NQ`, 23:14) | cluster 1 — MFCC dist to karma-Bahgat 5.17 vs 8.92; medF0 155/centroid 1500 closest to karma (184/1339); guest male, so reference-distance decided, not male/female | 71 (56 high / 15 med), bahgat_0219–0289 | 7.62 min |
| Committee-girl (`y8UR7BHh0bo`, 29:09) | cluster 0 — dist 7.62 vs 10.96; cluster 1 medF0 259 is female-range (guest is a girl); cluster 0 dominates duration (850 s vs 692 s) | 104 (37 high / 67 med), bahgat_0290–0393 | 11.76 min |
| Christian debate (`qdOtUjTTLZs`, 9:22) | cluster 0 — dist 8.41 vs 9.77 (narrowest margin); medF0 188 matches Bahgat's range (karma 184, sheikh 178, komanda 170) vs 253; guest's opening "وانت مجستير عالب مقارنة الأديان" sits in cluster 1 | 38 (12 high / 26 med), bahgat_0394–0431 | 3.85 min |

- Stage A: lagan transcription redone cleanly (399 segments, 796 s — no
  repeat of the earlier SIGTERM); committee-girl 694 segments; christian
  234 segments. No new HF downloads (`HF_HUB_OFFLINE=1`).
- **New total: 431 clips, 2746.3 s (45.77 min), 259 high / 172 medium**
  (was 218 clips / 22.54 min). Zip rebuilt (78,721,311 bytes, 448 files).
  Bot tests 295 pass.

## 13. Diversity expansion — laughing + shouting rants added (→ 66.01 min); sad/crying NOT found

Seif asked for MORE videos specifically for diversity ("منا عايز ازود
الفيديوهات عشان التنوع حاسس ٣ فيديوهات دي محدوده"), then added sad/crying
moments ("و في بهجت و هو حزين و بيعيط بردو"). This phase targeted styles
only, not minutes — the total was already past the old ~35–40 min stop
point, so the rule was: stop when each gap has coverage or when 2
consecutive videos add no new style.

| Video | Style it added | Bahgat cluster (evidence) | Clips kept | Clean added |
|---|---|---|---|---|
| Funny Komanda compilation (`dBjN21s49vQ`, 44:27) | **Laughing / jokes ✓** — funniest call-ins, roasts (Whisper doesn't transcribe laughter; attested by the video itself + roast transcripts) | cluster 1 — medF0 166, medCent 964, dist 5.36 vs 9.23 | 141 (101 high / 40 med), bahgat_0432–0572 | 14.06 min |
| Train-accident live (`t5kaaMzZBj8`, 8/11/2026, 20:57) | **Shouting rant ✓** — angry ranting about the accident/Sisi, not a debate | cluster 0 — medF0 188, dist 12.72 vs 26.59; noisiest split yet (live/phone audio, mean RMS −23 dB, centroids ~2× brighter) | 56 (35 high / 21 med), bahgat_0573–0628 | 6.18 min |
| Lina live (`Oli_neDUV_Y`, 1:45:59) | **None — NOT added** | Unusable: 2002 segments, 0 sad/cry hits in the full transcript, inter-centroid distance 2.89 (lowest of any video), both speakers in both clusters. Stage B deliberately NOT run — would inject Lina's voice. Raw + transcript kept. | 0 | 0 |

- **Sad/crying clips: NOT FOUND — stated plainly.** Checked: the
  train-accident live (title says "ينهار" but the transcript is angry
  ranting, no weeping language); the full Lina-live transcript (0 hits); a
  cry/sad-marker grep across all 6 previously transcribed videos (every hit
  was a Whisper mis-read of "بكلم" etc.); web search for "بهجت صابر
  يبكي/يعيط/حزين" (no verifiable crying video — only the arrest footage,
  excluded as noisy street/panic, and keyword-stuffing on the
  committee-girl video's tags). The **Telegram clip library was NOT
  attempted** (page fetch failed with a network error, not retried) — if a
  sad clip exists anywhere, it is most likely there or in a main-channel
  live not surfaced by search.
- One kept train-accident clip is flagged in the report as a likely
  mis-clustered caller turn (feminine "انا عايزة" phrasing, F0 213.6,
  medium) — flagged, not removed.
- Skipped: Lina 30/10 live, "قوم يا مصري" short, and other laughing
  compilations — the laughing/shouting gaps were already covered.
- **New total: 628 clips, 3960.6 s (66.01 min), 395 high / 233 medium**
  (verified independently on disk). Zip rebuilt: 113,387,893 bytes
  (~108 MB), 651 files, `unzip -l` verified. Bot tests 295 pass.

## 14. Professional-practice research + improvement plan

Full research (independent web research, sources with URLs + dates):
`docs/voice-improvement-research.md` (985 lines). Headlines:

- **RVC converts timbre only; prosody comes from the source.** RVC is
  speech-to-speech: "same timing, same pauses, same emphasis, new timbre".
  No RVC knob controls rate, pauses, or style. GPT-SoVITS *can* learn
  prosody (its GPT predicts semantic tokens capturing phoneme + prosody +
  duration), but it has **no official Arabic support** (zh/ja/en/ko/yue
  only) — Egyptian prosody there is unverified.
- **Data sweet spot: 15–20 min recommended, 10–30 min practical;**
  diminishing returns beyond 30 min, flattening past ~1 h. 22.54 min was
  already in the sweet spot; 66.01 min is well past it — more minutes add
  nothing. "20 minutes of good audio beats 60 minutes of poor audio."
- **Quality, ranked:** (1) single speaker only — other voices are "the
  single most damaging inclusion"; (2) noise/reverb — models are "faithful
  copyists", echo/hum are learned as part of the voice; (3) loudness
  consistency (peaks −3 to −6 dB, never clip); (4) emotion/speed diversity
  — "a model can't invent sounds it never heard"; (5) clip length 3–15 s
  at natural pauses (ours 3–10 s fits); (6) quantity last. Gentle cleaning
  only — aggressive noise reduction creates metallic artefacts the model
  then learns.
- **Training hyperparameters:** epochs 150–300 consensus (150 is the low
  end, defensible for our data if we save every 10 and listen to
  checkpoints; >300–400 on <30 min data = overfitting); batch 4 safe on a
  T4 (8 is the other defensible value); RMVPE is the consensus F0 method;
  **40 kHz is correct** (48 kHz needs ~24 GB VRAM, buys nothing for 16 kHz
  sources or Telegram Opus); build the FAISS index (top-1 retrieval is
  what suppresses timbre leakage). Overtraining = robotic/metallic,
  especially vowels; fix is rolling back to an earlier checkpoint, not
  training longer.
- **Inference settings (none of these change speed):** index rate 0.5–0.75
  (lower first for metallic/gritty artefacts; >0.8 often adds artefacts),
  filter radius 3, RMS mix 0.25 or lower (keeps input dynamics so shouts
  stay shouts), protect voiceless consonants 0.33 (slightly lower for
  crisper s/t), transpose 0. **Speed lives in the source audio:** the bot
  currently calls Edge TTS at `rate="+5%"` — essentially Shakir's calm
  default. SSML `<prosody rate>` supports up to `+100%` (2×). Azure
  `express-as` styles are only documented for a few voices — no
  angry/shouting style for ar-EG-ShakirNeural. Post-hoc `ffmpeg atempo`
  only as a final 5–15% trim.
- **OmniVoice knobs:** `speed` (default 1.0, >1 faster) is the direct fix
  for slowness; `duration` fixes total length and overrides `speed`;
  `num_step=32` is a quality/compute dial, not a prosody dial;
  `language_id="arz"` (23.23 h) vs `"arb"` (1,483.53 h) affects dialect,
  not speed; hand-checked `ref_text` beats Whisper auto-transcribe on
  garbled Egyptian dialect; **reference-clip choice is the biggest style
  lever after `speed`**. The comparison ran at default `speed=1.0` with
  one calm reference clip — its style was never actually tested.
  Recommended 3×3 grid before writing OmniVoice off: speed {1.0, 1.2,
  1.35} × reference {calm, shouting, mid}. No documented OmniVoice
  "angry/fast/shouting" style parameter was found.

### Concrete improvement plan

**Before/during RVC training on Colab (run #2):**
1. Use the current dataset as-is: 66.01 min (628 clips), zip rebuilt
   2026-11-26 05:45 EET. No more videos — minutes past ~30 min add
   nothing; the set already covers conversation, debate, call-ins,
   argument, laughing, and shouting rants.
2. Keep RVC v2 / 40 kHz / RMVPE / batch 4 / 150 epochs, save every 10,
   build the `.index`. Listen to checkpoints (epoch 50/100/150) and roll
   back if it turns robotic/metallic — do not train longer to fix that.
3. One open choice at training time: if the first model sounds off,
   retrain on the high-confidence subset only (395 clips) — quality over
   quantity. Not the default; only if needed.

**At inference time in the bot (the actual fix for "slow" and "mediocre"):**
4. **Fix the Edge TTS source first — this is the main lever.** Rate ladder
   on real bot lines: +15% → +25% → +35%, varied by mood (calmer when
   greeting, faster when angry/insulting). Shape rhythm with short
   sentences, `!`, `<break>`, `<emphasis>` — Bahgat's rhythm is bursts,
   not a steady stream. This is what makes the voice *sound* like Bahgat
   talking, not just like his timbre.
5. RVC inference starts: index rate 0.5–0.75, filter radius 3, RMS mix
   0.25, protect 0.33, transpose 0. Change one dial at a time and listen;
   lower the index rate first if it sounds metallic.
6. Trim dead air: if generated voice notes still feel slow, a final
   `ffmpeg atempo` 1.05–1.15 trim is acceptable — never more than that.

**OmniVoice re-test (cheap, before RVC if time allows):**
7. Run the 3×3 grid on Colab (speed 1.0/1.2/1.35 × calm/shouting/mid
   reference clip) with a FAST test sentence (a rant line, not the calm
   confused sentence used before). If one combination sounds like Bahgat
   at speed, OmniVoice becomes the fast zero-shot path; if none does,
   zero-shot is closed and RVC is the only voice.

**Honest ceiling — what RVC can and cannot fix:**
8. RVC converts timbre but keeps the SOURCE audio's prosody. That means
   the speaking style comes mostly from the Edge TTS input, not from the
   training data. The realistic ceiling is "Bahgat's voice saying things
   at Bahgat-like speed" — not "an exact copy that shouts, laughs, and
   cries like him". The shouting/laughing extremes in the training data
   help the model render those sounds when the source asks for them, but
   they cannot inject shouting into a calm source line. GPT-SoVITS is the
   only prosody-learning fallback in the package, and its Arabic is
   unverified — try it only if RVC + the TTS-rate ladder still sounds
   flat.

## 15. Files index

| Path | What it is |
|---|---|
| `training/raw/karma.opus` | Only downloaded voice video (28:41) |
| `training/raw/MANIFEST.md`, `manifest.json` | Download manifest + retry log (`training/raw/retry-log.txt`) — now covers 11 videos (karma, sheikh, komanda, lagan, committee-girl, christian, lina-live, funny-komanda, train-accident) |
| `training/clean/bahgat_*.wav` (628) | Clean solo-Bahgat clips, 66.01 min total (395 high / 233 medium) |
| `training/clean/filelist.txt` | 628 kept clips, one path per line |
| `training/clean/xtts_reference.wav` | 7.16 s zero-shot reference clip |
| `training/clean/cleaning_report.md` | Full cleaning report + per-clip table + expansion + diversity sections |
| `training/transcripts/karma_full.json` / `.txt` | Full transcript (654 segments, 2,344 words) — plus sheikh/komanda/lagan/committee-girl/christian/funny-komanda/train-accident/lina-live full transcripts |
| `training/samples/xtts_sample.wav` | XTTS v2 zero-shot output (5.75 s) — REJECTED by Seif |
| `training/samples/omnivoice_sample.wav` | OmniVoice zero-shot output (5.67 s, 24 kHz) — Seif: timbre close, style mediocre, feels slow |
| `training/samples/zero_shot_notes.md` | Measured notes on the XTTS sample |
| `docs/voice-improvement-research.md` | Professional-practice research (985 lines, sources) + bottom line for this project |
| `~/workspace/bahgat_dataset.zip` | Dataset for Colab: training/clean/ + training/transcripts/ — 113,387,893 bytes, 651 files |
| `training/work/` | Scratch: 16 kHz WAV, transcribe/pitch/MFCC scripts, manifests, rejected clips, `venv-xtts/` (5.5 GB, deletable) |
| `training/colab/bahgat_rvc_gpt-sovits_training.ipynb` | RVC (primary) + GPT-SoVITS (fallback) training notebook |
| `training/colab/rvc_config.md`, `gpt-sovits_config.md` | Exact training configs |
| `training/colab/bahgat_zeroshot_omnivoice_vs_xtts.ipynb` | OmniVoice vs XTTS comparison notebook |
| `training/colab/voicestudio_evaluation.md` | VoiceStudio evaluation (verdict: complement) |
| `training/colab/README.md` | Colab package README (both notebooks) |
| `docs/voice-training-report.md` | This report |
| `docs/training-videos.md`, `docs/voice-plan.md` | Original plan + video lists |

## 16. Shorts batch + curated 30–45 min set (2026-11-26)

Context: the pro-techniques audit (`~/workspace/research_notes/bahgat-voice-pro-techniques-2026-20261126-0625/report.md`,
verdict (b) — change settings, do not proceed as-is) flagged three things
before any RVC training: (1) 16 kHz source audio is a weak link — re-extract
at native 44.1/48 kHz; (2) F0/MFCC clustering is not real diarization —
contamination risk, audit or spot-check; (3) curate the BEST 30–45 min
instead of training on all 66 min; train RVC 2.3 to 300 epochs (not 150).
Seif then sent 15 short videos of Bahgat in different situations (mostly
seconds long) and asked to put them in the training, then pick the best
minutes after using them.

### Shorts — 15 files, 13 unique contents, 2 usable

Files copied to `training/raw/shorts/` (`short_01.mp4` … `short_15.mp4`,
originals untouched in the media library). Total 120.0 s raw. All have an
AAC audio track (44.1 kHz, one 48 kHz), 320×416 to 1280×720 video.
Duplicates found by decoded-audio MD5 (identical size alone was not
trusted): **short_05 = short_01** and **short_11 = short_03** — same audio
bit-for-bit. So 15 files = 13 unique contents. (Seif said "4 more" in the
second message but 5 files arrived — the 5th is short_11, the duplicate of
short_03; no content was lost, one was sent twice.)

Method: same as the long videos but adapted — extract native-rate mono WAV
+ a 16 kHz analysis copy, transcribe with cached faster-whisper small
(`HF_HUB_OFFLINE=1`, no new downloads), per-segment F0/centroid/RMS +
MFCC distance to the karma-Bahgat reference + spectral flatness, plus two
extra checks: (a) background level in the gaps between Whisper segments
(speech ≈ -13 dB; quiet gaps < -35 dB; music/noise shows as loud gaps),
(b) a speed-up test — resampling each short at 1/1.25, 1/1.5, 1/1.75, 1/2
and re-measuring F0 + MFCC distance, to test whether high pitch is just a
sped-up TikTok edit.

**Result: only 2 of 15 files usable (13.1 s, 0.22 min).** The rest fail on
evidence, not on suspicion:

| Short | Dur | Med F0 | MFCC dist | Verdict |
|---|---|---:|---:|---|
| short_01 | 11.98 s | 179 Hz | 8.2 | **KEEP → bahgat_0629.wav (9.94 s, medium)** — clean solo Bahgat, gaps -47 dB, no music |
| short_02 | 5.48 s | 285 Hz | 14.5 | DROP — female-range pitch, "يا أم" content |
| short_03 = short_11 | 9.49 s | 260 Hz | 15.9 | DROP — duplicate pair; high pitch, far MFCC |
| short_04 | 12.20 s | 248 Hz | 10.2 | DROP — Bahgat-style rant but F0 at the edge + loud gaps (-21.8 dB, music/noise under speech) |
| short_05 | 11.98 s | 179 Hz | 8.2 | DROP — exact duplicate of short_01 |
| short_06 | 6.87 s | 282 Hz | 12.9 | DROP — high pitch, far MFCC |
| short_07 | 16.02 s | 328 Hz | 10.1 | DROP — very high pitch + loud gaps (-21.6 dB) |
| short_08 | 6.22 s | 314 Hz | 22.4 | DROP — farthest from Bahgat of all shorts; female-sounding greeting |
| short_09 | 5.53 s | 352 Hz | 9.9 | DROP — mixed speakers; only 1.3 s is Bahgat-like (F0 166), too short for a 3 s clip |
| short_10 | 7.11 s | 306 Hz | 16.8 | DROP — female speaker ("أنا حامل") |
| short_12 | 3.48 s | 346 Hz | 14.0 | DROP — high pitch; only 2.6 s of speech, too short anyway |
| short_13 | 7.24 s | 280 Hz | 12.5 | DROP — high pitch, far MFCC |
| short_14 | 3.72 s | 274 Hz | 10.2 | DROP — high pitch; only 1.76 s of speech |
| short_15 | 3.16 s | 183 Hz | 4.7 | **KEEP → bahgat_0630.wav (3.16 s, high)** — closest MFCC match of all shorts, clean gaps (-42 dB) |

Speed-up test outcome: slowing any short down only made its MFCC distance
to Bahgat WORSE (monotonically, at every rate) — so the high-pitch shorts
are **not** sped-up Bahgat; they are other speakers (women/children) or
Bahgat doing a falsetto/high voice, and they stay out of the dataset.
Per the brief, ambiguous clips were dropped rather than risking
contamination — short clips are cheap, contamination is expensive.

Kept clips added to `training/clean/` as bahgat_0629 (short_01, 1.14–11.08 s,
9.94 s, medium, 44.1 kHz) and bahgat_0630 (short_15, 0–3.16 s, 3.16 s,
high, 44.1 kHz); `filelist.txt` now has 630 lines. Per-short manifest:
`training/work/shorts_clips_manifest.json`; stage-A script
`training/work/shorts_stageA.py`, stage-B `training/work/shorts_stageB.py`.

### Curated set — 38.76 min (367 clips) at native rate

Selection (`training/work/curate.py`): from the full 630-clip pool, high
confidence first, then closest to the video's median RMS and F0 ~180 Hz,
with style quotas. Excluded with reasons (19 clips, listed in
`training/curated/curation.json` + `CURATED.md`): the confirmed
mis-clustered caller clip bahgat_0576 (feminine "انا عايزة", F0 213.6 —
flagged in the cleaning report), 4 clips with first-person feminine markers
+ F0 > 220 Hz (bahgat_0114, 0120, 0528, 0535 — ambiguous speaker), and 14
clips >10 dB quieter than their video's median RMS (low-SNR tails, mostly
the christian debate tail at -35 to -39 dB). A broader feminine-word scan
of all 630 transcripts was mostly false positives (Bahgat talking *about*
women — "مراتي", "حامل" about his wife — not women speaking), so only
first-person markers + high F0 counted.

| Style | Clips | Duration |
|---|---:|---:|
| debate (karma/sheikh/komanda/committee-girl/christian) | 159 | 1020.4 s (17.01 min) |
| laughing / jokes (funny-komanda) | 102 | 621.1 s (10.35 min) |
| live calls (lagan) | 54 | 343.9 s (5.73 min) |
| shouting rant (train-accident — all available after exclusions) | 50 | 326.9 s (5.45 min) |
| shorts (both kept clips) | 2 | 13.1 s (0.22 min) |
| **TOTAL** | **367** | **2325.4 s (38.76 min)** |

Re-extraction: each curated clip was re-cut at **native rate — 48 kHz mono**
from the raw `.opus` masters (`training/work/<video>_48k.wav`, pure decode,
opus is natively 48 kHz; shorts stay at their native 44.1 kHz) into
`training/curated/clips/`. The 16 kHz files were NOT upsampled. All 367
clips ffprobe-verified (48 kHz mono, 44.1 kHz for shorts, duration within
0.15 s of manifest). List: `training/curated/CURATED.md`, machine-readable
`training/curated/curation.json`. Zip:
`~/workspace/bahgat_dataset_curated.zip` (367 clips) — this is the RVC
training set. The full-set zip `~/workspace/bahgat_dataset.zip` was
rebuilt with the 2 shorts clips (630 clips) and is kept as the reserve.

### Zero-shot reference candidates

`training/curated/REFERENCE_CANDIDATES.md` — 3 clips from the curated set
for the audit's §4 VoiceTut/OmniVoice test grid: rant bahgat_0621.wav
(9.30 s, F0 193.2, train-accident), laughing bahgat_0470.wav (7.68 s,
F0 172.9, funny-komanda), call bahgat_0265.wav (8.30 s, F0 154.3, lagan),
each with a hand-corrected Egyptian-orthography transcript + the raw
Whisper text. **Warning in the file: the transcripts are best-effort
reconstructions from garbled Whisper output — listen and fix by ear on
Colab before using as `ref_text`, or a wrong transcript teaches wrong
phonemes.**

### What this changes for the RVC run

- Train on `bahgat_dataset_curated.zip` (38.76 min), NOT the full 66 min.
- RVC 2.3 mainline, v2, 40 kHz, RMVPE, batch 4, **300 epochs, save every
  10**, listen at 150/200/250/300, build the FAISS index (audit §2).
- The dataset is now native-rate throughout; the 16 kHz weakness is fixed
  for the training set (the full 630-clip set in `training/clean/` is
  still mixed 16 kHz + 44.1 kHz and is a reserve, not the training set).
- Speaker-separation audit: spot-check done (19 exclusions above); the
  remaining risk is the medium-confidence tier (~90% Bahgat per the
  cleaning report) — pyannote 3.1 diarization was NOT run (gated model,
  needs an HF token + download; brief forbids new HF downloads).

## 17. Shorts salvage attempt (2026-11-26)

Audit-driven salvage (§5 of the shorts-salvage research report): triage by
identity first, BS-RoFormer separation + gentle denoise, strict gate;
survivors quarantined, never merged without a labelled second training run.

**Result: 1 borderline survivor, 5.44 s (0.09 min). Nothing merged.**
Segment-level re-check of all 13 dropped shorts found exactly one plausible
Bahgat segment: **short_04 seg 1 (0–5.44 s)** — F0 216.5 Hz (shouting;
inside the curated shouting spread 213–246 Hz), MFCC dist 7.96 to the karma
ref and 8.54 to the train-accident shouting ref (both inside the
confirmed-Bahgat spreads), insult-rant content, centroid 1427 Hz. The
other 12 shorts are dropped for good: wrong speaker / falsetto (F0
232–380 Hz, MFCC 10–22), one female ("أنا حامل"), duplicates, mixed
speakers with <3 s of Bahgat-like audio.

BS-RoFormer (Viperx 1297) separation on the segment took 10.5 min on CPU
and removed almost nothing — instrumental stem RMS −77.3 dB — proving the
segment had no music bed; its pauses were already quiet (−57 dB). Denoise
was skipped (no steady floor; DeepFilterNet 3 does not run in this venv —
`df` 0.5.6 vs torchaudio 2.11 API mismatch). Gate on the survivor
(`training/work/salvage/curated_additions/short_04_seg1_salvaged.wav`,
48 kHz mono, peak −3 dB): F0 unchanged 216.5 Hz, MFCC 8.39, 16/16 Whisper
words, pause floor −60.3 dB, flatness unchanged. **Borderline because F0
fails the literal 170–190 Hz gate band and the file's other half is another
speaker — the owner must listen and confirm it is Bahgat shouting before
any use, and 5.44 s is below the ≥1 min bar for a second training run
anyway.** Full details: `training/work/salvage/SALVAGE_REPORT.md`.
Curated set unchanged: 38.76 min / 367 clips.

## 18. Pre-Colab completion audit + final verification (2026-11-26)

All pre-Colab work finished the same day; Colab itself (GPU runs, Drive
upload) is Seif's step. Final-check research verdict (2026-11-26 09:39 EET):
**READY for Colab, conditional on the §3a must-dos** — nothing new had been
released since the morning audits, so no plan change, only additions, all
folded in below.

### Phase 1 — contamination spot-check: PASS, 0 drops

Seed 42, random 10% per source video, **37 clips**; F0 (numpy
autocorrelation) + MFCC distance to the karma-Bahgat reference +
first-person feminine markers in the transcripts; contamination only on
convergent evidence (F0 > 220 Hz AND a marker or MFCC clearly outside the
set's own spread). **0/37 contaminated, no video cluster over 5%.** The two
transcript flags were false positives on manual review (garbled Whisper:
"بم حامل بم"; "حسابة" = account). Caveats: MFCC distance is confounded by
recording conditions (video medians karma 6.78 → train-accident 14.16; all
19 clips above global p95 are train-accident); 6 clips sit above 220 Hz in
the population; **a spot-check is not a guarantee** — the listening list
below is the real speaker gate. Details: `training/work/audit_curated_section.md`,
`audit_curated.py`, `audit_curated_results.json`.

### Phase 2 — loudness / clipping / QC: the clipping was a conversion artifact

Before (367 clips): 80 clips peak ≥ −0.5 dBFS, **59 with samples pinned at
0 dBFS** (flat-top runs up to 42 samples; lagan 54/54). The float decode of
the raw `.opus` masters proves the clipping is **NOT in the source** — peaks
at 1.19–1.35 with smooth rounded tops and no plateau (longest near-1.0 run
is 4 samples in 23 min of lagan). Root cause: `curate.py` decoded opus with
a naive `pcm_s16le` call — no headroom — clamping everything above 1.0.
**The 59 clips were re-extracted from the raw opus float with headroom**
instead of dropped (calibration: ffmpeg f32 reads exactly √2 hotter than
s16; 0.5 s preroll fixes Opus cold-seek priming; control re-extraction of
unclipped bahgat_0016 reproduces the existing file to 1 LSB; F0/MFCC on 3
recovered clips unchanged within noise). This is a correct re-decode, not
normalising down a clipped clip.

**Loudness target: −3 dB peak** (linear gain only, no compression). −16 LUFS
was rejected: it would push rant peaks (median −0.72 dBFS) over 0 dBFS into
fresh clipping, and it applies style-dependent gains that distort natural
dynamics. After: **0 pinned samples, 0 clips ≥ −0.5 dBFS, every clip peaks
at exactly −3.00 dBFS**; LUFS spread narrowed 17.7 → 13.0 LU. Honest
dynamics check: rant does NOT measure louder than debate in median RMS/LUFS
(before or after) — it measures louder in **peak and crest** (rant crest
18.98 vs debate 12.86): shouting is bursty, debate is dense. That ordering
is preserved exactly. No high-pass (LF <80 Hz share median 0.0004).
QC script `training/work/qc_curated.py`: final run on the 361-clip set =
**0 FAILs**.

**Drops (phase 2 only, 6 clips / 38.9 s):** bahgat_0598 (13.92 s, over the
11 s hard limit) + 5 funny-komanda near-duplicates of komanda turns
(0547/0552/0553/0560/0563 — same Bahgat turn reused by the compilation,
MFCC 0.17–0.92, matching transcripts; primaries kept). Recorded in
`curation.json` `audit_exclusions` + `CURATED.md`. Details:
`training/work/loudness_audit.md`, `loudness_audit.json`,
`loudness_audit_before.json`, `qc_curated.json`.

### Final totals (post-audit)

**361 clips, 2286.5 s (38.11 min)** — debate 159 / 1020.2 s, laughing 97 /
595.6 s, calls 54 / 344.3 s, rant 49 / 313.0 s, short 2 / 13.1 s. Zip
rebuilt: `~/workspace/bahgat_dataset_curated.zip` (190,973,322 bytes,
361 WAVs verified with `unzip -l`). Pre-normalisation zip kept at
`training/work/bahgat_dataset_curated_pre-norm_2026-11-26.zip` (367 clips).
Notebooks, README, configs and checklist all updated to these totals.
`training/clean/` and the full-set zip were NOT touched.

### Listening gate — NOT done, Seif's step

Stratified list: `training/work/listening_list.md` (also committed as
`docs/colab-listening-list.md`) — **75 clips, 7.70 min**, all styles + all
source videos + all phase-1 outliers. **100% rule: if ANY wrong-speaker
clip is found in the sample, the WHOLE style / source video it came from
gets 100% re-listening before training. Do not launch Colab on statistics
alone.** Train-accident dominates the list (27/75) by design — it is the
residual risk cluster (noisiest split, all MFCC outliers, 5 of 6 F0 > 220 Hz
clips).

### §3a final-check additions folded into the notebooks/checklist

Frozen ref_texts (2026-11-26, byte-identical to `REFERENCE_CANDIDATES.md`)
+ 5 fixed 10-word test sentences (debate / joke / rant / fast-profanity /
code-switch) in the VoiceTut grid; `guidance_scale` held constant at 2.0;
`[laughter]` behaviour logged per cell; IndexTTS pitfalls recorded
(`duration_factor` inverted, `use_emo_text` requires `use_qwen_emo=True`,
`emo_alpha` ~0.6); extra donor cell #9 — voicetut-egyptian-emotion
(HF `masterofaudio2077/voicetut-egyptian-emotion`, `[shouting]` /
`[furious, barely holding it together]`, **donor only**, loudness-preserving
tokenisation); RVC notebook: pretrained `f0G40k`/`f0D40k` verified present
before launch, FCPE as named fallback if RMVPE pitch wobbles on shouting
(note: at RVC tag 2.3.260718 `extract_f0.py` hard-codes RMVPE — check the
checked-out repo's FCPE entry point at run time, do not guess a flag),
checkpoint-retention rule (save every 10, small `.pth` at 150/200/250/300,
skip intermediate D ckpts, verify each Drive copy before deleting local);
checklist: Drive space check (5 GB vs 15 GB, empty Trash), zip → copy to
`/content` → extract → train from local disk, ~10-clip dry run, `nvidia-smi`
T4 check, alphanumeric folder name (`bahgat_40k_v2`), rant scored
**separately** at each listening checkpoint (rant is only ~14% of the set
and will be the weakest style).

### Salvage note (final-check item 7)

For any future salvage run: add an **NISQA/objective gate** alongside the
listening gate; note the sample-rate handoff — BS-RoFormer works at
44.1 kHz, DeepFilterNet 3 at 48 kHz. The 2026-11-26 salvage itself (§17)
yielded 1 borderline 5.44 s survivor, quarantined, not merged.

### Warning — the 16 kHz full set carries the same clamping artifact

`training/clean/` was NOT touched by this audit, and it has the SAME
int16-clamping artifact (verified: 16 kHz 0262/0220/0590 have 107/117/110
pinned samples; control 0016 has 0). **If the 66-min reserve set is ever
used for training, re-decode it from the opus float first** (same
procedure as §2 above).

Bot tests after all of this work: **315 pass**; no bot runtime code changed.
