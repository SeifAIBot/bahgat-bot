# Lightning AI Studios runbook — Bahgat RVC voice training

- **Prepared:** 2026-11-26
- **Status:** runbook only. No account was created, nothing was run, no GPU was used.
- **Job:** RVC WebUI 2.3, tag `2.3.260718`, v2 40 kHz, RMVPE pitch extraction, batch 4, 300 epochs, save every 10, experiment **`bahgat_40k_v2`**.
- **Dataset:** `bahgat_dataset_curated.zip` — 219 MB, 361 wav clips, 38.11 min, 48 kHz mono (2 clips at 44.1 kHz). Lives in Seif's Google Drive root.
- **Sources:** `training/colab/bahgat_rvc_gpt-sovits_training.ipynb` (34 cells: 25 code + 9 markdown — every command below is adapted from it, paths only changed) and `~/workspace/research_notes/free-gpu-rvc-training-alternatives-20261126-2010/report.md` §3.
- **Why Lightning:** Colab kills this workload (its FAQ bans "creating deepfakes" on managed runtimes — 4× setup kills). Kaggle committed runs die ~60 s in with "Canceled by backend, exit 137" (4 identical failures). Lightning AI Studios is the only no-card route found that can run the whole job.

## 0. Job card

| | |
|---|---|
| GPU | 1× Tesla T4, 16 GB — **$0.55/hr**, paid from 5 free credits (1 credit = $1) |
| GPU budget | 5 credits = **~9.1 h of T4**. Job is 5–7 h → **$2.75–$3.85**, leaving ~2–4 h spare |
| Session | T4 session length: **unlimited** on the free plan (A100/H100/H200 are 4 h-capped; T4 is not) |
| Storage | **50 GB persistent disk** (job needs ~20 GB). Files, packages and data survive restarts |
| Billing | Per second, **including setup time on the GPU and idle time** — so do all prep on the free CPU Studio first, and stop the Studio when done |
| Free CPU Studio | Costs 0 credits, but **restarts every 4 h** and **Studios always wake up on CPU** — after any restart, switch back to T4 |
| Idle | A GPU Studio sleeps after ~10 idle minutes (stops billing) — useful, but don't rely on it; stop the Studio explicitly at the end |

## 1. Account — Seif only, do not create anything on Muse's behalf

1. Go to **https://lightning.ai** and sign up with your email.
2. Verify with a **real (non-virtual) phone number** — Lightning requires it for anti-abuse. No card is needed.
3. You should see **5 free credits** on registration (25 more only if you add a card — **do not**). Credits expire after 12 months.
4. **Check the dashboard shows 5 credits before starting.** One secondary source notes verification "can take days for a personal email" — start this step early, not the same evening as the run.
5. ⚠️ **Not verified:** whether Lightning accepts an Egyptian mobile number for verification. No Egypt-specific blocklist was found, but no source explicitly confirmed Egypt eligibility either (see §12).

## 2. Create the Studio (free CPU, 0 credits)

1. Create a Studio from the default template, machine **CPU** (free). Name it e.g. `bahgat-rvc`.
2. Open the **Terminal** (VS Code / Jupyter are also available, but all steps below use the terminal).
3. First commands — record the answers:
   ```bash
   pwd; whoami; python3 --version; df -h; free -h
   ```
4. **Working-directory path — read this:** the Studio terminal opens in the Studio's home directory. The historical Lightning convention for its absolute path is `/teamspace/studios/this_studio`, but that was **not verified live** from Lightning docs on 2026-11-26 (current docs only say the `studios/<name>/` Drive folder is "relative to its home directory"). **Confirm with `pwd` on first login.** Every command in this runbook uses `$HOME`-based paths, so it works whatever the absolute path is. The variables below assume you run them from the home directory:
   ```bash
   RVC_DIR=$HOME/rvc
   ```
5. **Python version check (do this before installing anything):** the notebook's requirements file is `requirments_cu128_py312.txt` — i.e. it expects **Python 3.12**. If `python3 --version` is not 3.12, create a 3.12 env first:
   ```bash
   # only if `python3 --version` is NOT 3.12:
   which conda || { curl -sL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o /tmp/miniconda.sh && bash /tmp/miniconda.sh -b -p $HOME/miniconda && $HOME/miniconda/bin/conda init bash; }
   conda create -y -n rvc python=3.12
   conda activate rvc
   ```
   All later commands assume the Python that `python3 --version` reports as 3.12 (system or the `rvc` conda env).

