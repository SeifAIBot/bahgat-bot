# Bahgat voice training — Colab package

Train a Bahgat Saber voice model from the clean dataset, on a **free** Google
Colab GPU. No paid services, no local GPU needed.

Two routes in one notebook. **RVC is primary** (do it first); **GPT-SoVITS is
the fallback** (only if RVC fails or sounds wrong — Arabic is not in its
officially supported language list, see below).

## Files in this folder

| File | What it is |
|---|---|
| `bahgat_rvc_gpt-sovits_training.ipynb` | The notebook — upload to Colab and run top to bottom |
| `rvc_config.md` | Exact RVC repo, commands and hyperparameters (reviewable without opening Colab) |
| `gpt-sovits_config.md` | Same for the GPT-SoVITS fallback |
| `README.md` | This file |

## Prerequisites

- A **Google account** (for Colab + Google Drive).
- The **dataset zip**: `bahgat_dataset.zip` — a zip of `training/clean/`
  (16 kHz mono WAV clips, 3–10 s each, `bahgat_*.wav`) + `training/transcripts/`
  (one `.txt` per clip). Built by the dataset/clean job; **10+ minutes of clean
  audio minimum** (10–30 min ideal). Upload it to the **root of Google Drive**
  ("My Drive", not inside a folder).
- **~1–2 hours** of Colab GPU time for RVC (~1–1.5 h for GPT-SoVITS if you run it).
- Nothing to install locally. Do not run any of this on your own machine —
  there is no GPU here and Colab needs an interactive browser session.

## Step-by-step run order

1. Go to https://colab.research.google.com → **Upload** →
   `bahgat_rvc_gpt-sovits_training.ipynb`.
2. **Runtime → Change runtime type → Hardware accelerator → T4 GPU.**
   Verify the GPU check cell (§0) shows a T4 before continuing.
3. Upload `bahgat_dataset.zip` to the root of your Google Drive.
4. Run the notebook **top to bottom, in order**:
   - §0 GPU check (`nvidia-smi`)
   - §1 RVC setup: clone the official RVC repo (pinned commit), install deps,
     download pretrained weights (HuBERT, RMVPE, v2 40k base)
   - §2 Dataset: mount Drive, unzip, audit (sample-rate/duration check),
     hold out 5 clips for listening tests
   - §3 **RVC training (primary)**: preprocess → RMVPE F0 → HuBERT features →
     train 150 epochs, batch 4 → build the `.index`
   - §4 GPT-SoVITS training (**fallback only**): clone, pretrained v2 weights,
     build `.list`, prep (text → HuBERT → semantic), train SoVITS 8 epochs
     then GPT 15 epochs
   - §5 Export: zip the finished weights back to Drive
   - §6 Resume / troubleshooting (read before you need it)
   - §7 What to do next
5. **Keep the browser tab open** while training runs. Closing it kills the session.

## Expected outputs (on Drive, `My Drive/bahgat_voice_models/`)

| File | Contents | When |
|---|---|---|
| `bahgat_rvc_v2_40k_YYYYMMDD.zip` | `bahgat.pth` (~70–80 MB, inference weights) + `added_*.index` (retrieval index) + README.txt | After §3 + §5 |
| `bahgat_gpt-sovits_v2_YYYYMMDD.zip` | `s2G*.pth` + `s2D*.pth` (SoVITS) + `s1bert25hz-*-e15.ckpt` (GPT) + README.txt | Only if you ran §4 |
| `checkpoints_rvc/` (optional) | `G_*.pth` / `D_*.pth` checkpoints | Only if you ran the §6 backup cell |

Download the zip(s) and do a **listening test** (convert a holdout clip and a
fresh Edge TTS sample) before wiring anything into the bot. Wiring is a
separate task: Edge TTS `ar-EG-ShakirNeural` audio → RVC conversion with
`bahgat.pth` + `.index` (see `docs/voice-plan.md`, v3). The bot stays labelled
a parody bot.

