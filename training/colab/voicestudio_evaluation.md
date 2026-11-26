# VoiceStudio evaluation for the Bahgat bot

Prepared 2026-11-26. Everything below was verified by reading the VoiceStudio
repo (`debpalash/VoiceStudio`, commit `d906140`, 118,357 stars, AGPL-3.0) and the
upstream OmniVoice project (`k2-fsa/OmniVoice`, PyPI `omnivoice` 0.1.5) the same
day. Nothing in this file was run — there is no GPU in this environment and
Colab needs an interactive session. The comparison notebook this evaluation
goes with is `bahgat_zeroshot_omnivoice_vs_xtts.ipynb` in this folder.

## 1. What was verified in the repo

### (a) Engine list — OmniVoice is the default zero-shot engine

- `README.md`: "Start with **VoiceStudio** (default, powered by
  k2-fsa/OmniVoice)". `docs/engines/omnivoice.md`: "OmniVoice (k2-fsa/OmniVoice)
  is VoiceStudio's default TTS engine — the one a fresh install uses without
  any configuration. It does zero-shot voice cloning across 600+ languages and
  outputs 24 kHz mono audio."
- `docs/engines/README.md` lists **21 TTS engine rows** (the brief for this
  task said 17 — the count I verified in the table is 21): VoiceStudio
  (OmniVoice, default), VoxCPM2, MOSS-TTS-Nano, KittenTTS, MLX-Audio, CosyVoice
  3, GPT-SoVITS, Sherpa-ONNX, IndexTTS 2.5, OmniVoice GGUF, Supertonic-3,
  MOSS-TTS-v1.5, dots.tts, OmniVoice (subprocess), PocketTTS, Confucius4-TTS,
  Ming-3.0-tts, audio.cpp (Breeze-TTS-2), audio.cpp (dots.tts SOAR), CosyVoice 3
  GGUF, Qwen3-TTS Base (CUDA adapter). The feature catalog
  (`docs/feature-catalog.md`) lists the same set.
- **XTTS is NOT in the catalog.** There is no XTTS engine in VoiceStudio at
  all — the XTTS side of the comparison has to come from Coqui's own `TTS`
  package, which the notebook does.

### (b) How OmniVoice zero-shot cloning is invoked

Two layers — the VoiceStudio app, and the upstream model underneath it:

- **Inside VoiceStudio (the app):** GUI voice cloning (pick a voice or add a
  clean reference recording, type text, generate), or the local API on
  `http://127.0.0.1:3900`: `POST /generate` and the OpenAI-compatible
  `POST /v1/audio/speech`, with a reference clip (`ref_audio`), an optional
  reference transcript, and a `language` parameter (`Auto` for
  language-agnostic synthesis). `GET /engines` reports per-engine limits.
  Auth is `OMNIVOICE_API_KEY` as a bearer token; loopback clients need no
  credential. There is also a CLI (`cli/`) and an MCP server on the same port.
- **The model itself:** `docs/engines/omnivoice.md` — cloning takes a short
  reference clip, **3–10 s is the sweet spot**; a transcript of the clip
  improves conditioning and is auto-generated with an installed speech
  recognizer (Whisper) if not supplied. A clip with a supplied transcript is
  limited to 20 s; without one, VoiceStudio searches up to 75 s and picks the
  15 s passage with the most speech. Cross-language cloning: keep the reference
  transcript in the sample's original language, write the new script in the
  output language. `instruct` style attributes and a reference clip can be
  combined — upstream documents dialect cloning (dialect reference + matching
  dialect instruct) as the canonical case. **Recommended VRAM floor: ~6 GB.**
  CPU works (float32) but is slow; there is a quantized **OmniVoice GGUF**
  variant for low-VRAM/CPU machines.

### (c) Can OmniVoice run WITHOUT the Electron app? Yes — three ways