## 3. Setup on the free CPU Studio (0 credits)

Do **everything** in this section on CPU. Nothing here needs a GPU, and GPU time bills from the moment the T4 is ready.

### 3.1 System packages (notebook cell 4)

```bash
sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg unzip
# If you are already root (`whoami` prints `root`), drop the `sudo`.
which ffmpeg unzip
```

### 3.2 Clone RVC, pinned to release tag 2.3.260718 (notebook cell 4)

```bash
git clone https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git $RVC_DIR
cd $RVC_DIR
git checkout 2.3.260718
git describe --tags        # must print 2.3.260718
git log --oneline -1       # must be dated Jul 2026 or later
python3 --version
```

If `git checkout 2.3.260718` fails (tag missing), delete that line and use main — then confirm `git log` is dated Jul 2026 or later.

### 3.3 Dependencies (notebook cell 5)

```bash
cd $RVC_DIR
pip install -q huggingface_hub faiss-cpu soundfile
ls requirments*.txt requirements*.txt 2>/dev/null
pip install -q -r requirments_cu128_py312.txt || pip install -q -r requirements.txt
```

Notes:

- The filename really is spelled `requirments_cu128_py312.txt` (missing an "e") upstream — that is not a typo in this runbook.
- `pip install` here only downloads/installs; torch will report `cuda: False` on the CPU Studio. **That is expected** — re-check after switching to T4 (§5).

### 3.4 Pretrained assets (notebook cell 6)

```bash
cd $RVC_DIR
hf download lj1995/VoiceConversionWebUI --revision main --include "hubert_base/*" --local-dir assets
hf download lj1995/VoiceConversionWebUI rmvpe.pt --revision main --local-dir assets/rmvpe
hf download lj1995/VoiceConversionWebUI --revision main --include "pretrained_v2/f0G40k.pth" "pretrained_v2/f0D40k.pth" --local-dir assets
ls -lh assets/hubert_base/ assets/rmvpe/ assets/pretrained_v2/
```

What these are: `hubert_base/*.pt` = ContentVec features (16 kHz); `rmvpe.pt` = pitch model; `pretrained_v2/f0G40k.pth` + `f0D40k.pth` = v2 40k base generator/discriminator (pretrained on ~50 h of VCTK — we only fine-tune them).

**Verify before going further — stop if any check fails, re-run the downloads, do not start training:**

```bash
cd $RVC_DIR
python3 - <<'EOF'
import os
for path, what in [('assets/pretrained_v2/f0G40k.pth', 'v2 40k generator base'),
                   ('assets/pretrained_v2/f0D40k.pth', 'v2 40k discriminator base'),
                   ('assets/rmvpe/rmvpe.pt', 'RMVPE pitch model')]:
    assert os.path.exists(path), f'MISSING {path} ({what}) — re-run the download cell.'
    size = os.path.getsize(path)
    assert size > 0, f'ZERO-BYTE {path} ({what}) — re-download it.'
    print(f'OK  {size/1e6:6.1f} MB  {path} ({what})')
_hubert = [f for f in os.listdir('assets/hubert_base') if f.endswith('.pt')] if os.path.isdir('assets/hubert_base') else []
assert _hubert, 'assets/hubert_base/ has no .pt file (ContentVec) — re-run the download cell.'
print(f"OK  hubert_base: {_hubert} (ContentVec features)")
print('All pretrained assets present and non-zero — safe to train.')
EOF
```

Keep the default `f0G40k`/`f0D40k` — do not chase singing pretrains (KLM v7s, Ov2Super, RIN_E3) on the first run: they are singing-trained and unproven for fast Egyptian shouting speech.

## 4. Dataset into the Studio

The zip (`bahgat_dataset_curated.zip`, 219 MB) lives in **Seif's Google Drive root** (`MyDrive/bahgat_dataset_curated.zip`). It is not on the Studio yet. Pick one route:

### Option A — file-browser upload (recommended)