## Chosen hyperparameters (short version)

- **RVC (primary):** v2, **40 kHz** (48 kHz needs ~24 GB VRAM and buys nothing
  audible for Telegram voice notes), F0 on with **RMVPE** on CUDA, **batch 4**,
  **150 epochs**, save every 10, `-sw 1`. Full rationale in `rvc_config.md`.
- **GPT-SoVITS (fallback):** **v2** (v4 needs 8 GB min / 16 GB recommended —
  marginal on a 15 GB T4), SoVITS **8 epochs** batch 4, GPT **15 epochs**
  batch 4. Full rationale in `gpt-sovits_config.md`.

## Known Colab free-tier limits (read this before starting)

Google publishes almost none of these exactly — the numbers below are the
documented/consistently reported ones as of Nov 2026, and Google says limits
"vary over time":

- **12 hours max per session** (free tier). After that the VM is deleted.
  Export to Drive well before that.
- **Idle disconnect after ~90 minutes** of no interaction (unpublished,
  varies). A running training cell counts as active, but don't rely on it —
  keep the tab open and don't walk away for hours.
- **GPU is not guaranteed.** At peak times you may get CPU-only or no GPU.
  Retry later / off-peak. Weekly GPU hours are rationed dynamically
  (~15–30 h reported, unpublished). If you get throttled, wait a day.
- **No background execution** on free tier (Pro+ only). Closing the browser
  stops the run.
- **VM disk (~35–78 GB) is ephemeral** — everything not copied to Drive is
  wiped when the session ends.
- **Drive is 15 GB free** (shared with Gmail/Photos). Export only finished
  weights, not full `logs/` folders (several GB).
- **Gradio WebUI is blocked** on free Colab — that is why this notebook uses
  the headless CLI for RVC instead of the GUI.

### How to resume after a disconnect

1. Start a new session, re-run §0–§2 (GPU check, clone+install, pretrained
   download, dataset unzip) — ~15 min.
2. Copy backed-up checkpoints from
   `Drive/bahgat_voice_models/checkpoints_rvc/` back into `logs/bahgat/`
   (run the §6 backup cell after every ~50 epochs so the checkpoints exist).
3. Re-run preprocess + F0 + HuBERT (~10 min — they live on the wiped VM disk).
4. Re-run training with the **latest checkpoint as the pretrained weights**
   and a reduced epoch count, e.g. stopped at epoch 80 → `-te 70
   -pg logs/bahgat/G_80.pth -pd logs/bahgat/D_80.pth`.
5. GPT-SoVITS resumes the same way from `logs/bahgat/ckpt/`.

## Troubleshooting (short version — full list in notebook §6)

- `CUDA out of memory` → batch 4 → 2 (`-bs 2`), keep `-c 0`.
- `ModuleNotFoundError: av` / fairseq errors → old notebook/checkout; this
  package uses current main, which needs neither.
- RVC WebUI won't open → expected on free Colab; use the CLI cells.
- GPT-SoVITS rejects language `ar` → set `LANG = "en"` in the `.list` cell
  and re-run §4 (Arabic is not officially supported by GPT-SoVITS).
- `hf download` 404 on a pretrained file → the filename changed upstream;
  check the repo README and adjust the include/allow lists.
- No GPU allocated → wait and retry off-peak; do not train on CPU.

## Notes / caveats

- The notebook was **not** run end-to-end here (no GPU in this environment,
  and Colab needs an interactive session). It was validated as JSON/nbformat
  only. A human must run it in Colab; the `--help` inspection cells in §4
  exist because GPT-SoVITS prep/train flags can drift between repo versions.
- Exact-match claim: none of the training was executed; epoch/time estimates
  are from the cited community sources, not measured runs.
- Prepared 2026-11-26 for the Bahgat bot project. Dataset contract:
  `training/clean/` (16 kHz mono WAV, 3–10 s) + `training/transcripts/`.