1. **Standalone pip package (the Colab route — chosen).** Upstream
   `k2-fsa/OmniVoice` is on PyPI as `omnivoice` 0.1.5:
   `pip install omnivoice`, then
   ```python
   from omnivoice import OmniVoice
   model = OmniVoice.from_pretrained("k2-fsa/OmniVoice",
                                     device_map="cuda:0", dtype=torch.float16)
   audio = model.generate(text="...", ref_audio="ref.wav",
                          ref_text="...")  # ref_text optional — Whisper auto-transcribes
   ```
   plus `omnivoice-infer` / `omnivoice-demo` CLI entry points. This is the
   same code VoiceStudio vendors as its bundled `omnivoice/` package
   (LICENSE-NOTICE.md: separately licensed Apache-2.0, not relicensed by
   VoiceStudio). The notebook uses this route. Upstream also links an official
   Colab notebook, so Colab is a supported way to run it.
2. **VoiceStudio Docker image** (headless, no Electron): official images
   `ghcr.io/debpalash/voicestudio:stable` and Docker Hub mirror
   `palashdeb/omnivoice-studio:stable` (same images/tags; old
   `ghcr.io/debpalash/omnivoice-studio` path is a compatible alias). Tags:
   `:stable` (release), `:latest`/`:main` (rolling main), `:stable-rocm` /
   `:rocm` (AMD GPU), `:stable-cuda-arm64` (ARM64 NVIDIA). CPU run:
   `docker run -d -p 127.0.0.1:3900:3900 -e OMNIVOICE_API_KEY=... -v
   omnivoice-data:/app/omnivoice_data ghcr.io/debpalash/voicestudio:stable`;
   GPU adds `--gpus all` + the NVIDIA Container Toolkit. First run downloads
   ~2.4 GB of weights. **Colab cannot run Docker, so this route is unusable
   for the comparison** — but it is the right route for a local GPU machine
   or a server later.
3. **VoiceStudio backend alone, from source:** the FastAPI backend lives in
   `backend/`; `bun run dev` installs JS + Python deps and launches Electron,
   `bun run setup:api` rebuilds just the Python environment. There is **no
   pip-installable VoiceStudio backend** — running it means cloning the whole
   repo and using bun/uv. Not practical on Colab, and pointless there when
   route (1) gives the same model with one `pip install`.

### (d) "GPT-SoVITS (external server)" — what it actually means

From `docs/engines/gpt-sovits.md`, verified verbatim: "Unlike VoiceStudio's
other engines, GPT-SoVITS does not run inside the app. It ships as a
standalone API server, and VoiceStudio connects to it over HTTP."

- **Not bundled.** You install and run the upstream project yourself
  (RVC-Boss GPT-SoVITS, 57k+ stars, MIT-licensed):
  `python api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml`.
  VoiceStudio is only an HTTP client speaking the `api_v2` protocol
  (`POST /tts`); the older v1 `api.py` server is **not compatible**.
- Fine-tuned voices: edit the `custom` section of `tts_infer.yaml` to point at
  your own `GPT_weights*` / `SoVITS_weights*` files before starting the server.
  Default URL `http://127.0.0.1:9880` (`OMNIVOICE_GPTSOVITS_URL`); non-loopback
  servers need `OMNIVOICE_TRUSTED_NETWORKS`. Output is 32 kHz mono.
- **Languages: five only — zh / en / ja / yue / ko. No Arabic.** "Five
  languages only; for broader coverage use OmniVoice." This independently
  confirms the training-package worker's finding that GPT-SoVITS does not
  officially support Arabic (the RVC notebook works around it with
  `LANG = "en"` in the `.list`).

### (e) Licence of the default OmniVoice weights — CC-BY-NC confirmed

- `README.md` (Pro section): "Neither licence covers model weights: the
  default OmniVoice weights are non-commercial (CC-BY-NC), so check each
  model's licence in the Model Manager before client work."
- `LICENSE-NOTICE.md`: "The default `k2-fsa/OmniVoice` model card identifies
  its code as Apache-2.0 and pretrained weights as CC-BY-NC. Its
  `audio_tokenizer/LICENSE` contains separate Boson Higgs Audio 2 and Meta
  Llama community terms. A commercial license for VoiceStudio-owned code does
  not replace any of those terms." The app itself is AGPL-3.0, which
  *includes* commercial use of the application under its terms — but that
  covers the code, not the weights. The bundled `omnivoice/` Python package is
  Apache-2.0.