1. Download the zip from Google Drive to your own computer.
2. In the Studio, use the file browser's **Upload** (drag-and-drop) to upload it to the Studio home directory: `$HOME/bahgat_dataset_curated.zip`.
3. Unzip:
   ```bash
   mkdir -p $HOME/dataset && unzip -o -q $HOME/bahgat_dataset_curated.zip -d $HOME/dataset
   find $HOME/dataset -type f -name '*.wav' | wc -l   # expect 361
   ```

### Option B — direct Drive download with gdown (needs link sharing)

1. In Google Drive, share `bahgat_dataset_curated.zip` as **"Anyone with the link"** and copy the link — the file ID is the part between `/d/` and `/view`.
2. In the Studio terminal:
   ```bash
   pip install -q gdown
   cd $HOME && gdown --id <FILE_ID_FROM_THE_LINK> -O bahgat_dataset_curated.zip
   mkdir -p $HOME/dataset && unzip -o -q $HOME/bahgat_dataset_curated.zip -d $HOME/dataset
   find $HOME/dataset -type f -name '*.wav' | wc -l   # expect 361
   ```
3. Turn link sharing back off afterwards if you prefer.

### Option C — Lightning CLI from your own computer

Download the zip from Drive to your computer, then (with the Lightning CLI installed and logged in locally):
```bash
lightning cp ./bahgat_dataset_curated.zip lit:///studios/bahgat-rvc/bahgat_dataset_curated.zip
```
then unzip on the Studio as in Option A step 3.

### 4.1 Audit the dataset (notebook cell 9, paths adapted)

Contract: 48 kHz mono WAV (44.1 kHz accepted — 2 clips), 3–10 s per clip, Bahgat speaking alone. RVC's preprocess resamples to 40 kHz itself.

```bash
python3 - <<'EOF'
import glob, os
import soundfile as sf
wavs = sorted(glob.glob(os.path.expanduser("~/dataset/**/*.wav"), recursive=True))
assert wavs, "no .wav files found in the zip — check the zip layout."
total, bad = 0.0, []
for w in wavs:
    info = sf.info(w)
    total += info.duration
    if info.samplerate not in (44100, 48000) or info.channels != 1 or not (3 <= info.duration <= 10):
        bad.append((os.path.basename(w), info.samplerate, info.channels, round(info.duration, 1)))
print(f"clips: {len(wavs)} | total clean audio: {total/60:.1f} minutes")
print(f"target: 30-45 min curated. {'OK' if total >= 1800 else 'BELOW 30 MIN — expected 38.11 min from the curated zip; check the upload.'}")
print("clips outside contract (not 44.1/48 kHz mono 3-10s):", len(bad))
for b in bad[:20]:
    print("   ", b)
EOF
```

Expect: **361 clips, ~38.1 minutes**.

### 4.2 Build the training set + hold out 5 clips (notebook cell 10, paths adapted)

RVC has no train/val split: it trains on everything you give it and you judge quality by ear. So 5 clips are held out by hand (never fed to training) for later A/B listening tests.

```bash
python3 - <<'EOF'
import glob, os, random, shutil
random.seed(7)
wavs = sorted(glob.glob(os.path.expanduser("~/dataset/**/*.wav"), recursive=True))
holdout = random.sample(wavs, min(5, len(wavs)))
os.makedirs(os.path.expanduser("~/rvc_dataset"), exist_ok=True)
os.makedirs(os.path.expanduser("~/holdout"), exist_ok=True)
for w in wavs:
    if w in holdout:
        shutil.copy(w, os.path.expanduser("~/holdout/"))
    else:
        shutil.copy(w, os.path.expanduser("~/rvc_dataset/"))
print(f"training clips: {len(os.listdir(os.path.expanduser('~/rvc_dataset')))} | holdout clips: {len(os.listdir(os.path.expanduser('~/holdout')))}")
print("holdout:", [os.path.basename(h) for h in holdout])
EOF
```

Expect: **356 training clips, 5 holdout clips**.

## 5. Switch to T4 and verify

**Only switch now** — setup is done, and GPU billing starts the moment the T4 is ready.

