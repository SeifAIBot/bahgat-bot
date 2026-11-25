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
| Branch / pin | `main`, pinned to commit `81eed5e8f68b6bed1789f682fe78cdd324495afc` (the commit the official CLI docs were verified against). Drop the `git checkout` line to use latest `main`. |
| Why this repo | Official, actively maintained (2026 release 2.3.x, Python 3.12, torch 2.7.1+cu128). Applio (the popular fork) is in maintenance mode; old Rejekts/ardha27 Colab notebooks are broken on current Colab (Python 3.12 / numpy 2.x / fairseq no longer installs). Current main needs no fairseq (ContentVec via Hugging Face transformers). |
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
| Input | `bahgat_dataset.zip` in Google Drive root (`My Drive/bahgat_dataset.zip`), unzipped to `/content/dataset` |
| Clips | 16 kHz mono WAV, 3–10 s each, Bahgat speaking alone (`clean/bahgat_*.wav`); per-clip transcripts in `transcripts/` (not needed for RVC, needed for GPT-SoVITS) |
| Size target | 10–30 min total clean audio (10+ min minimum) |
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

# 4. Train — the long step (~45–75 min on a free T4 for ~15 min audio)
python train/train.py -e bahgat -sr 40k -f0 1 -bs 4 -g 0 -te 150 -se 10 \
  -pg assets/pretrained_v2/f0G40k.pth -pd assets/pretrained_v2/f0D40k.pth \
  -l 0 -c 0 -sw 1 -v v2

# 5. Retrieval index (script path moves between versions; notebook locates it
#    dynamically, then runs: python <index-script> logs/bahgat v2)
```

## Hyperparameters

| Setting | Value | Justification |
|---|---|---|
| Version | v2 | Current standard; v1 legacy, v3 weights never shipped |
| Sample rate | **40 kHz** | Default for nearly all community v2 checkpoints. 48 kHz needs ~24 GB VRAM (not a T4) and buys nothing audible for Telegram voice notes (Opus); source clips are 16 kHz, so 48 k adds no information. 32 kHz is the fallback if VRAM is tight. |
| F0 | on, **RMVPE (CUDA)** | Pitch guidance is what makes speech (not just singing) sound like the person. RMVPE is best quality and GPU-accelerated; harvest/pm are CPU-only and worse. |
| Batch size | **4** | WebUI default rule is VRAM_GB/2 (≈ 7 on a T4), but 4 is safer on a shared Colab T4 and slightly more accurate. Drop to 2 only on CUDA OOM. |
| Epochs | **150** | Community guidance 100–300; more data = fewer epochs. 100 risks underfitting an expressive/shouty voice; 300+ on ~15 min risks memorisation. |
| Save every | 10 epochs | Lets you pick the best checkpoint by ear, not just the last one. |
| `-sw 1` | on | Also saves small inference-ready `.pth` to `assets/weights/bahgat.pth`. |
| `-l 0`, `-c 0` | off | Keep all checkpoints (needed for resume); don't cache dataset in GPU memory. |
| Speaker | `bahgat`, id 0 | Single-speaker model. |

## GPU / time (free Colab T4, 15 GB usable VRAM)

- Training fits from 6 GB VRAM; T4 is comfortable at batch 4.
- Expected wall time, ~15 min audio: setup ~10–15 min, preprocess ~2–5 min,
  RMVPE ~3–5 min, HuBERT ~2–4 min, training ~45–75 min, index ~2–5 min.
  **Total ≈ 1.5–2 h**, inside one 12 h session.

## Outputs

| Artifact | Location after training | Notes |
|---|---|---|
| `bahgat.pth` | `assets/weights/bahgat.pth` (~70–80 MB) | Small inference weights (`-sw 1`) — **the file the bot needs** |
| `added_*.index` | `logs/bahgat/added_*.index` | FAISS retrieval index — improves similarity; model works without it (`index_rate=0`) |
| `G_*.pth` / `D_*.pth` | `logs/bahgat/` | Full checkpoints every 10 epochs; for resume / picking best epoch, not for shipping |
| Export zip | Drive: `My Drive/bahgat_voice_models/bahgat_rvc_v2_40k_YYYYMMDD.zip` | Contains only `bahgat.pth` + `*.index` + a README.txt |

## Resume after disconnect

Re-run setup (§0–§2), copy backed-up `G_*.pth`/`D_*.pth` from
`Drive/bahgat_voice_models/checkpoints_rvc/` into `logs/bahgat/`, re-run
preprocess + F0 + HuBERT (~10 min), then train with the latest checkpoint as
the pretrained weights and a reduced epoch count, e.g. stopped at epoch 80:

```bash
python train/train.py -e bahgat -sr 40k -f0 1 -bs 4 -g 0 -te 70 -se 10 \
  -pg logs/bahgat/G_80.pth -pd logs/bahgat/D_80.pth -l 0 -c 0 -sw 1 -v v2
```

## Wiring into the bot (not done by the notebook)

Bot keeps Edge TTS `ar-EG-ShakirNeural` for speech generation, then converts
that audio through RVC with `bahgat.pth` + `.index` (f0 RMVPE,
index_rate ≈ 0.75). See `docs/voice-plan.md` (v3).