- The upstream model card (PyPI/HF) repeats the same split: code Apache-2.0,
  pre-trained weights CC-BY-NC, plus a disclaimer that the project is "for
  academic research purposes" and forbids unauthorised voice cloning /
  impersonation / fraud. VoiceStudio's README carries the same responsible-use
  disclaimer ("Clone a voice only with its owner's permission").
- XTTS v2, for the record, is also non-commercial: Coqui Public Model License
  (CPML).

### (f) Arabic support — listed, but quality is unverified

From `docs/languages.md` (the OmniVoice language catalog — 646 languages,
581k hours total). Arabic entries found by searching the table:

| Language | VoiceStudio ID | Training data |
|---|---|---|
| Standard Arabic | `arb` | 1,483.53 h |
| Egyptian Arabic | `arz` | **23.23 h** |
| Gulf Arabic | `afb` | 98.55 h |
| Moroccan Arabic | `ary` | 104.67 h |
| Najdi Arabic | `ars` | 203.54 h |
| Levantine Arabic | `apc` | 15.65 h |
| Saidi Arabic | `aec` | 9.28 h |
| Eastern Egyptian Bedawi Arabic | `avl` | 1.86 h |
| Hijazi Arabic | `acw` | 22.32 h |

- RTL text (Arabic, Hebrew, Persian, Urdu) is handled in the editors
  (`dir="auto"`).
- Caveats, all from the docs: training hours are not a quality guarantee —
  Egyptian Arabic has **~64× less data than Standard Arabic** (23 h vs
  1,483 h) and ~9× less than Najdi. "Engine language coverage and accent
  quality still vary; use a multilingual engine that supports the target
  language." Voice *design* (attributes like gender/age/dialect) "is trained
  on English and Chinese and can be unstable in low-resource languages" — so
  dialect must come from the **reference clip + matching dialect instruct**,
  not from voice design. No Arabic-specific quality claim, benchmark, or demo
  exists anywhere in the repo/docs I read. **Egyptian-dialect quality is
  therefore genuinely unknown until the notebook's listening test is run.**
- XTTS v2 supports Arabic as generic `ar` only (17 languages total, incl.
  `ar`); it has no dialect code at all, so XTTS cannot even *ask* for Egyptian
  Arabic — a structural disadvantage in this comparison.

## 2. The chosen Colab route for the comparison

**Route: standalone upstream `pip install omnivoice` — no VoiceStudio app, no Docker.**

Step by step (implemented in `bahgat_zeroshot_omnivoice_vs_xtts.ipynb`):

1. Colab runtime → T4 GPU; verify with `nvidia-smi` (§0). A T4's ~15 GB
   clears OmniVoice's ~6 GB VRAM floor.
2. Get `training/clean/xtts_reference.wav` from Drive (or upload it) and verify
   16 kHz mono, 6–10 s (§1). Optional transcript from
   `training/transcripts/xtts_reference.txt`.
3. §2 XTTS: `pip install TTS`, load
   `tts_models/multilingual/multi-dataset/xtts_v2`, `tts_to_file(text,
   speaker_wav=ref, language="ar")` → `xtts_sample.wav`.
4. §3 OmniVoice: `pip install omnivoice soundfile`,
   `OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map="cuda:0",
   dtype=torch.float16)`, `model.generate(text, ref_audio=ref,
   ref_text=..., language_id="arz", num_step=32)` → `omnivoice_sample.wav`
   (24 kHz). The cell prints the real `generate()` signature first and falls
   back to no `language_id` if the installed version lacks the parameter;
   if `arz` is rejected at runtime, retry with `"arb"`.
5. §4 listening test with a 1–5 scorecard (similarity / intelligibility /
   dialect accuracy / artefacts) filled in by ear, with a stated decision rule.
6. §5 export both WAVs + `comparison_notes.json` to
   `My Drive/bahgat_voice_models/zeroshot_comparison_<date>/`.