1. In the Studio UI, open the machine selector, pick **T4** (single GPU, 16 GB), click **Switch**, and wait until it is ready. (CLI alternative: `lightning studio switch --name bahgat-rvc --machine T4`.)
2. Verify — all three must pass before training:
   ```bash
   nvidia-smi          # expect: Tesla T4, 16 GB
   df -h               # expect: >= 20 GB free on the Studio disk
   python3 - <<'EOF'
   import torch
   print("torch:", torch.__version__, "| cuda available:", torch.cuda.is_available())
   print("gpu:", torch.cuda.get_device_name(0))
   print("vram (GB):", round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1))
   EOF
   ```
   Expect: `cuda available: True`, `gpu: Tesla T4`, VRAM ~15–16 GB.
3. If `nvidia-smi` shows no GPU, you are still on CPU — switch the machine to T4.
4. If T4 shows as unavailable or queued, wait and retry later. **Do not fall back to L4** ($0.79/hr → only ~6.3 h for the $5, almost no margin) unless T4 is unavailable for a long time.
5. Remember: **Studios wake up on CPU after any restart.** After a restart, re-switch to T4 before resuming anything GPU-side.

## 6. GPU prep: preprocess + RMVPE F0 + HuBERT (on T4)

These use GPU time — budget roughly 30–60 min inside the ~9 h. The preprocess step itself is CPU work and may already have been done on the CPU Studio; the F0 and HuBERT steps need CUDA.

### 6.1 Preprocess — resample to 40k, slice, write the filelist (notebook cell 12)

```bash
cd $RVC_DIR
python train/preprocess.py $HOME/rvc_dataset 40000 4 logs/bahgat_40k_v2 False 3.7
ls logs/bahgat_40k_v2/ && wc -l logs/bahgat_40k_v2/filelist.txt && head -3 logs/bahgat_40k_v2/filelist.txt
```

Expect `filelist.txt` to have ~356 lines (one per training clip).

### 6.2 F0 extraction with RMVPE on CUDA (notebook cell 13)

```bash
cd $RVC_DIR
python train/dataset/extract_f0.py cuda 1 0 0 logs/bahgat_40k_v2 true
```

RMVPE is the method. Do **not** try to switch to FCPE by guessing a CLI flag: in this tag (`2.3.260718`) the `extract_f0.py` CUDA path hard-codes `f0method="rmvpe"` — there is no `--f0method` flag in that script. (FCPE is more accurate on large pitch drops / vocal fry — exactly the shouting case — but it is not exposed in this checkout; if RMVPE pitch tracks wobble on the rant clips, note it for the listening test rather than re-extracting blind.)

### 6.3 HuBERT (ContentVec) feature extraction (notebook cell 14)

```bash
cd $RVC_DIR
python train/dataset/extract_hubert_feature.py cuda:0 1 0 0 logs/bahgat_40k_v2 v2 true
ls logs/bahgat_40k_v2/3-feature768/ | head -3; ls logs/bahgat_40k_v2/3-feature768/ | wc -l
```

Expect ~356 feature files in `3-feature768/`.

## 7. Training (on T4, headless)

**Start the checkpoint backup from §8 first** (or at least the local staging loop), then launch training — checkpoints only exist once training starts writing them.

### 7.1 Launch — notebook cell 15, experiment name adapted

The notebook's own command uses `-e bahgat`; this runbook uses **`-e bahgat_40k_v2`** per the job spec (see the discrepancy note in §12 — keep the name consistent everywhere, because it sets the `logs/` directory and the small-weights filename).

```bash
cd $RVC_DIR
nohup python train/train.py -e bahgat_40k_v2 -sr 40k -f0 1 -bs 4 -g 0 -te 300 -se 10 \
  -pg assets/pretrained_v2/f0G40k.pth -pd assets/pretrained_v2/f0D40k.pth \
  -l 0 -c 0 -sw 1 -v v2 > train.log 2>&1 &
echo "training PID: $!"
sleep 60 && tail -n 30 train.log
```

