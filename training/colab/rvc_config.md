# RVC training config — Bahgat voice model

Reviewable copy of the exact values the Colab notebook
(`bahgat_rvc_gpt-sovits_training.ipynb`, §1–§3, §5) uses. Nothing here is
executed; change a value here **and** in the matching notebook cell.

Research date: 2026-11-26. Sources: RVC-Project official repo + `docs/en/cli.md`,
independent RVC pilot write-ups, Colab free-tier limit surveys (Nov 2026).

## Repo

| Item | Value |
|---|---|
| Repo | https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI |
| Branch / pin | Release tag **`2.3.260718`** (21 Jul 2026). `git checkout 2.3.260718` + `git describe --tags` must print it. Drop the `git checkout` line to use latest `main` (then confirm `git log` is Jul 2026 or later). |
| Why this repo | Official, actively maintained (2026 release **2.3.260718**: resumable training, FCPE pitch, PyMSS replacing UVR5, CUDA Graph). Applio (the popular fork) is in maintenance mode; old Rejekts/ardha27 Colab notebooks are broken on current Colab (Python 3.12 / numpy 2.x / fairseq no longer installs). Current main needs no fairseq (ContentVec via Hugging Face transformers). There is no shipped RVC v3 base model. |
| Install | `pip install -r requirments_cu128_py312.txt` (upstream spelling, missing an `e`) + `huggingface_hub faiss-cpu soundfile`; `apt install ffmpeg unzip` |
| Interface | **Headless CLI only** — Colab blocks the RVC Gradio WebUI on the free tier. |

## Pretrained assets (downloaded per session from Hugging Face)

| File | Source |
|---|---|
| `assets/hubert_base/*` | `hf download lj1995/VoiceConversionWebUI --include "hubert_base/*" --local-dir assets` |
| `assets/rmvpe/rmvpe.pt` | `hf download lj1995/VoiceConversionWebUI rmvpe.pt --local-dir assets/rmvpe` |
| `assets/pretrained_v2/f0G40k.pth`, `f0D40k.pth` | `hf download lj1995/VoiceConversionWebUI --include "pretrained_v2/f0G40k.pth" "pretrained_v2/f0D40k.pth" --local-dir assets` |

Base model was pretrained on ~50 h of VCTK; we only fine-tune it.

## Dataset

| Item | Value |
|---|---|
| Input | `bahgat_dataset_curated.zip` in Google Drive root (`My Drive/bahgat_dataset_curated.zip`), unzipped to `/content/dataset` (old `bahgat_dataset.zip` accepted as fallback only) |
| Clips | **361 clips, 38.11 min total, 48 kHz mono WAV, 3–10 s each**, Bahgat speaking alone (`training/curated/clips/bahgat_*.wav`; 359 @ 48 kHz, 2 @ 44.1 kHz). **No transcripts in the zip** (not needed for RVC, needed for GPT-SoVITS §4) |
| Size target | **30–45 min curated** (audit: 10–30 min ideal, 40+ min 'can improve naturalness further, stay under 60 min'). Curated set is 38.11 min — inside the target. Full 66-min set kept as reserve, not trained on. |
| Holdout | 5 random clips copied to `/content/holdout/` and **excluded** from training — listening-test set. RVC has no train/val split. |
| Training dir | `/content/rvc_dataset/` (flattened copy of the clips) |

## Pipeline commands (run from `/content/rvc`)

```bash
# 1. Preprocess: resample to 40 kHz, slice, write logs/bahgat/filelist.txt
python train/preprocess.py /content/rvc_dataset 40000 4 logs/bahgat False 3.7

# 2. F0 extraction, RMVPE on CUDA (args: device nproc rank gpu exp_dir half)
python train/dataset/extract_f0.py cuda 1 0 0 logs/bahgat true

# 3. HuBERT (ContentVec) feature extraction
python train/dataset/extract_hubert_feature.py cuda:0 1 0 0 logs/bahgat v2 true

# 4. Train — the long step (~4–6 h on a free T4 for 38.11 min audio, 300 epochs;
#    estimate by linear scaling, unmeasured — watch the first 10 epochs)
python train/train.py -e bahgat -sr 40k -f0 1 -bs 4 -g 0 -te 300 -se 10 \
  -pg assets/pretrained_v2/f0G40k.pth -pd assets/pretrained_v2/f0D40k.pth \
  -l 0 -c 0 -sw 1 -v v2

# 5. Retrieval index (script path moves between versions; notebook locates it
#    dynamically, then runs: python <index-script> logs/bahgat v2)
```

## Hyperparameters