Why this route and not the alternatives:

- **VoiceStudio Docker on Colab: impossible.** Colab runtimes cannot run
  Docker containers. No workaround — this step is not "blocked", it is simply
  the wrong tool for Colab, and the notebook does not attempt it.
- **Full VoiceStudio app on Colab: impractical.** It needs Electron/bun/uv
  and the whole repo; there is no pip package for the app. It would also test
  the app's mastering chain rather than the model.
- **This VM (CPU): not feasible for a fair test.** OmniVoice on CPU is
  float32 and slow (the docs budget 600 s per CPU generate, and a 4 GB-class
  render "runs for minutes"); the notebook is written for a Colab T4.
- **What the pip route does not test:** VoiceStudio's mastering chain
  (highpass + compressor at 24 kHz) and its reference-window selection
  (best 15 s passage). The notebook flags this in its header. If OmniVoice
  wins, a follow-up generation through the real VoiceStudio backend on a GPU
  machine is worth one run before committing — same weights, slightly
  different pipeline.

## 3. Verdict: COMPLEMENT — do not replace the RVC/GPT-SoVITS training setup

**Verdict: complement. One-line reason: VoiceStudio adds a strong zero-shot
engine (OmniVoice) and a handy offline-generation API, but it contains no RVC
at all and its GPT-SoVITS is only a client to an external server that does not
support Arabic — so it cannot replace the trained-voice pipeline the bot's
runtime depends on.**

### (a) Does it replace `training/colab/` (RVC notebook + configs)? No

| Piece of the current setup | Does VoiceStudio replace it? |
|---|---|
| **RVC training** (primary: v2 40k, 300 epochs, RMVPE, `.pth` + `.index`) | **No. RVC is not in VoiceStudio at all** — it appears nowhere in the engine catalog (21 engines, §1a). RVC is language-agnostic by design (it converts acoustic features, it does not need to *speak* Arabic), which is exactly why it is primary for an Egyptian-dialect voice. Nothing in VoiceStudio does trained voice *conversion* from Edge TTS audio. |
| **GPT-SoVITS training** (fallback in the RVC notebook) | **No — it makes it a client, not a replacement.** VoiceStudio does not train GPT-SoVITS; it talks HTTP to a separately-run GPT-SoVITS server (§1d). And that server supports only zh/en/ja/yue/ko — Arabic is not supported, which is why the RVC notebook already treats GPT-SoVITS as a fallback with `LANG = "en"`. VoiceStudio adds nothing here except a nicer UI over the same server. |
| **Colab training workflow** (headless CLI, Drive export, resume) | **No — heavier, not lighter.** VoiceStudio is an Electron desktop app + FastAPI backend (+ optional Docker). It cannot run on Colab (no Docker) and cannot run on Render free (512 MB, no GPU). The RVC notebook is a lighter, purpose-built artifact for exactly one job: train on a free T4 and export weights. |
| **Runtime voice path** (Edge TTS `ar-EG-ShakirNeural` → RVC conversion) | **No.** VoiceStudio is an offline/batch tool. It is not a runtime component and must stay off the Render deploy, same as before. |

### (b) What VoiceStudio IS useful for in this project

1. **Zero-shot comparison (now).** Its default engine is the strongest
   zero-shot candidate we have, with an explicit Egyptian Arabic language
   (`arz`) that XTTS lacks. The notebook tests that engine directly via the
   upstream pip package — the comparison is VoiceStudio's main contribution
   to this project.
2. **Offline batch generation (later, if OmniVoice wins).** If the listening
   test favours OmniVoice, the VoiceStudio backend (Docker image on any GPU
   machine, or the pip package in a script) becomes the offline generator:
   feed it bot reply texts + the Bahgat reference clip, get voice notes out,
   ship the WAVs — no training, no RVC inference chain. Its local API
   (`POST /generate`, `POST /v1/audio/speech`, MCP) is built for exactly this
   scripted use. Still offline only; the bot's runtime stays Edge TTS → RVC.
