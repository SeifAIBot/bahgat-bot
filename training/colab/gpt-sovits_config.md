# GPT-SoVITS training config — Bahgat voice model (FALLBACK)

Reviewable copy of the exact values the Colab notebook
(`bahgat_rvc_gpt-sovits_training.ipynb`, §4–§5) uses for the GPT-SoVITS
fallback. Nothing here is executed; change a value here **and** in the
matching notebook cell.

**Status: fallback only.** RVC is the primary route. Train GPT-SoVITS only if
RVC fails or sounds wrong — see the Arabic caveat below.

Research date: 2026-11-26. Sources: RVC-Boss/GPT-SoVITS repo + README,
independent GPT-SoVITS v2/v4 guides, Colab free-tier limit surveys (Nov 2026).

## Repo

| Item | Value |
|---|---|
| Repo | https://github.com/RVC-Boss/GPT-SoVITS |
| Branch | `main` (no pin — repo moves fast; v2 files are stable) |
| Official Colab notebook | `Colab-WebUI.ipynb` in the repo root — if the CLI cells below fight you, use that notebook instead; it tunnels the Gradio WebUI. |
| Install | `pip install -r requirements.txt` then `pip install -r extra-req.txt --no-deps` |
| Python | 3.10–3.12 supported (repo badge) — Colab's 3.12 is fine. |

## Version choice: v2Pro, not v2 or v4

| Version | Fine-tune VRAM | Output | Verdict for free Colab |
|---|---|---|---|
| **v2Pro (chosen)** | ~8–10 GB | 32 kHz | Fits a free T4 (15 GB usable) with headroom; best for low-quality recordings |
| v2 | 6 GB min / 8 GB recommended | 32 kHz | Older, most-documented path — superseded by v2Pro for this project |
| v3 | 8 GB min | 48 kHz | Heavier; metallic artifacts reported, superseded by v4 |
| v4 | 8 GB min / **16 GB recommended** | 48 kHz, LoRA rank 32 | Marginal on a 15 GB T4 — not recommended on free tier |
| v5 | newer, less documented for fine-tuning | — | Skip for now (Oct 2026, in code only, **no tagged release**, untested for fine-tuning, no Arabic) |

## ⚠️ Arabic caveat (the reason this is the fallback)

GPT-SoVITS's officially supported languages are **English, Japanese, Korean,
Chinese and Cantonese. Arabic is not on that list**, so its text frontend may
not handle Arabic text correctly. Consequences:

- The `.list` builder tags clips `ar` first. If the pipeline rejects `ar`,
  change `LANG = "ar"` to `LANG = "en"` in the notebook and re-run §4 — the
  acoustic model still learns Bahgat's voice; only the text handling changes.
- **Test zero-shot inference with an Arabic sentence before committing to a
  full fine-tune.** If Arabic TTS is broken, GPT-SoVITS cannot replace
  Edge TTS for this bot, and RVC (language-agnostic: audio → audio) is the
  only viable route.
- RVC needs no transcripts at all; GPT-SoVITS cannot train without them.

## Pretrained assets (downloaded per session from Hugging Face)

Repo `lj1995/GPT-SoVITS`, files under `GPT_SoVITS/pretrained_models/`:

| File | Role |
|---|---|
| `s1bert25hz-5kh-longer-epoch=12e-step=369668.ckpt` | GPT (text→semantic) base, v2 |
| `s2Gv2Pro.14000.pth` | SoVITS generator base, v2 |
| `s2Dv2Pro.14000.pth` | SoVITS discriminator base, v2 |
| `chinese-hubert-base/*` | HuBERT features |
| `chinese-roberta-wwm-ext-large/*` | BERT text features |

If a filename 404s, check the repo README "pretrained models" section for the
current names and adjust the `allow_patterns` in the notebook's download cell.
The notebook prints the downloaded layout so you can verify before training.

## Dataset

Same dataset as RVC (`bahgat_dataset_curated.zip` — 361 clips, 38.11 min, 48 kHz), but **transcripts are mandatory** — and the curated zip contains **no per-clip transcripts**. Supply per-clip `.txt` files (same basename as each WAV) or a combined `{basename: text}` JSON before running §4, or skip §4.
`.list` format, one line per clip:

```
<wav_path>|bahgat|<LANG>|<transcript text>
```