| Setting | Value | Justification |
|---|---|---|
| Version | v2 | Current standard; v1 legacy, v3 weights never shipped |
| Sample rate | **40 kHz** | Default for nearly all community v2 checkpoints. 48 kHz needs ~24 GB VRAM (not a T4) and buys nothing audible for Telegram voice notes (Opus-compressed). Source clips are 48 kHz, so 40 k keeps the audible band. 32 kHz is the fallback if VRAM is tight. |
| F0 | on, **RMVPE (CUDA)** | Pitch guidance is what makes speech (not just singing) sound like the person. RMVPE is best quality and GPU-accelerated; harvest/pm are CPU-only and worse. |
| Batch size | **4** | WebUI default rule is VRAM_GB/2 (≈ 7 on a T4), but 4 is safer on a shared Colab T4 and slightly more accurate. Drop to 2 only on CUDA OOM. |
| Epochs | **300** | Community guidance 200–500, sweet spot 200–400; the best checkpoint is rarely the last one. **Listen at 150 / 200 / 250 / 300 and keep the best by ear.** Stop early only if loss has flattened and later checkpoints sound worse. Over-training sounds robotic/metallic, especially on vowels. |
| Save every | 10 epochs | Lets you pick the best checkpoint by ear, not just the last one — and makes the run resumable. A background cell copies each new checkpoint to Drive every 10 min (continuous backup). |
| `-sw 1` | on | Also saves small inference-ready `.pth` to `assets/weights/bahgat.pth`. |
| `-l 0`, `-c 0` | off | Keep all checkpoints (needed for resume); don't cache dataset in GPU memory. |
| Speaker | `bahgat`, id 0 | Single-speaker model. |

## GPU / time (free Colab T4, 15 GB usable VRAM)

- Training fits from 6 GB VRAM; T4 is comfortable at batch 4.
- Expected wall time, 38.11 min audio, 300 epochs: setup ~10–15 min, preprocess ~2–5 min,
  RMVPE ~5–10 min, HuBERT ~2–5 min, training ~4–6 h, index ~2–5 min.
  **Total ≈ 4.5–6.5 h**, inside one 12 h session. Time scales with (epochs × audio);
  the estimate is unmeasured — watch the first 10 epochs and extrapolate.

## Outputs

| Artifact | Location after training | Notes |
|---|---|---|
| `bahgat.pth` | `assets/weights/bahgat.pth` (~70–80 MB) | Small inference weights (`-sw 1`) — **the file the bot needs** |
| `added_*.index` | `logs/bahgat/added_*.index` | FAISS retrieval index — improves similarity; model works without it (`index_rate=0`) |
| `G_*.pth` / `D_*.pth` | `logs/bahgat/` | Full checkpoints every 10 epochs; for resume / picking best epoch, not for shipping |
| Export zip | Drive: `My Drive/bahgat_voice_models/bahgat_rvc_v2_40k_YYYYMMDD.zip` | Contains only `bahgat.pth` + `*.index` + a README.txt. Note: `bahgat.pth` (`-sw 1`) is the FINAL (300th) epoch — to ship an earlier best epoch, extract its small `.pth` from the matching `G_<epoch>.pth` first (see notebook §7). |
| `checkpoints_rvc/` | Drive: `My Drive/bahgat_voice_models/checkpoints_rvc/` | Latest 2 `G_*.pth` / `D_*.pth` pairs + `bahgat_latest_small.pth`, copied continuously every 10 min during training |

## Resume after disconnect

Re-run setup (§0–§2), copy backed-up `G_*.pth`/`D_*.pth` from
`Drive/bahgat_voice_models/checkpoints_rvc/` into `logs/bahgat/` (the §3
continuous-backup cell copies them every 10 min while training runs), re-run
preprocess + F0 + HuBERT (~10 min), then train with the latest checkpoint as
the pretrained weights and the REMAINING epoch count, e.g. stopped at epoch 80 of 300:

```bash
python train/train.py -e bahgat -sr 40k -f0 1 -bs 4 -g 0 -te 220 -se 10 \
  -pg logs/bahgat/G_80.pth -pd logs/bahgat/D_80.pth -l 0 -c 0 -sw 1 -v v2
```

## Wiring into the bot (not done by the notebook)

Bot generates speech with a DONOR voice, then converts that audio through RVC
with `bahgat.pth` + `.index` (f0 RMVPE, index_rate ≈ 0.75). Do NOT use calm
Edge TTS `ar-EG-ShakirNeural` as the primary donor — RVC keeps the donor's
prosody. Prefer a fast/loud Egyptian donor: the VoiceTut grid winner, a human
Egyptian speaker, or IndexTTS 2.5 with a shouting emotion reference.
See `docs/voice-plan.md` (v3).