3. **Engine catalog as a discovery list.** The 21-engine catalog is a
   shortlist for future zero-shot tests if OmniVoice disappoints: IndexTTS 2.5
   (cloning + emotion, one-click sidecar install), CosyVoice 3 (cloning),
   VoxCPM2 (cloning + voice design). None of these is verified for Arabic
   either — each would need the same listening test.
4. **Voice design for non-Bahgat voices.** The `instruct` attribute system
   (gender/age/pitch/whisper/accents) is useful if the project ever needs a
   second, invented voice — but it was trained on English/Chinese only, so
   not for Bahgat.

### (c) What VoiceStudio is NOT useful for

- **Runtime on Render free.** 512 MB RAM, no GPU, sleeps after 15 min idle.
  OmniVoice needs ~6 GB VRAM (or a slow CPU) and multi-GB weights. Voice
  inference must stay an offline/batch step; the bot's runtime voice path is
  unchanged (Edge TTS → RVC).
- **Arabic GPT-SoVITS training.** GPT-SoVITS in VoiceStudio is a client to
  an external server, and that server does not support Arabic. It does not
  fix the fallback's language problem.
- **Commercial use under CC-BY-NC.** See §4 — the weights forbid commercial
  use; a paid Pro licence for the app does not change that.
- **Replacing RVC.** See §3a — no RVC engine exists in the catalog.

## 4. Licence implication of CC-BY-NC weights for a parody Telegram bot

What was verified (not legal advice — this is a summary of the licence text
as found in the repo):

- The **app code** is AGPL-3.0, which the licence notice says *includes*
  commercial and internal business use of the application itself (with the
  Affero source-sharing obligation if a modified version is offered over a
  network).
- The **default OmniVoice weights** are **CC-BY-NC** (Creative Commons
  Attribution–NonCommercial), per the `k2-fsa/OmniVoice` model card quoted in
  `LICENSE-NOTICE.md`. The NC term forbids use "primarily intended for or
  directed towards commercial advantage or monetary compensation". The
  tokenizer additionally carries Boson Higgs Audio 2 and Meta Llama community
  terms. Buying VoiceStudio Pro (a commercial licence for the app's code)
  explicitly does **not** replace any of those weight terms.
- This bot is a **non-commercial hobby project**: free Telegram bot, ~15 users
  in 1–2 groups, no payment, no ads, no paid tier, everything free by design.
  On the face of the licence text, that use sits on the non-commercial side of
  the NC line. If the bot ever gains any commercial element (paid access,
  donations tied to the voice, sponsored use), the CC-BY-NC weights would need
  to be replaced — e.g. with an Apache-2.0/MIT-licensed engine from the catalog
  — before that change.
- **Separate from copyright: consent.** Both VoiceStudio's README and the
  upstream model disclaimer prohibit unauthorised voice cloning /
  impersonation. Bahgat Saber is a real living person and has not consented to
  having his voice cloned. The project already mitigates this the only way it
  currently can: the bot is labelled a parody bot (`setMyDescription`), it
  does not claim to be him, and it is a private joke among ~15 people, not a
  public impersonation. That labelling does not create consent — it is a
  mitigation, and the residual risk should stay visible in the project docs.
  (XTTS v2's CPML licence carries the same non-commercial restriction, so the
  licence position does not favour either engine.)

## 5. Open questions / follow-ups

- Run the notebook in Colab once `training/clean/xtts_reference.wav` exists
  (the clean job was still running when this was written — `training/clean/`
  was empty; the notebook handles a missing Drive file with a manual upload).
- If OmniVoice wins: one confirmation run through the real VoiceStudio
  backend (Docker on a GPU machine) to check the app's mastering chain does
  not change the verdict, before using it for batch generation.
- If both engines fail the listening test: zero-shot is not good enough;
  the trained RVC model stays the only voice path, and the comparison result
  should be recorded in `docs/voice-plan.md`.
- The `training/colab/README.md` could gain a one-line pointer to the new
  comparison notebook (not done here — this task only adds the notebook and
  this evaluation).