- Per-clip `.txt` files (same basename as the WAV) preferred.
- Fallback: one combined JSON `{basename: text}` anywhere in the dataset.
- A `.srt` alone cannot be mapped to clips — convert it first.
- Language tag: `ar` first, `en` if `ar` is rejected (see caveat).
- The 5 holdout clips set aside for RVC are also excluded here
  (the `.list` is built from `/content/rvc_dataset/`, not the raw zip).

## Pipeline commands (run from `/content/gpt-sovits`)

```bash
# 1. Dataset prep (documented 3-step pipeline; run --help first — the
#    notebook prints each script's flags before running them)
python GPT_SoVITS/prepare_datasets/1-get-text.py --exp_name bahgat
python GPT_SoVITS/prepare_datasets/2-get-hubert-wav32k.py --exp_name bahgat
python GPT_SoVITS/prepare_datasets/3-get-semantic.py --exp_name bahgat

# 2. Training configs: the notebook copies GPT_SoVITS/configs/s2.json and
#    GPT_SoVITS/configs/s1longer.yaml, fills in the Bahgat values below,
#    and writes TEMP/tmp_s2.json / TEMP/tmp_s1.yaml (same thing the WebUI
#    "1B fine-tune" tab does). If a key name differs in the checked-out
#    version, print the config and adjust the key names.

# 3. Train SoVITS first (slow), then GPT (fast) — independent, either order works
python GPT_SoVITS/s2_train.py --config TEMP/tmp_s2.json
python GPT_SoVITS/s1_train.py --config_file TEMP/tmp_s1.yaml
```

## Hyperparameters

| Model | Setting | Value | Justification |
|---|---|---|---|
| SoVITS (s2) | Epochs | **8** | WebUI default for fine-tuning; more epochs on 10–30 min risks overfitting the acoustic model |
| SoVITS (s2) | Batch size | **4** | Safe on a 15 GB T4 (WebUI default is 4 for s2); raise only if VRAM headroom is confirmed |
| SoVITS (s2) | Save every | 2 epochs | Checkpoints at 2/4/6/8 for picking the best by ear |
| SoVITS (s2) | `training_files` / `validation_files` | `TEMP/bahgat.list` (both) | Same-list validation, as the WebUI does |
| SoVITS (s2) | Pretrained | `s2Gv2Pro.14000.pth` / `s2Dv2Pro.14000.pth` | v2Pro base weights |
| GPT (s1) | Epochs | **15** | WebUI default for fine-tuning |
| GPT (s1) | Batch size | **4** | Safe on a 15 GB T4 |
| GPT (s1) | Pretrained | `s1bert25hz-5kh-longer-epoch=12e-step=369668.ckpt` | v2Pro base weights |
| Both | Exp name / speaker | `bahgat` | Single-speaker fine-tune |

No manual train/val split is needed: GPT-SoVITS uses the `.list` for training
(and the same list for validation, per the WebUI).

## GPU / time (free Colab T4, 15 GB usable VRAM)

- v2Pro fine-tuning: ~8–10 GB → fits the T4.
- Expected wall time, ~15 min audio: setup ~10 min, prep ~5–10 min,
  SoVITS 8 epochs ~30–45 min, GPT 15 epochs ~10–20 min.
  **Total ≈ 1–1.5 h**, inside one 12 h session.

## Outputs

| Artifact | Location after training | Notes |
|---|---|---|
| SoVITS generator | `logs/bahgat/ckpt/s2G*.pth` | **Ship this** |
| SoVITS discriminator | `logs/bahgat/ckpt/s2D*.pth` | Training-only; include in the zip for completeness/resume |
| GPT checkpoint | `logs/bahgat/ckpt/s1bert25hz-*-e15.ckpt` | **Ship this** |
| Export zip | Drive: `My Drive/bahgat_voice_models/bahgat_gpt-sovits_v2pro_YYYYMMDD.zip` | Contains the `ckpt/` files above + a README.txt |

## Resume after disconnect

Checkpoints live in `logs/bahgat/ckpt/`. Back them up to Drive, then in a new
session re-run setup + prep, point `TEMP/tmp_s2.json` / `TEMP/tmp_s1.yaml` at
the latest checkpoint files, and re-run the train commands.

## Wiring into the bot (not done by the notebook)

If GPT-SoVITS is used instead of RVC, it **replaces** the Edge TTS step
entirely: text → GPT-SoVITS TTS in Bahgat's voice (GPT ckpt + SoVITS weights
loaded by the GPT-SoVITS inference runtime). This is a separate integration
task. See `docs/voice-plan.md` (v3).
