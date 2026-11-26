# Bahgat voice training — Colab package

Train a Bahgat Saber voice model from the clean dataset, on a **free** Google
Colab GPU. No paid services, no local GPU needed.

**Run order: the zero-shot grid FIRST, RVC training SECOND.**

1. **`bahgat_voicetut_grid.ipynb`** — VoiceTut-TTS vs base OmniVoice vs
   IndexTTS 2.5 vs `voicetut-egyptian-emotion` donor, 9 test cells, ~30–60 min. It may make RVC training
   unnecessary (or give a far better donor voice for RVC). **Run this first.**
2. **`bahgat_rvc_gpt-sovits_training.ipynb`** — RVC 2.3 training (**primary**,
   only if the grid says the zero-shot engines are not close) + GPT-SoVITS
   **v2Pro** as the fallback (only if RVC fails or sounds wrong — Arabic is
   not in its officially supported language list, see below).

## Files in this folder

| File | What it is |
|---|---|
| `bahgat_voicetut_grid.ipynb` | **Run FIRST** — VoiceTut-TTS (`arz`) vs base OmniVoice (`arz`) vs IndexTTS 2.5 (AR) vs `voicetut-egyptian-emotion` donor (#9), 9-cell grid, listening scorecard inside |
| `bahgat_rvc_gpt-sovits_training.ipynb` | **Run SECOND (only if the grid says so)** — RVC 2.3, 300 epochs + GPT-SoVITS v2Pro fallback |
| `rvc_config.md` | Exact RVC repo, commands and hyperparameters (reviewable without opening Colab) |
| `gpt-sovits_config.md` | Same for the GPT-SoVITS v2Pro fallback |
| `bahgat_zeroshot_omnivoice_vs_xtts.ipynb` | Older zero-shot comparison (OmniVoice vs XTTS v2) — superseded by the VoiceTut grid; kept for reference |
| `voicestudio_evaluation.md` | VoiceStudio/OmniVoice evaluation — verdict: complement, do not replace the RVC setup |
| `README.md` | This file |

## Prerequisites

- A **Google account** (for Colab + Google Drive) — Seif's is
  `seifallahmr@gmail.com`.
- The **dataset zip**: `bahgat_dataset_curated.zip` — **182 MB, 361 clips,
  38.11 min total, 48 kHz mono WAV, 3–10 s each** (`training/curated/clips/
  bahgat_*.wav`; 359 clips @ 48 kHz, 2 @ 44.1 kHz). All clips are
  **peak-normalised to −3 dBFS** (2026-11-26 loudness audit, §18 in
  `docs/voice-training-report.md` — 6 clips dropped, 59 recovered from a
  clean re-decode). **No transcripts in this
  zip** (RVC does not need them; GPT-SoVITS does — see §4 note in the training
  notebook). Upload it to the **root of Google Drive** ("My Drive", not
  inside a folder).
- **~30–60 min** of Colab GPU time for the VoiceTut grid; **~4.5–6.5 h** for
  RVC training (300 epochs — estimate, unmeasured; resumable from Drive
  checkpoints if Colab disconnects).
- Nothing to install locally. Do not run any of this on your own machine —
  there is no GPU here and Colab needs an interactive browser session.

## Step-by-step run order

### 1. VoiceTut grid (FIRST)

1. Go to https://colab.research.google.com → **Upload** →
   `bahgat_voicetut_grid.ipynb`.
2. **Runtime → Change runtime type → Hardware accelerator → T4 GPU.**
   Verify the GPU check cell (§0) shows a T4 before continuing.
3. Upload `bahgat_dataset_curated.zip` to the root of your Google Drive.
4. Run the notebook **top to bottom, in order**:
   - §0 GPU check (`nvidia-smi`)
   - §1 Setup: `pip install voicetut-tts` (+ OmniVoice backbone from GitHub)
   - §2 Reference clips: the 3 candidates are copied from the curated zip —
     **listen to each and verify its transcript by ear before it is used as
     `ref_text`** (a wrong `ref_text` teaches wrong phonemes)
   - §3 Test sentences: 5 fixed Egyptian lines (debate / joke / shouting
     rant / fast profanity-heavy / code-switching Arabic+English, 10 words
     each) — the same five in every cell, including the donor cell #9
   - §4 The 9-cell grid: VoiceTut `arz` rant (#1), VoiceTut `arz` laughing +
     `[laughter]` (#2), VoiceTut `arb` (#3), base OmniVoice `arz` (#4),
     VoiceTut auto `ref_text` (#5), VoiceTut speed 1.25 (#6), VoiceTut
     `num_step` 16 (#7), IndexTTS 2.5 AR + shouting emotion ref (#8),
     `voicetut-egyptian-emotion` donor with `[shouting]`/`[furious, …]` tags
     (#9 — **donor only**, single synthetic voice, cloning unsupported;
     RVC re-timbres it afterwards, it can never BE the Bahgat voice).
     `guidance_scale` is held constant at **2.0** for all VoiceTut/OmniVoice
     cells (it is not a grid variable). The `[laughter]` tag is an open test,
     not an assumed feature — log per cell whether it was read aloud /
     ignored / actually laughed (plain VoiceTut/OmniVoice may read the tag
     aloud). IndexTTS pitfalls: `duration_factor` is inverted vs VoiceTut
     speed (>1.0 slows, <1.0 speeds; 0.8 = faster); `use_emo_text=True`
     requires `use_qwen_emo=True` or it raises `RuntimeError`; with
     `use_emo_text`, `emo_alpha` ~0.6 or lower is recommended for natural
     speech.
   - §5 Measurement: words/s on speech-only + % silence (ffmpeg
     `silencedetect`, no Whisper needed)
   - §6 Scorecard: fill in by ear (timbre / dialect / pace, 1–5)
   - §7 Export to `My Drive/bahgat_voice_models/voicetut_grid_2026-11-26/`
5. **Apply the decision rule:** if grid #1/#2 are close on timbre **and**
   pace (≥4/5 on both) → **skip RVC training** (or use VoiceTut as the RVC
   donor). Otherwise continue to step 2.

### 2. RVC training (SECOND — only if the grid says so)

1. Upload `bahgat_rvc_gpt-sovits_training.ipynb` to Colab (same T4 runtime;
   the Drive upload from step 1 is already done).
2. Run top to bottom:
   - §0 GPU check
   - §1 RVC setup: clone the official RVC repo (**tag `2.3.260718`**), install
     deps, download pretrained weights (HuBERT, RMVPE, v2 40k base)
   - §2 Dataset: mount Drive, unzip `bahgat_dataset_curated.zip`, audit
     (sample-rate/duration check), hold out 5 clips for listening tests
   - §3 **RVC training (primary)**: preprocess → RMVPE F0 → HuBERT features →
     **train 300 epochs, batch 4, save every 10** → build the `.index`.
     A background cell copies every new checkpoint to Drive every 10 min
     (continuous backup — start it before the training cell).
   - §4 GPT-SoVITS training (**fallback only**): clone, pretrained **v2Pro**
     weights, build `.list`, prep (text → HuBERT → semantic), train SoVITS
     8 epochs then GPT 15 epochs. **Needs per-clip transcripts — the curated
     zip has none; supply them first or skip §4.**
   - §5 Export: zip the finished weights back to Drive
   - §6 Resume / troubleshooting (read before you need it)
   - §7 What to do next — **listen at 150 / 200 / 250 / 300 and keep the
     best checkpoint by ear**
3. **Keep the browser tab open** while training runs. Closing it kills the
   session.

## Expected outputs (on Drive, `My Drive/bahgat_voice_models/`)

| File | Contents | When |
|---|---|---|
| `voicetut_grid_2026-11-26/` | `grid_01…09_*.wav` (45 test outputs: 9 cells × 5 sentences) + 3 reference clips + `measurements.json` + `scorecard.md` + `grid_notes.json` | After the grid (§7) |
| `bahgat_rvc_v2_40k_YYYYMMDD.zip` | `bahgat.pth` (~70–80 MB, inference weights) + `added_*.index` (retrieval index) + README.txt | After RVC training (§3 + §5) |
| `bahgat_gpt-sovits_v2pro_YYYYMMDD.zip` | `s2G*.pth` + `s2D*.pth` (SoVITS) + `s1bert25hz-*-e15.ckpt` (GPT) + README.txt | Only if you ran §4 |
| `checkpoints_rvc/` | `G_*.pth` / `D_*.pth` checkpoints (latest 2 pairs) + `bahgat_latest_small.pth` | Continuously during §3 training |

Download the zip(s) and do a **listening test** (convert a holdout clip and a
fresh donor-TTS sample) before wiring anything into the bot. **Donor note:**
do not use calm Edge TTS `ar-EG-ShakirNeural` as the primary donor — RVC keeps
the donor's prosody, so a calm donor stays calm in Bahgat's timbre. Prefer a
fast/loud Egyptian donor: the VoiceTut grid winner, a human Egyptian speaker,
or IndexTTS 2.5 with a shouting emotion reference (see `docs/voice-plan.md`,
v3). The bot stays labelled a parody bot.

## Chosen hyperparameters (short version)

- **VoiceTut grid (first):** `arz` first, manual `ref_text` (frozen 2026-11-26,
  verified by ear — see `training/curated/REFERENCE_CANDIDATES.md`), the 5
  fixed 10-word test sentences in every cell, `guidance_scale` held constant
  at **2.0**, speed 1.0 / 1.25, `num_step` 32 / 16, `[laughter]` tag on the
  joke line (test #2 only — log read-aloud / ignored / laughed per cell);
  IndexTTS 2.5 `AR`, `duration_factor` 0.8, shouting emotion ref; emotion
  donor #9 (`voicetut-egyptian-emotion`, `[shouting]` / `[furious, …]` tags,
  donor only — its loudness-preserving tokenisation is the mechanism if it
  wins on shouting).
- **RVC (primary):** **2.3** (`2.3.260718`), v2, **40 kHz** (48 kHz needs
  ~24 GB VRAM and buys nothing audible for Telegram voice notes), F0 on with
  **RMVPE** on CUDA, **batch 4**, **300 epochs**, save every 10, listen at
  **150 / 200 / 250 / 300** and keep the best, `-sw 1`. Full rationale in
  `rvc_config.md`.
- **GPT-SoVITS (fallback):** **v2Pro** (v4 needs 8 GB min / 16 GB recommended
  — marginal on a 15 GB T4; v5 is untagged/unverified), SoVITS **8 epochs**
  batch 4, GPT **15 epochs** batch 4. Full rationale in `gpt-sovits_config.md`.

## Known Colab free-tier limits (read this before starting)

Google publishes almost none of these exactly — the numbers below are the
documented/consistently reported ones as of Nov 2026, and Google says limits
"vary over time":

- **12 hours max per session** (free tier). After that the VM is deleted.
  Export to Drive well before that. The 300-epoch run (~4.5–6.5 h) fits, but
  only just with setup + listening.
- **Idle disconnect after ~90 minutes** of no interaction (unpublished,
  varies). A running training cell counts as active, but don't rely on it —
  keep the tab open and don't walk away for hours.
- **GPU is not guaranteed.** At peak times you may get CPU-only or no GPU.
  Retry later / off-peak. Weekly GPU hours are rationed dynamically
  (~15–30 h reported, unpublished). If you get throttled, wait a day — or use
  **Kaggle as the backup** (30 GPU-hours/week published, 2× T4, runs with the
  tab closed; see `docs/colab-start-checklist.md`).
- **No background execution** on free tier (Pro+ only). Closing the browser
  stops the run.
- **VM disk (~35–78 GB) is ephemeral** — everything not copied to Drive is
  wiped when the session ends. The §3 continuous-backup cell exists for this.
- **Drive is 15 GB free** (shared with Gmail/Photos) — **but new accounts may
  default to 5 GB** (full 15 GB only after phone verification), so check
  **one.google.com/storage** before launching and empty Trash (trashed files
  still count). Export only finished weights, not full `logs/` folders
  (several GB). Checkpoint rule: save every 10 epochs, extract the small
  `.pth` at 150/200/250/300, skip syncing intermediate D checkpoints, and
  verify each Drive copy (size + timestamp) before deleting the local copy.

### How to resume after a disconnect

1. Start a new session, re-run §0–§2 (GPU check, clone+install, pretrained
   download, dataset unzip) — ~15 min.
2. Copy backed-up checkpoints from
   `Drive/bahgat_voice_models/checkpoints_rvc/` back into `logs/bahgat/`
   (the §3 continuous-backup cell copies them every 10 min while training
   runs, so they should already be there).
3. Re-run preprocess + F0 + HuBERT (~10 min — they live on the wiped VM disk).
4. Re-run training with the **latest checkpoint as the pretrained weights**
   and the **remaining** epoch count, e.g. stopped at epoch 80 of 300 →
   `-te 220 -pg logs/bahgat/G_80.pth -pd logs/bahgat/D_80.pth`.
5. GPT-SoVITS resumes the same way from `logs/bahgat/ckpt/`.

## Troubleshooting (short version — full list in notebook §6)

- `CUDA out of memory` → batch 4 → 2 (`-bs 2`), keep `-c 0`.
- `ModuleNotFoundError: av` / fairseq errors → old notebook/checkout; this
  package uses RVC 2.3, which needs neither.
- RVC WebUI won't open → expected on free Colab; use the CLI cells.
- GPT-SoVITS rejects language `ar` → set `LANG = "en"` in the `.list` cell
  and re-run §4 (Arabic is not officially supported by GPT-SoVITS).
- GPT-SoVITS `.list` cell asserts "no transcripts found" → the curated zip
  has no per-clip transcripts; supply them first or skip §4.
- `hf download` 404 on a pretrained file → the filename changed upstream;
  check the repo README and adjust the include/allow lists.
- `git checkout 2.3.260718` fails → the tag is missing; drop the checkout line
  and use main, then confirm `git log` is Jul 2026 or later.
- No GPU allocated → wait and retry off-peak; do not train on CPU. Kaggle is
  the backup (see above).

## Notes / caveats

- The notebooks were **not** run end-to-end here (no GPU in this environment,
  and Colab needs an interactive session). They were validated as JSON/nbformat
  only, plus a syntax check of the code cells. A human must run them in Colab;
  the `--help` inspection cells in §4 exist because GPT-SoVITS prep/train flags
  can drift between repo versions. Install commands were verified against the
  upstream pages on 2026-11-26 (VoiceTut PyPI `voicetut-tts` 0.1.1, RVC
  release `2.3.260718`, IndexTTS 2.5 repo README).
- Exact-match claim: none of the training was executed; epoch/time estimates
  are scaled from the cited community sources, not measured runs. The 300-epoch
  time (~4–6 h) is a linear scaling of the old 150-epoch/~15-min estimate —
  watch the first 10 epochs and extrapolate.
- Prepared 2026-11-26 for the Bahgat bot project. Dataset contract:
  `training/curated/clips/` (361 clips, 38.11 min, 48 kHz mono — 359 @ 48 kHz,
  2 @ 44.1 kHz, 3–10 s each). Full 66-min set (628 clips, 16 kHz) is kept as
  reserve, not trained on.