Flag meanings (notebook's own): `-e` experiment name, `-sr 40k` sample rate, `-f0 1` use F0, `-bs 4` batch size, `-g 0` GPU 0, `-te 300` total epochs, `-se 10` save every 10 epochs, `-pg`/`-pd` pretrained generator/discriminator, `-l 0`, `-c 0`, `-sw 1` save small inference weights, `-v v2`.

Notes:

- **Do not train through the Gradio WebUI** (`python infer-web.py` Train tab). The CLI path above is the resumable one the notebook uses; the WebUI is an extra failure surface.
- `nohup ... &` keeps training alive if the browser tab closes (Lightning also supports `tmux` — `tmux new -s train`, run the command, detach with `Ctrl-b d`, reattach with `tmux attach -t train`).
- The research report's §3 template used `-l 1`; the notebook uses `-l 0`. **The notebook wins** — use `-l 0`.

### 7.2 Monitor

```bash
tail -f train.log                    # loss lines; Ctrl-C stops the tail, not the training
nvidia-smi                           # expect GPU util high, ~10-14 GB used
ps aux | grep '[t]rain/train.py'     # process must be alive
ls -lt logs/bahgat_40k_v2/ | head    # G_<epoch>.pth / D_<epoch>.pth appear every 10 epochs
```

### 7.3 Credit budget — the number to watch

| Elapsed GPU time | Cost at $0.55/hr | Credits left of 5 |
|---|---|---|
| 5 h | $2.75 | $2.25 (~4.1 h) |
| 6 h | $3.30 | $1.70 (~3.1 h) |
| 7 h | $3.85 | $1.15 (~2.1 h) |
| 9.1 h | $5.00 | $0 — out |

Expected: training itself ~4–6 h + §6 extraction ~0.5–1 h = **5–7 h total**. Check the Lightning dashboard credit balance when the log passes epoch ~100: if the projected total is heading past ~9 h, stop and reassess rather than burning the last credit mid-run (see §10 for how a resumed run spends the remainder).

## 8. Checkpoints — get them out as they appear

### 8.1 Where they live

- `logs/bahgat_40k_v2/G_<epoch>.pth` + `D_<epoch>.pth` — written every 10 epochs.
- `assets/weights/bahgat_40k_v2.pth` — small inference weights (~70–80 MB), **rewritten at every save**. At each listening milestone (150 / 200 / 250 / 300) copy it aside under an epoch-named file immediately, or it will be overwritten by the next save:
  ```bash
  cp $RVC_DIR/assets/weights/bahgat_40k_v2.pth $HOME/checkpoints_out/bahgat_40k_v2_e150.pth
  ```

### 8.2 Download each checkpoint as it appears (primary)

Download `G_<epoch>.pth` (and its `D_` pair if you want resume ability) via the Studio **file browser** as soon as each appears. Do not wait until the end — the 5 credits are one-time, and a problem at hour 8 must not lose hour 7's checkpoint.

### 8.3 Second place: private Hugging Face repo (backup copy)

1. Create a **private** repo on https://huggingface.co (free, email-only account) — e.g. `bahgat-rvc-checkpoints`.
2. Create a token at https://huggingface.co/settings/tokens (read+write). **Never paste the token in chat** — put it only in the Studio terminal:
   ```bash
   export HF_TOKEN='paste-token-here-in-the-terminal-only'
   ```
3. Upload each new checkpoint:
   ```bash
   hf upload <your-hf-username>/bahgat-rvc-checkpoints logs/bahgat_40k_v2/G_150.pth
   ```

### 8.4 Continuous backup loop (adapted from notebook cell 16)

The notebook's version synced to Google Drive every 10 min; there is no Drive mount on Lightning, so this version stages locally and uploads to Hugging Face. Start it **before** the training cell (it does nothing until checkpoints appear):

```bash
mkdir -p $HOME/checkpoints_out
cat > $HOME/checkpoint_sync.sh <<'EOF'
#!/bin/bash
# checkpoint_sync.sh — stage new RVC checkpoints + upload to Hugging Face every 10 min, keep latest 2 pairs on disk
SRC=$HOME/rvc/logs/bahgat_40k_v2
DST=$HOME/checkpoints_out
REPO="<your-hf-username>/bahgat-rvc-checkpoints"   # <-- fill in your HF repo
while true; do
  cp -n $SRC/G_*.pth $SRC/D_*.pth $DST/ 2>/dev/null
  cp -f $HOME/rvc/assets/weights/bahgat_40k_v2.pth $DST/bahgat_latest_small.pth 2>/dev/null
  # upload any staged checkpoint not yet uploaded (hf upload is idempotent-ish; re-uploads are cheap vs losing a run)
  for f in $DST/G_*.pth $DST/D_*.pth; do
    [ -f "$f" ] && hf upload "$REPO" "$f" >/dev/null 2>&1
  done
  # prune the Studio disk: keep only the 2 newest G_*.pth (and their matching D_*.pth)
  ls -t $SRC/G_*.pth 2>/dev/null | tail -n +3 | while read f; do
    rm -f "$f" "${f/G_/D_}"
  done
  sleep 600
done
EOF
chmod +x $HOME/checkpoint_sync.sh
nohup bash $HOME/checkpoint_sync.sh > $HOME/checkpoint_sync.log 2>&1 &
echo "backup loop PID: $!"
```

Stop it with `pkill -f checkpoint_sync.sh`. Check it any time with `ls -lh $HOME/checkpoints_out/`.

**Retention rule (from the notebook):** save every 10 epochs; at 150 / 200 / 250 / 300 extract the small `.pth`; keep only the latest 2 G+D pairs on the Studio disk (each pair ~200–400 MB; 30 pairs unpruned would be ~9 GB of the 50 GB disk); **verify each second-place copy (size + timestamp) before deleting the local copy**. A checkpoint that lives only on the Studio disk dies if the Studio is deleted; a zero-byte remote copy is the same as lost.

### 8.5 Stop billing at the end

When training is done (or you are stopping for the day): download the final `.pth` + `.index` (§9), then **stop the Studio** — UI **Stop** button, or CLI `lightning studio stop --name bahgat-rvc`. The GPU Studio sleeps after ~10 idle minutes, but stop it explicitly; billing is per second while it runs.

## 9. Build the index, verify, export

### 9.1 Build the retrieval index (notebook cell 17)

The `.index` makes converted speech sound closer to Bahgat (retrieval over his real features). The model works without it (index rate 0), but ship it. The index script's path moved between repo versions, so locate it dynamically:

```bash
cd $RVC_DIR
python3 - <<'EOF'
import glob, subprocess, sys
cands = (glob.glob("infer/modules/train/extract/*index*.py")
         + glob.glob("train/*index*.py") + glob.glob("tools/*index*.py"))
print("index script candidates:", cands)
if cands:
    subprocess.run([sys.executable, cands[0], "logs/bahgat_40k_v2", "v2"], check=True)
else:
    print("NO index script found in this checkout — run: find . -name '*index*.py' -path '*train*'")
EOF
```

### 9.2 Verify outputs (notebook cell 18, adapted)

```bash
ls -lh assets/weights/bahgat_40k_v2.pth logs/bahgat_40k_v2/added_*.index logs/bahgat_40k_v2/*.index 2>/dev/null
```

Expect: `assets/weights/bahgat_40k_v2.pth` (~70–80 MB) + `logs/bahgat_40k_v2/added_*.index`.

### 9.3 Export (notebook cell 29, adapted)

```bash
cd $RVC_DIR
DATE=$(date +%Y%m%d)
mkdir -p $HOME/bahgat_voice_models
python3 - <<EOF
import glob, os, zipfile
DATE = "$DATE"
OUT = os.path.expanduser("~/bahgat_voice_models")
os.makedirs(OUT, exist_ok=True)
files = glob.glob("$RVC_DIR/assets/weights/bahgat_40k_v2.pth") \
      + glob.glob("$RVC_DIR/logs/bahgat_40k_v2/added*.index") \
      + glob.glob("$RVC_DIR/logs/bahgat_40k_v2/*.index")
assert files, "no RVC weights found — did training finish?"
zpath = f"{OUT}/bahgat_rvc_v2_40k_{DATE}.zip"
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("README.txt",
        "Bahgat RVC v2 40k\nModel: bahgat_40k_v2.pth (small inference weights, -sw 1)\n"
        "Index: added_*.index (FAISS retrieval index)\n"
        "Trained: RVC 2.3, 300 epochs, batch 4, RMVPE f0, v2 40k\n"
        "Data: 361 clips / 38.11 min curated 48 kHz mono audio\n"
        "Use: Edge TTS ar-EG-ShakirNeural audio -> RVC convert (see bot docs/voice-plan.md)\n")
    for f in files:
        z.write(f, os.path.basename(f))
        print(f"added {os.path.basename(f)} ({round(os.path.getsize(f)/1e6, 1)} MB)")
print("saved:", zpath, f"({round(os.path.getsize(zpath)/1e6, 1)} MB)")
EOF
```

Then download the zip via the file browser and upload it to Google Drive (`bahgat_voice_models/`) and/or the HF repo.

### 9.4 Listen before calling it done (notebook §7)

Listen at **150 / 200 / 250 / 300** and keep the best **by ear**. Score the **rant/shouting clips separately** at each checkpoint — rant is only ~14% of the set and will be the weakest style; the best overall epoch may not be the best rant epoch. Use the 5 held-out clips from `$HOME/holdout/` for the A/B test (they were never trained on).

## 10. Resume after an interruption

**Key difference vs Colab/Kaggle: the Studio disk persists.** Do not re-run setup, re-download assets, or re-copy checkpoints. Resume is:

1. If the Studio restarted: it wakes on **CPU** — switch back to **T4** (§5) and re-verify `nvidia-smi`.
2. Check what survived: `ls logs/bahgat_40k_v2/` for the last `G_<epoch>.pth` / `D_<epoch>.pth`, and that `logs/bahgat_40k_v2/filelist.txt` and `3-feature768/` still exist. Re-run §6.1–6.3 **only** if those feature dirs are missing (they won't be, unless the Studio was deleted).
3. **Back up the old logs dir first.** A resumed run counts epochs from 0 again and writes new `G_10.pth`, `G_20.pth`, … files that would **overwrite** same-numbered checkpoints from the first run:
   ```bash
   mv logs/bahgat_40k_v2 logs/bahgat_40k_v2_run1
   mkdir -p logs/bahgat_40k_v2
   cp logs/bahgat_40k_v2_run1/filelist.txt logs/bahgat_40k_v2/ 2>/dev/null
   cp -r logs/bahgat_40k_v2_run1/3-feature768 logs/bahgat_40k_v2/ 2>/dev/null
   cp -r logs/bahgat_40k_v2_run1/3-feature256 logs/bahgat_40k_v2/ 2>/dev/null
   ```
   (Copy the feature dirs back so §6 does not need re-running; if the copy is large, re-running §6.1–6.3 takes ~10–60 min instead.)
   Then restore the checkpoint pair you are resuming from into the fresh dir:
   ```bash
   cp logs/bahgat_40k_v2_run1/G_<LAST>.pth logs/bahgat_40k_v2/
   cp logs/bahgat_40k_v2_run1/D_<LAST>.pth logs/bahgat_40k_v2/
   ```
   (If the checkpoints are already on Hugging Face / downloaded locally, fetch them from there instead.)
4. Re-run training with the latest checkpoint as the pretrained weights and the **remaining** epochs (notebook §6 — e.g. stopped at epoch 80 of 300, so 220 left):
   ```bash
   cd $RVC_DIR
   nohup python train/train.py -e bahgat_40k_v2 -sr 40k -f0 1 -bs 4 -g 0 -te 220 -se 10 \
     -pg logs/bahgat_40k_v2/G_80.pth -pd logs/bahgat_40k_v2/D_80.pth \
     -l 0 -c 0 -sw 1 -v v2 > train_resumed.log 2>&1 &
   ```
5. Restart the backup loop (§8.4) so the resumed run is protected too.
6. **Credit check before resuming:** remaining credits ≈ 5 − spent. After a 4 h interruption you have ~$2.80 left ≈ 5 h of T4 — enough to finish most of a resumed run. If the remaining epochs won't fit in the remaining credits, listen to the last checkpoint you already have (§9.4) instead of starting a resume you can't finish.

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `CUDA out of memory` | Batch 4 → 2 (`-bs 2`), and make sure `-c 0` |
| `pip install` fails on `requirments_cu128_py312.txt` | Fallback: `pip install -q -r requirements.txt`; check `python3 --version` is 3.12 (§2 step 5) |
| `ModuleNotFoundError: av` / fairseq errors | You are on an old checkout — this job uses 2.3, which needs neither; re-check `git describe --tags` |
| `hf download` 404 on a pretrained file | The filename changed upstream; check the repo README and adjust the `--include` lists |
| `git checkout 2.3.260718` fails | Tag missing from this clone; use main, then confirm `git log` is dated Jul 2026 or later |
| `nvidia-smi` shows no GPU / `cuda: False` | You are still on the CPU machine — switch to T4 (§5) |
| Studio restarted mid-run | It wakes on CPU; re-switch to T4. Files persist — resume per §10, do not redo setup |
| Training process died, Studio alive | `tail -n 100 train.log`; resume per §10 from the last `G_`/`D_` pair |
| T4 unavailable / long queue | Wait and retry later; L4 ($0.79/hr, ~6.3 h for $5) only as a last resort |
| Gradio WebUI won't open | Expected — use the CLI commands in this runbook, never the WebUI training tab |
| GPT-SoVITS rejects language `ar` | Out of scope for this RVC run; the notebook §4 fallback sets `LANG = "en"` in the `.list` cell |
| GPT-SoVITS `.list` asserts "no transcripts found" | The curated zip has no per-clip transcripts — supply them first or skip §4 |

## 12. Open questions / things NOT verified

1. **Studio home absolute path** — `/teamspace/studios/this_studio` is the historical convention, **not verified live** (current Lightning docs only confirm the `studios/<name>/` Drive folder is relative to the Studio home). Confirm with `pwd` on first login. All commands here use `$HOME`, so they work either way.
2. **Egyptian mobile for phone verification** — not verified. Requirement is only "a real (non-virtual) phone number"; no Egypt blocklist was found, but no source explicitly confirmed Egypt eligibility.
3. **T4 availability / queue for free accounts** — the pricing page showed 6,144 T4 units on 26 Nov 2026, but free-tier GPU availability is not guaranteed; a queue or "unavailable" at switch time is possible.
4. **Studio default Python version** — not verified live. The runbook checks it (§2 step 5) and has a conda 3.12 fallback; if the base image already ships 3.12, skip the fallback.
5. **File-browser upload limit for the 219 MB zip** — not verified; Options B (gdown) and C (CLI `lightning cp`) are included as fallbacks.
6. **Experiment-name discrepancy** — the repo notebook file uses `-e bahgat` / `logs/bahgat`; this runbook uses `bahgat_40k_v2` / `logs/bahgat_40k_v2` per the job spec (and the research report). If you compare checkpoints against the Kaggle notebook, confirm its experiment name matches first.
7. **`-l` flag** — the notebook uses `-l 0`; the research report's §3 template used `-l 1`. The notebook wins (used here).
8. **Hugging Face upload of 200–400 MB checkpoint files** via `hf upload` — standard workflow, but not tested in this project. Verify the first upload's size on the repo page before relying on the loop.
9. **Credits are one-time, not recurring** — if the run fails after the credits are spent, there is no second free grant. That is why §8 (download checkpoints as they appear + second place) is not optional.
10. **Fastero note:** phone verification "can take days for a personal email" — if signup stalls, that is the first delay to expect, not a GPU problem.

## Sources

- Notebook (commands adapted from it): `training/colab/bahgat_rvc_gpt-sovits_training.ipynb`
- Research report: `~/workspace/research_notes/free-gpu-rvc-training-alternatives-20261126-2010/report.md` (§3 Lightning AI Studios)
- Lightning AI pricing (verified live 26 Nov 2026): https://lightning.ai/pricing
- Lightning AI Studios — switch CPU/GPU, environments persist: https://lightning.ai/docs/platform/build/ai-studio/add-gpus
- Lightning AI Studios — single-GPU training / switch from CPU to GPU: https://lightning.ai/docs/platform/train/finetune-models/single-gpu-training
- Lightning AI CLI — Studio create/start/switch/cp: https://lightning.ai/docs/platform/developers/cli/studio
- Lightning AI Teamspace Drive (`lit://` URLs, `studios/<name>/` = Studio home): https://lightning.ai/docs/platform/developers/cli/drive
- Lightning AI free tier (5 credits at signup, 25 more with a card, 4 h CPU restarts, T4 unlimited): https://fastero.com/blog/lightning-ai-studio
- RVC WebUI repo, release 2.3.260718: https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI
- RVC CLI training / WebUI launch: https://context7.com/websites/deepwiki_rvc-project_retrieval-based-voice-conversion-webui/llms.txt?tokens=10000
- RVC local training guide (Python 3.10/3.12, torch, `f0G40k.pth`/`f0D40k.pth`, RMVPE): https://www.hawxtech.net/train-a-local-rvc-voice-model-with-clean-audio-samples.html
