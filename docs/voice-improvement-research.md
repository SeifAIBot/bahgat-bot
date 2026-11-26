# Voice-improvement research — making Bahgat sound like Bahgat, not just timbre

**Date researched:** 2026-11-26. **Project:** Bahgat Saber Telegram parody bot.
**Current setup (for reference):** clean dataset **22.54 min, 218 clips, 16 kHz mono,
3–10 s**, solo Bahgat speech, growing to ~30+ min. Training plan: RVC v2, 40 kHz,
RMVPE F0, batch 4, 150 epochs, free Colab T4. Runtime path: Edge TTS
`ar-EG-ShakirNeural` → RVC conversion to Bahgat's timbre. Zero-shot results so far:
OmniVoice — timbre judged **close** by the owner's ear, but speaking style
**"mediocre"** and **slow**; XTTS v2 zero-shot **rejected** by ear (wrong voice,
wrong dialect).

**How to read this document:** every section answers one of the six research
questions (a)–(f). Numbers are quoted from the sources named, not from memory.
Where sources disagree — notably on epoch counts — the disagreement is shown
rather than smoothed over. "No good source found" is stated where that is the
honest answer.

---

## (a) How professionals match SPEAKING STYLE and RHYTHM, not just timbre

### The core fact: RVC is a converter, not a speaker

RVC is speech-to-speech, not text-to-speech. It takes a recorded performance
and returns the same performance in a different voice: "same timing, same
pauses, same emphasis, new timbre" (Eachlabs, RVC v2 guide, published
2026-11-09). The same guide states the rule bluntly: "RVC keeps the
performance. Timing, energy and emphasis come from the input, so the input
take is your direction. A flat read converts into a flat read in a new voice.
If you want a line to land with a smile, record it with a smile. The model
changes who is speaking, not how they meant it."

An independent research matrix (2026-07-17) puts it the same way: RVC timbre
cloning is 8/10, but "ceiling is timbre only: prosody/cadence come from the
DONOR performance you feed in, not from the model" — "no native text-driven
prosody… cadence/emphasis/emotion are inherited from the source donor audio.
Manual controls: pitch transpose (semitones), index/retrieval rate (0–1),
median filter radius (breathiness), RMS volume-envelope mix, and F0 method
(RMVPE/Crepe/FCPE). No pause/rate/style tokens."

The underlying reason is architectural. RVC's content encoder (HuBERT /
ContentVec) is meant to extract speaker-invariant linguistic content, and its
retrieval step replaces source features with the nearest features from the
target's training set (top-1 retrieval). That kills timbre leakage — the
source voice does not bleed through — but it also means the model never
learns *when* Bahgat pauses, *how fast* he attacks a sentence, or *how* he
rises into a shout. Those decisions live in the input audio, not in the
`.pth` file.

**Implication for this project:** no amount of RVC training will make a slow,
polite Shakir reading sound like a fast, shouting Bahgat. The style must be
put into the source audio *before* RVC sees it. That is §(e), and it is the
single most important finding in this document.

### What GPT-SoVITS does differently — and its limits

GPT-SoVITS is a text-to-speech model, not a converter, and it is built in two
stages (voice-cloning guide, GPT-SoVITS v4 doc, accessed 2026-11-26):

- **GPT** (autoregressive) predicts discrete *semantic tokens* that capture
  "phoneme + prosody + duration".
- **SoVITS** (VITS-based decoder) synthesises those tokens + speaker
  conditioning into a mel-spectrogram → waveform.

The guide's summary: "SoVITS handles speaker identity (mostly fixed during
fine-tune), GPT handles speaker prosody (updated during fine-tune to learn
the speaker's rhythm patterns)." That is why the same guide recommends
GPT-SoVITS v4 when a voice "needs to learn the speaker's specific prosody
patterns — not just timbre", and recommends RVC v2 instead when you need
"real-time voice conversion of live input".

A related design, made explicit in the GSV-TTS-Lite / GPT-SoVITS docs, is
that timbre and style are controlled by *separate* reference audios:
`spk_audio` defines **who** is speaking (timbre), while `prompt_audio` +
its transcript defines **how** speech sounds (prosody, emotion, style).
GPT-SoVITS inference likewise takes text + a 3–15 s reference clip + its
transcript, and the guide warns: "Reference clip drifts voice [if] reference
semantic tokens don't match LoRA's learned prosody — use a reference clip
from the training set, not an arbitrary new clip."

**Limits that matter here:**

1. **Arabic is not officially supported by GPT-SoVITS.** Upstream languages
   are zh/ja/en/ko/yue. The project's own training package already works
   around this with `LANG = "en"` (see `docs/voice-training-report.md` §6).
   The v4 guide lists "your target language isn't in zh/ja/en/ko/yue" under
   "When NOT to pick it". So GPT-SoVITS is a *prosody-capable fallback*, not
   a proven Arabic path — its Egyptian-dialect prosody is unverified, and
   any test must be judged by ear on Arabic text, not assumed from its
   Chinese/Japanese results.
2. **Prosody learning needs prosody in the data.** The v4 guide's
   "diminishing returns" section says: beyond ~30 min, focus on diversity,
   not volume — "Emotional range: angry, calm, excited, sad, whispered. The
   model can only generate styles it's seen during training", plus sentence-
   length variety and "declarative + questioning + exclamative + hesitant".
   A dataset that is all calm debate will teach calm debate, however long it is.
3. **GPT-SoVITS is slower and heavier to run** (inference RTF ~0.5 on an
   RTX 5080; training needs ~12 GB VRAM for v4) and it is autoregressive, so
   it can truncate ("only said 4 words") on some inputs. It is not a
   drop-in replacement for the Edge TTS → RVC runtime path; it would be a
   different runtime path (text → GPT-SoVITS directly).

### How zero-shot TTS models do style: the reference prompt carries it

Modern zero-shot TTS (Chatterbox, OmniVoice, Reverb-TTS) works by
conditioning generation on a short reference clip, and the better
documented ones split that conditioning in two. The Chatterbox voice-cloning
guide (DeepWiki, accessed 2026-11-26) describes it clearly: a VoiceEncoder
extracts **speaker embeddings** (timbre), while an S3Gen tokenizer extracts
**prompt tokens** from the first seconds of the reference, which "capture
prosody and speaking style". Duration guidance from that guide: <3 s is
insufficient prosody capture; 3–5 s is minimum viable; **5–7 s is the
optimal balance**; 7–10 s gives maximum prosody detail; >10 s "may include
unwanted variation". Reverb-TTS (built on OmniVoice, Hugging Face model card,
accessed 2026-11-26) gives the same practical rule: "The reference works
best as 3 to 10 seconds of clean speech… References over 15 seconds make
worse takes."

That is exactly why the OmniVoice test in this project used a 3–10 s
reference clip — and why *which* 3–10 s matters: a calm, slow reference
teaches the model calm and slow; a fast, angry, shouting reference teaches
fast and angry. The comparison notebook already flags this ("a flat or
polite delivery scores low on similarity even if it is clear"), but the
knob was never actually turned: see §(f).

### What professionals actually do, in order

Synthesising the sources above, the professional playbook for style match is:

1. **Choose the right architecture for the job.** If the output must be
   *generated from text* with the target's rhythm, use a TTS model that
   predicts duration/prosody (GPT-SoVITS, or a zero-shot model with a
   style prompt). If you already have a performance, use a converter
   (RVC) — and accept that the performance *is* the style.
2. **Make the reference / donor performance match the target style.**
   For RVC this is the *input* audio; for GPT-SoVITS / zero-shot TTS it
   is the *reference clip*. Record or select it in the target's actual
   register — fast, loud, interruptive — not in a neutral register.
3. **Cover the style in training data.** Include the emotions, speeds,
   volumes and sentence shapes the output will need; a model cannot
   invent a register it never heard (§(c)).
4. **Control style at synthesis time with the knobs the engine actually
   has** — speaking-rate / duration parameters, punctuation and
   sentence chunking, emphasis and pauses (SSML for Edge TTS; `speed` /
   `duration` for OmniVoice) — rather than hoping the timbre model
   will add style by itself. It will not.
5. **Judge by ear on the target material.** Loss curves do not measure
   style; A/B listening on real bot lines (short insults, fast
   back-and-forth, shouting) does.

### Sources — (a)

- Eachlabs, "RVC v2: Build Your Own RVC Model and Dial In the Settings",
  published 2026-11-09 — https://www.eachlabs.ai/blog/rvc-v2-build-your-own-rvc-model
- MattModeCode, "Phase-0 research matrix — voice-clone backends",
  2026-07-17 — https://github.com/mattmodecode/double-chin/blob/HEAD/.goal/research/matrix.md
- Wty2003328, "GPT-SoVITS v4 (LoRA fine-tune)", voice-cloning-guide,
  accessed 2026-11-26 — https://github.com/wty2003328/voice-cloning-guide/blob/HEAD/docs/models/gpt-sovits-v4.md
- DeepWiki, "Voice Cloning Guide" (Chatterbox fine-tuning), accessed
  2026-11-26 — https://deepwiki.com/gokhaneraslan/chatterbox-finetuning/6.2-voice-cloning-guide
- Hugging Face, software-mansion/Reverb-TTS model card, accessed
  2026-11-26 — https://huggingface.co/software-mansion/Reverb-TTS
- DeepWiki, "GSV-TTS-Lite" (timbre/style decoupling via `spk_audio` /
  `prompt_audio`), accessed 2026-11-26 — https://deepwiki.com/chinokikiss/GSV-TTS-Lite/1-overview

---

## (b) How much clean data is the real sweet spot for RVC?

### The consensus: 10 min minimum, 15–30 min sweet spot, diminishing after 30 min

The guides agree closely, and they agree that the numbers refer to *clean,
verified* minutes — silences and contaminated audio do not count:

| Source | Floor | Sweet spot | Diminishing returns |
|---|---|---|---|
| Apatero, "RVC Training Dataset Preparation 2026", published 2026-02-18 | 10 min "absolute minimum" | **15–20 min** recommended; 30 min "excellent" | "Beyond 30 minutes: improvements decrease" |
| NiceVois, "RVC Dataset Preparation: How Much Audio?", accessed 2026-11-26 | ~10 min "realistic floor" | **10–30 min** "practical sweet spot" | "Beyond roughly an hour the returns flatten sharply, and past about two hours extra audio changes very little" |
| The Vocal Market, "How Much Vocal Data…", accessed 2026-11-26 (citing RVC project docs: "you can easily train a good VC model with voice data ≤ 10 mins") | 5–10 min minimum viable | 30 min–1 h "recommended for good quality" | "Beyond 5 hours: diminishing returns… the base model is the bottleneck, not the fine-tuning data" |
| Kenneth Lamar, "A Guide to Voice Clones", accessed 2026-11-26 | 10 min "may be adequate in some cases" | 30 min "often results in a very convincing voice"; 1 h+ "typically offers excellent quality" | "Providing much more than an hour results in diminishing returns" |
| VoiceChanger.live, "How to Train Your Own RVC Voice Model", accessed 2026-11-26 | 10–30 min standard | 40+ min "can improve naturalness further" | "stay under 60 minutes to avoid diminishing returns" |
| PropelRC, "RVC WebUI Voice Conversion Guide", accessed 2026-11-26 (author trained 12 models, 5 min–2 h datasets) | 10 min minimum | **15–20 min** "sweet spot… diverse, high-quality audio"; best model was 18 min of varied YouTube content | — |
| SpeechData.ai, "The Data Behind Voice Cloning", accessed 2026-11-26 | — | 10–30 min "recognizable, usable" (light fine-tune); 30 min–3 h "production, consistent quality" | "A carefully scripted 30 minutes often beats a sloppy two hours" |

### Where this project sits

- **6.94 min (the original Karma-only set)** was *below* the 10-min floor:
  usable for RVC in principle, but thin, and the right call was to expand it.
- **22.54 min (current, 218 clips)** sits **inside the sweet spot on every
  source above**: above Apatero's 15–20 min recommendation, inside NiceVois's
  10–30 min band, and at/above PropelRC's 15–20 min sweet spot. It is enough
  to train a good RVC model. It is *not* under-data any more.
- **~30 min (the planned growth target)** is the point Apatero calls
  "excellent" and Kenneth Lamar calls "very convincing". Going from 22.5 to
  ~30 min is worth doing *if the extra minutes add diversity* (see below) —
  it is the last stretch where most guides still expect a real gain.
- **Beyond 30–60 min, expect little.** Every source puts the flattening
  somewhere between 30 min and 1 hour, and all of them say the same thing
  about what to do instead: improve *quality and diversity*, not minutes.
  "20 minutes of good audio beats 60 minutes of poor audio" (Apatero);
  "Fifteen well-chosen minutes will outperform fifteen careless ones by a
  wide margin" (NiceVois); "10 minutes of clean studio audio will outperform
  60 minutes of noisy, bleed-contaminated audio" (The Vocal Market).

### What "more" should mean for Bahgat specifically

More minutes only help if they add *coverage the current 22.54 min lacks*.
The guides' diversity test is: different topics, emotions, energy levels,
and speaking speeds. For Bahgat that translates to concrete gaps to audit
before adding more audio:

- **Fast / shouting / angry** — the register the bot actually uses most.
  If the current set is mostly measured debate speech, the model will be
  good at measured debate speech and weak at shouting, however many calm
  minutes are added. Eachlabs makes the general point: "a session of one
  calm read gives you a voice that can only be calm… get a little loud,
  drop to a near whisper."
- **Short interjections and insults** — the bot's shortest replies. Very
  short clips (<3 s) were deliberately excluded during cleaning (correctly —
  they risk guest-voice contamination), but that means the model has
  relatively little exposure to Bahgat's 1–2 s bursts. This is a coverage
  gap that *duration* alone does not fix; it needs clean short-burst
  material from solo passages, not more long debate turns.
- **Questions, laughter, interruptions** — the shapes that make a group-chat
  voice feel alive rather than read-aloud.

The un-cleaned raw files already on disk (Lagan, committee-girl, Christian
debate — see `docs/voice-training-report.md` §1) are the cheapest source of
those extra ~8 min to reach 30 min, *provided they are cleaned to the same
bar* (solo Bahgat only, no guest leakage). Adding them as noisy minutes
would be worse than not adding them.

### A note on GPT-SoVITS data needs (for comparison)

GPT-SoVITS fine-tuning is quoted at 1–30 min of training audio (v4 guide),
with the same ~30-min diminishing-returns point ("Diminishing returns around
30 min of clean speech. Beyond that, focus on diversity not volume"). So
the current 22.54 min set is also in-range for the GPT-SoVITS fallback —
data quantity is not the blocker for either path.

### Sources — (b)

- Apatero, "RVC Training Dataset Preparation 2026", published 2026-02-18 —
  https://apatero.com/blog/rvc-training-dataset-preparation-tips-2026
- NiceVois, "RVC Dataset Preparation: How Much Audio?", accessed 2026-11-26 —
  https://nicevois.com/guides/rvc-dataset-preparation
- The Vocal Market, "How Much Vocal Data Do You Need to Train a Singing
  Voice Model", accessed 2026-11-26 —
  https://thevocalmarket.com/blogs/enterprise/how-much-vocal-data-to-train-voice-model
- Kenneth Lamar, "A Guide to Voice Clones", accessed 2026-11-26 —
  https://kennethmlamar.com/posts/voice-clones-guide/
- VoiceChanger.live / Echo, "How to Train Your Own RVC Voice Model",
  accessed 2026-11-26 — https://voicechanger.live/hub/how-to-train-rvc-model
- PropelRC, "RVC WebUI Voice Conversion Guide", accessed 2026-11-26 —
  https://www.propelrc.com/rvc-webui-voice-conversion/
- SpeechData.ai, "The Data Behind Voice Cloning: Recordings, Consent, and
  Quality", accessed 2026-11-26 —
  https://www.speechdata.ai/blog/voice-cloning-training-data

---

## (c) Data-quality levers: what matters most, and how pros handle it

### Ranked by impact (synthesis of the sources)

**1. Single speaker only — the most damaging failure mode.**
"Other voices. Interviews, duets, and crowd noise are the single most
damaging inclusion" (NiceVois). "Multiple speakers: creates confused model"
(Apatero). "All vocals from other people should be removed, isolating to a
single speaker" (Kenneth Lamar). The current project's cleaning already
enforces this (tiered-confidence labelling, 0 of 75 Karma clips containing
guest audio) — that discipline is the highest-value thing in the pipeline,
and loosening it to chase minutes (e.g. admitting the 19 "conflict" clips
or bridging across guest turns) would cost more than the minutes gain.
Length cannot compensate for contamination: "If a second voice appears, it
learns that too… Length cannot compensate for contamination — it multiplies
it" (NiceVois).

**2. Noise and reverb — they are learned as part of the voice.**
"Background noise trains into model" / "Heavy background noise: noise
trains into model" (Apatero). "Voice cloning models are faithful copyists.
They reproduce whatever is in the training audio, including the parts you
did not mean to capture. If there is a hum… the cloned voice can carry a
hum. If the room has echo, the clone sounds like it is in that room"
(SpeechData.ai). "Reverb should be removed in the training set… Ideally,
the dataset doesn't have any reverb to begin with" (Kenneth Lamar, who
recommends UVR `UVR-DeEcho-DeReverb` as a remover). "Room echo becomes part
of the voice the model learns. A small, dead room beats a big, beautiful
one every time" (Eachlabs). For this project the sources are YouTube
debate recordings, not a studio — so some room character is unavoidable;
the practical rule is *consistency* (same room/mic character across clips)
rather than perfection, and gentle separation rather than aggressive
processing (see below).

**3. Loudness consistency.**
"Ensure all performances were recorded at the same gain levels, to ensure
accurate loudness behaviours in the cloned voice" (Kenneth Lamar). "All
clips should be to the same quality. Mixing recordings produced with
radically different microphones, different vocal effects… or various levels
of file compression… will result in a model that sometimes picks from
different qualities" (Kenneth Lamar). Apatero's concrete targets: peak
−3 dB to −6 dB, gentle compression only if needed, never clip ("No
distortion from over-normalization"). Fish Audio's guide (via 101 AI Tools,
accessed 2026-11-26) gives the same band: peaks around −6 dB to −3 dB,
average speech around −18 dB, true peak near −3 dB — and "clipping is worse
than it sounds on playback… there is no cleanup step" that repairs it.
The current set measures −13.84 LUFS integrated / RMS −14.35 dB — a
reasonable, consistent level; the check to run when adding new videos is
that the new clips land in the same loudness band, not that they are
individually maximised.

**4. Diversity of emotion and speaking speed — the style lever.**
This is the lever that most directly bears on the "mediocre / slow" complaint,
and it is where RVC training data *does* influence style, indirectly:
the retrieval index can only return features the model has heard. "Include
varied speech: different topics, different emotions (happy, serious,
excited, calm), different energy (loud, quiet, fast, slow), natural speech:
conversational, not just reading" (Apatero). "Variety within one speaker is
what you are after: different sentences, a natural range of pitch and
volume, and more than one emotional register. A dataset of one sentence
repeated is long but narrow, and the model will sound narrow too"
(NiceVois). "If every sentence is spoken in the same flat tone, the model
learns a flat voice" (Mimicore RVC beginners' guide, accessed 2026-11-26).
Eachlabs again: record "the whispers, laughs and loud lines you'll need
later, because the model can't invent sounds it never heard." For Bahgat,
"fast + loud + angry" is not an edge case to include for completeness — it
is the *primary* register, and it should be a large share of the set, not a
token few clips. Conversely, a useful caution from Kenneth Lamar: "Avoid
using impersonation performances or fake accents in training, as they can
contaminate the data set… the final voice clone will trend toward the same
style. For instance, voices captured from audiobooks sound like they're
reading." Bahgat *debating calmly* is, for this bot, the equivalent of the
audiobook problem.

**5. Clip length: 3–15 s, split at natural pauses.**
Apatero: "3–15 seconds per clip… split at pauses… roughly similar lengths."
The current 3–10 s clips fit this. Shorter than 3 s risks fragments with no
prosodic context; much longer than 15 s wastes training time and mixes
registers inside one clip. Also: "Remove long silences: speeds training, no
value. Keep breathing: natural element of speech. Trim starts/ends: clean
boundaries" (Apatero); "Truncating extended periods of silence… keeps the
training data compact… the model doesn't need to train on silence"
(Kenneth Lamar). The current set already has only 21.1 s of ≥0.5 s silence
in the Karma source, so this is not a live problem.

**6. Quantity — last, not first.**
Every source in §(b) ranks quantity below the five levers above. "More
quality beats more quantity" is the verbatim Apatero headline, and
SpeechData.ai's version is the sharpest: "The models are good and the
tooling is accessible, so the algorithm is rarely what holds a project
back. The data is."

### How pros handle cleaning without wrecking the audio

- **Gentle reduction, not aggressive processing.** "Approach: gentle
  reduction, preserve voice quality… Warning: over-processing hurts more
  than helps" (Apatero). "Some noise is better than too much processing"
  (Apatero FAQ). "Aggressive noise removal can itself create metallic
  artifacts the model then learns" (NiceVois). "Do not over-process — each
  pass slightly degrades quality" (VoiceChanger.live).
- **Separate first, then decide.** Vocal separation (UVR5 / MDX-Net Kim
  Vocal 1 for separation; `UVR-DeEcho-DeReverb` for reverb) is the standard
  first step when the source has music or room sound — but separation is a
  safety net, not a cleaning service, and material that will not separate
  cleanly should be discarded, not forced (NiceVois sequence: separate →
  discard what will not separate cleanly → cut other voices → trim
  silences/distortion → check total).
- **Listen to everything.** "Whenever possible, listen to every second of
  your training data before starting the training process" (Kenneth Lamar);
  "Listen through: catch problems before training… spot check random samples
  from different sections" (Apatero); NiceVois's sanity check: "listen to
  the finished dataset end to end once. Anything that makes you wince is
  something the model is about to learn." For 22.54 min this is a ~25-minute
  listen — cheap, and it is the only reliable contamination check.
- **Keep format consistent.** WAV, mono, 16-bit; sample rate 44.1/48 kHz
  in the guides (the project's 16 kHz clips are resampled to 40 kHz by the
  RVC preprocessing step, which is the correct place for that conversion —
  do not upsample the stored clips and pretend the information is there).

### Sources — (c)

- Apatero, dataset preparation guide, published 2026-02-18 —
  https://apatero.com/blog/rvc-training-dataset-preparation-tips-2026
- NiceVois, dataset preparation guide, accessed 2026-11-26 —
  https://nicevois.com/guides/rvc-dataset-preparation
- SpeechData.ai, "The Data Behind Voice Cloning", accessed 2026-11-26 —
  https://www.speechdata.ai/blog/voice-cloning-training-data
- Kenneth Lamar, "A Guide to Voice Clones", accessed 2026-11-26 —
  https://kennethmlamar.com/posts/voice-clones-guide/
- Eachlabs, RVC v2 guide, published 2026-11-09 —
  https://www.eachlabs.ai/blog/rvc-v2-build-your-own-rvc-model
- 101 AI Tools, "Fish Audio voice cloning: how to get clean, ethical
  results", accessed 2026-11-26 —
  https://101aitools.com/guides/fish-audio-voice-cloning-how-to-get-clean-ethical-results
- Mimicore, "RVC Voice Training for Beginners (Plain English)", accessed
  2026-11-26 — https://mimicore.app/rvc-for-beginners/
- VoiceChanger.live, "How to Train Your Own RVC Voice Model", accessed
  2026-11-26 — https://voicechanger.live/hub/how-to-train-rvc-model

---

## (d) RVC training hyperparameters that affect quality

All values below are for **RVC v2, f0 model, Colab T4 (15 GB VRAM)** unless
stated. The project's planned values are shown against the community range.

### Epochs — the most argued-over number; 150 is defensible, 200 is the modal advice

There is no single community number; the honest range is **100–300**, with
most guides centring on **150–300** and warning that the *best checkpoint is
rarely the last one*:

- VoiceChanger.live: "Epochs (200–500)… Start with 200–300 and evaluate…
  the best checkpoint is rarely the last one — most experienced trainers
  find the sweet spot somewhere between epoch 200 and 400." (Note: 200–500
  is the high end of the range; the same guide says over-training "causes
  robotic artifacts".)
- HAWX Tech, "Train a Local RVC Voice Model with Clean Audio", accessed
  2026-11-26: "Total epochs: set between 200 and 300. Training past 400
  epochs on small datasets (under 15 minutes) introduces harsh vocal
  artifacts caused by model overfitting."
- Applio studio production guide (GitHub, accessed 2026-11-26): "Total
  Epochs: 150 to 300 (scales to data). Shorter dataset = more epochs.
  Longer dataset = fewer epochs."
- Nivant Labs RVC write-up, accessed 2026-11-26: "Epochs: 150–300 (more
  data = fewer epochs needed)"; "Common gotchas: … over-training (300+
  epochs on small data)".
- PropelRC: "training… for 100–300 epochs"; "Epochs: 150–300".
- ChangeLyric, "How To Make an AI Voice Model That Actually Sounds Good",
  updated 2026-04-17: "Epochs: start with 150–200 epochs. Going higher is
  not always better. Overtraining makes the model sound robotic and lose
  natural variation."
- Eachlabs (2026-11-09): the worked example trains 80 epochs, but the
  guide's own advice is to run a short smoke test first (10 epochs, to
  catch dataset problems early) and then the long run, "testing checkpoints
  every 10 to 20 epochs to avoid overfitting".

**Assessment for this project:** the planned **150 epochs** sits at the low
end of the 150–300 consensus band. That is reasonable for 22.54 min of data
(more data = fewer epochs needed), and it is *safer* than 300 on a
shouty, narrow-register dataset. The risk of 150 is mild underfitting, not
catastrophe — and it is fully mitigated by saving every 10 epochs and
listening to checkpoints (100, 120, 150, and, if the run is extended,
180–200) on the *same* held-out test lines. Do **not** extend to 300+
"just in case": on a <30-min dataset that is precisely where the
overfitting reports cluster. If 150 sounds undertrained (thin, unlike him
on held-out lines), the correct next step is a second run to ~200 with
checkpoints, not a blind jump to 400.

### Batch size — 4 is safe on a T4; 8 is the other defensible value

- The RVC WebUI's own default rule is **batch = VRAM in GB ÷ 2** — ~7 on a
  15 GB T4 (NexGPU RVC VRAM guide, accessed 2026-11-26).
- HAWX Tech: 8 on an 8 GB GPU, 16 on 12 GB, 32 on 24 GB; "if the terminal
  throws a CUDA out of memory error, lower this value immediately."
- VoiceChanger.live: 6 GB VRAM → 4–6; 8 GB → 6–8; 12 GB+ → 8–12.
- Applio studio guide: batch **8**, with the rationale that it "introduces
  necessary gradient noise to capture human texture" — i.e. a slightly
  larger batch is not purely a speed choice; very small batches can
  over-fit noisily, very large batches can over-smooth.
- Nivant Labs: "Batch size: 4–8 (depends on VRAM)".

**Assessment:** planned **batch 4** is safe and slightly conservative on a
shared Colab T4 (where usable VRAM is less predictable than on a local
card). It trades a little training speed for OOM safety. Batch 8 is the
only alternative worth A/B-ing, and only if batch 4's output sounds
over-fitted or unstable — do not change batch size and epochs in the same
run, or you will not know which change mattered.

### F0 method — RMVPE is the consensus; the alternatives are fallbacks

| Method | Speed | Stability / quality | When to use it |
|---|---|---|---|
| **RMVPE** | Fast | "Extremely high" (HAWX Tech table) | Default for speech and singing; "the standard selection… better accuracy than Harvest without the severe processing time and memory overhead of Crepe" |
| Crepe / Mangio-Crepe | Very slow | Very high | Noisy speech, sung acapellas, micro-detail on dry audio; "second opinion when the pitch wobbles on held notes, not as a starting point" (Eachlabs) |
| Harvest | Slow | High, "muffled highs" | Quiet speech, low-pitch stability |
| Dio | Fast | Medium | Cheap fallback |
| PM | Fastest | Low | Low-spec testing, rough drafts only |
| FCPE | — | — | Added in RVC release 2.3.260718 (2026); too new for a settled community verdict — do not switch to it for this run |

Sources: HAWX Tech F0 comparison table; Eachlabs (RMVPE "described in
[RVC's] changelog as the strongest open-source vocal pitch extraction model
at the time"); Nivant Labs ("RMVPE (best quality)"); Xport Studio
(2026-10-24: "RMVPE is the usual choice today: fast and reliable on most
vocals… try another method only if notes wobble or jump an octave");
Apatero open-source guide ("Use RMVPE for f0 extraction. I've tested all
the methods, and RMVPE wins on both quality and speed").

**Assessment:** planned **RMVPE on CUDA** is correct. F0 must be **on**
for this voice: without pitch guidance the model cannot track Bahgat's
shouting pitch excursions at all ("omitting f0 results in a speech-only
model that cannot track melodic pitch changes" — HAWX Tech). Note that
RMVPE is also the right *inference* F0 method (§(e)) — training and
inference F0 should match unless there is a specific reason to differ.

### Sample rate — 40 kHz is right; 48 kHz buys nothing here

- 40 kHz is "the community standard" (VoiceChanger.live), "the default
  almost everyone should use… virtually every community voice checkpoint
  you will find is this tier" (NexGPU), and "40kHz is the dominant sample
  rate for RVC models in the wild" (Mojo Audio research note, 2026-03-20 —
  v2 initially shipped with only 40 k pretrains).
- 48 kHz "captures slightly more high-frequency detail but requires more
  compute. Use 40kHz unless you have a specific reason to go higher"
  (VoiceChanger.live). NexGPU: 48 k is "one notch heavier than 40k; 24 GB
  recommended… Use it when the render goes straight into a film mix or a
  48 kHz master. For dubbing and short-form video it buys you nothing
  audible and costs real VRAM and time." The project's own config notes
  the same 24 GB figure — a free T4 cannot train 48 k comfortably.
- The decisive point for this project: the source clips are **16 kHz**.
  48 kHz cannot invent frequencies above 8 kHz that were never recorded;
  it would only upsample. And the output is Telegram voice notes (Opus),
  not a film mix. 40 kHz is correct; 32 kHz is the fallback if VRAM is
  tight, not an upgrade path.

### Index building — build it; it is what makes RVC "retrieval-based"

After training, RVC builds a FAISS index (`added_*.index`) over the
training set's ContentVec features. At inference, top-1 retrieval replaces
each source feature with the nearest target feature from that index — that
lookup is the mechanism that suppresses timbre leakage (§(a)). Without an
index the model still works (`index_rate = 0`), but it is a plain VITS
conversion and sounds less like the target. The Applio studio guide
recommends FAISS (or KMeans) as the index algorithm. Practical notes:
the index is built from the *training* clips, so its quality is bounded
by §(c) — a noisy index injects noise at inference, which is one reason
high `index_rate` on a noisy dataset sounds gritty (§(e)). The index file
ships alongside the `.pth` (the project exports both).

### Overtraining — how to recognise it, and what to do

Convergent descriptions across every guide:

- **Sound:** "robotic, metallic, or distorted — especially on vowels and
  sustained sounds. The voice loses its natural quality and starts sounding
  artificial" (VoiceChanger.live). "Sounds great on sentences like the
  training audio and strange on everything else" (Eachlabs). "Harsh vocal
  artifacts" on small datasets past ~400 epochs (HAWX Tech).
- **Loss curve:** "Watch the loss curve — it should decrease steadily and
  then flatten. When it flattens, the model has learned what it can from
  the data. Continuing beyond this point risks over-training"
  (VoiceChanger.live). "If it flatlines early, you probably need more
  diverse training data. If it starts going back up after dropping, you are
  overtraining. Stop the run and use the checkpoint from the lowest point"
  (ChangeLyric). Kenneth Lamar's method: TensorBoard, `loss/g/total`,
  "the inflection point… where the loss is no longer decreasing, is the
  right point to stop training. I save in 5 epoch intervals so I can keep
  only the optimal model, before the point of overtraining."
- **One dissenting note worth recording:** the Applio studio guide says
  "Overtraining Detector: OFF / Disabled. GAN loss curves are deceptive.
  Only rely on ear A/B testing." Loss and ears disagree sometimes; when
  they do, ears win — but loss flattening is still the cheapest early
  warning, and it costs nothing to watch it.
- **Fix:** roll back to an earlier checkpoint — "try epoch 150–250" if the
  late checkpoints sound robotic (VoiceChanger.live); "try using an earlier
  save file (e.g. epoch 150 instead of 200)" (Trend-Rays RVC tutorial).
  If *all* checkpoints sound robotic, the cause is usually the dataset
  (reverb/noise), not the epoch count — retraining longer will not fix it.

**Assessment:** save every 10 epochs (planned) is right; consider every
5–10 for the final stretch if disk allows (each checkpoint is ~100–200 MB,
so 10-epoch spacing on a 150-epoch run is ~15 checkpoints — already a lot
to listen to; listen to every 20–30 first, then narrow in).

### Sources — (d)

- VoiceChanger.live, "How to Train Your Own RVC Voice Model", accessed
  2026-11-26 — https://voicechanger.live/hub/how-to-train-rvc-model
- HAWX Tech, "Train a Local RVC Voice Model with Clean Audio", accessed
  2026-11-26 — https://www.hawxtech.net/train-a-local-rvc-voice-model-with-clean-audio-samples.html
- Applio studio production guide (froggeric/applio-macOS-native-app),
  accessed 2026-11-26 —
  https://github.com/froggeric/applio-macos-native-app/blob/HEAD/STUDIO_PRODUCTION_GUIDE.md
- Nivant Labs, "RVC: Retrieval-based Voice Conversion", accessed 2026-11-26 —
  https://nivantlabs.com/blog/ai-tools-rvc/
- PropelRC, "RVC WebUI Voice Conversion Guide", accessed 2026-11-26 —
  https://www.propelrc.com/rvc-webui-voice-conversion/
- ChangeLyric, "How To Make an AI Voice Model That Actually Sounds Good",
  updated 2026-04-17 — https://changelyric.com/blog/ai-voice-model-guide
- Eachlabs, RVC v2 guide, published 2026-11-09 —
  https://www.eachlabs.ai/blog/rvc-v2-build-your-own-rvc-model
- NexGPU, "RVC VRAM Requirements", accessed 2026-11-26 —
  https://nexgpu.net/en/models/rvc/
- Mojo Audio, "RVC Model Sample Rate Distribution in the Wild",
  2026-03-20 —
  https://github.com/itsdevcoffee/mojo-audio/blob/HEAD/docs/research/03-20-2026-rvc-sample-rate-distribution.md
- Xport Studio, "Best RVC Settings", 2026-10-24 —
  https://xportstudio.com/blog/best-rvc-settings
- Apatero, "AI Voice Cloning Open Source Guide 2026", accessed 2026-11-26 —
  https://www.apatero.com/blog/ai-voice-cloning-open-source-guide-2026

---

## (e) RVC inference settings — and why the SOURCE audio controls speed

### First, the plain-English core of this section

**RVC converts timbre but keeps the source audio's prosody.** Duration,
pauses, emphasis, speed, loudness contour and emotional arc all come from
the input file. RVC does not re-time, re-pause or re-emphasise anything.
There is no RVC inference knob for "speak faster", "sound angrier" or
"pause less". If the input is a slow, calm, evenly-paced Shakir reading,
the output is a slow, calm, evenly-paced reading *in Bahgat's voice* —
which is exactly the "close timbre, mediocre style, feels slow" result the
OmniVoice test produced, and exactly what the Edge TTS → RVC path will
produce unless the Edge TTS input is fixed first.

This is not an inference-tuning problem. It is a *source-performance*
problem, and it has to be solved upstream of RVC, in the text-to-speech
step. The rest of this section covers (i) what the RVC dials actually do,
so they are not blamed for what they cannot do, and (ii) what can be done
to the Edge TTS source, which is where the speed and style actually live.

### The RVC inference dials (what each one does, safe starting values)

All defaults below are the RVC WebUI / each::labs defaults, corroborated by
Xport Studio (2026-10-24) and the RVC CLI docs (via the fork CLAUDE.md,
accessed 2026-11-26). **Change one dial per run and write down what
changed** — "changing three at once makes it impossible to know which one
helped" (Xport Studio).

| Dial | Range / default | What it does | Starting value for this project | If it sounds wrong |
|---|---|---|---|---|
| **Transpose / pitch shift (`f0up_key`)** | semitones; 0 default; ±12 = one octave | Shifts input pitch into the model's natural range *before* conversion | **0** (both Shakir and Bahgat are adult male; measure first — see below) | Strained / cartoonish / sleepy → pitch is wrong, not the model. Small ±2–5 shifts for close voices; ±12 only across genders. The XTTS sample measured median F0 129.7 Hz vs reference 158.4 Hz — a ~29 Hz gap — so a small upward shift (+1 to +3 semitones) is worth A/B-testing on RVC output, by ear, not by formula |
| **F0 method (inference)** | rmvpe (default), mangio-crepe, harvest, dio, pm | How pitch is tracked in the *input* before conversion | **RMVPE** | Notes wobble / jump an octave → try mangio-crepe (hop 128 default; lower = more frequent checks, slower, more crack risk). Keep training and inference F0 the same unless testing a specific fault |
| **Index rate** | 0–1; default 0.5 (each::labs) / 0.75 (RVC CLI docs for speech: 0.88 in that doc's speech example; 0.75 music) | How strongly the output pulls toward the training set's features (retrieval) vs the base model / source. Higher = more like the target voice | **0.5–0.75**; project config already says ≈0.75 | Not enough like Bahgat → raise. Metallic / gritty / breathy / artefacts on every word → **lower first** (this is the first dial to move for artefacts). "Going above 0.8 often introduces artifacts" (Apatero guide). High index rate on a noisy dataset is worse, because the noise lives in the index too (Xport Studio) |
| **Filter radius** | 0–7; default 3 | Median filtering on the tracked F0 (≥3 applies it). Smooths pitch jitter | **3** | Breathiness / wobble → raise slightly; over-smoothing flattens expressive pitch jumps (shouting) — do not push past 5 for this voice without listening |
| **RMS mix rate** | 0–1; default 0.25 | Whose loudness envelope: 0 = follow the input's dynamics, 1 = fixed loudness | **0.25, or lower (0–0.25)** | Volume pumping → lower. Whispers coming out as loud as shouts → lower (Eachlabs: "for acting, dialogue or anything with a whisper in it, keep it low"). The Applio studio guide's 0.80–1.00 is a *music-mixing* value — do not copy it for speech; for a shouty voice the input dynamics *are* the performance |
| **Protect (voiceless consonants)** | 0–0.5; default 0.33; 0.5 = protection off | Shields breaths and voiceless consonants (s, t, k, f) from being pushed through the voice model, where they tear | **0.33**; try **0.2–0.33** for speech | Mushy / hissing s and t, crackling breaths → lower slightly. Too low → words sound swallowed, and indexing accuracy drops (RVC's own note, via Eachlabs). "Spoken lines benefit from a slightly lower protect value, so consonants stay crisp" (Xport Studio) |

**What none of these dials do:** change duration, change speaking rate,
add or remove pauses, add anger, change word emphasis, or fix a flat
delivery. If the output feels slow, do not reach for index rate or filter
radius — reach for the source audio.

### The source audio is the style: Edge TTS `ar-EG-ShakirNeural`

The bot's current voice path (`tools/voice.py`) calls Edge TTS with
`rate="+5%"`, `pitch="+0Hz"`. That is, for practical purposes, Shakir's
default delivery: a calm, newsreader-like Egyptian male voice, 5% faster
than its own default. Bahgat is fast, loud, interruptive, profanity-heavy,
with short sentences, repeated words, and abrupt pitch jumps. A 5% rate
lift does not bridge that gap — it is within normal inter-sentence
variation.

**What Edge TTS / SSML can actually control** (Microsoft Learn, "Speech
Synthesis Markup Language (SSML) document structure and events", accessed
2026-11-26; edge-tts CLI docs, accessed 2026-11-26):

- **`<prosody rate="…">`** — speaking rate. Values are relative
  (`slow`/`fast`) or percentages (`+25%`, `+50%`, `+100%` = 2× speed;
  negative for slower). The edge-tts `--rate` flag uses the same syntax:
  `+25%` (faster), `-25%` (slower), `+100%` (2×). Microsoft's own Q&A
  confirms the mechanism: for full-text synthesis, rate is applied via
  SSML `<prosody rate="1.2">…</prosody>`; request-level rate properties are
  ignored for text-streaming inputs, so SSML is the supported route.
  *Caveat:* this is a synthesis-time rate change, not a dumb resample —
  the voice stays at the same pitch while speaking faster — but past
  ~+30–40% most neural voices start to sound rushed and clip consonants.
  There is no published "correct" percentage for Bahgat; it must be found
  by laddering (+10%, +20%, +30%) on real bot lines and listening.
- **`<prosody pitch="…">` / `volume="…"`** — pitch in Hz or %, volume in %.
  A modest pitch lift and volume lift can push Shakir toward Bahgat's
  excited register, but they cannot create shouting — they shift the whole
  line uniformly.
- **`<break time="…"/>`** — explicit pauses. This is the *only* direct
  pause control, and it matters: Bahgat's rhythm is as much about *where*
  he does not pause (barrelling through) and where he stops dead
  (before an insult) as about raw speed. Shortening or removing the
  default inter-sentence pauses is as important as raising the rate.
- **`<emphasis level="strong">`** — emphasis on a word. Useful for the
  insult word / punch word in a line.
- **Punctuation and text shaping** — the cheapest, most reliable lever.
  Short sentences, exclamation marks, repeated words ("يا عم يا عم"),
  and comma placement change Shakir's phrasing directly, because the TTS
  model reads punctuation as prosody. The bot's text generator already
  controls this; it should be treated as a *voice* control, not just a
  *text style* control.
- **What Edge TTS cannot do for this voice:** Azure's `<mstts:express-as
  style="…">` speaking styles (cheerful, empathetic, newscast…) are
  supported only for a small list of voices — the documented examples are
  `en-US-JessaNeural` and `zh-CN-XiaoxiaoNeural` — and there is no
  documented style (angry / shouting / excited) for `ar-EG-ShakirNeural`.
  Do not plan around `express-as` for Shakir; verify it per-voice before
  relying on it, and expect it to be ignored.

**Practical ladder for the source (test in this order, one change at a time):**

1. **Rate ladder on real lines:** `+5%` (today) → `+15%` → `+25%` → `+35%`,
   same 5–6 bot lines each time (a short insult, a fast question, a long
   rant). Pick the fastest rate that is still intelligible in Egyptian
   Arabic — expect the answer to be around +20–30%, not +5%.
2. **Per-mood rate:** angry / insult replies faster (+25–35%) and louder;
   calm / explanatory replies near today's rate. The bot already knows the
   mood (§(a) of the bot's brain); the voice call should receive it. This
   is a small code change with a large perceptual payoff, and it mirrors
   how the *text* already varies by mood.
3. **Punctuation / chunking:** split long replies into short sentences
   with `!` and `…` where Bahgat would hammer; strip the polite,
   evenly-paced connective tissue. Test whether Shakir's phrasing follows.
4. **Pitch/volume nudge on angry lines only:** e.g. `pitch="+10Hz"` /
   `volume="+10%"` on insults — small, and only if the rate ladder alone
   still sounds flat.
5. **Post-hoc time-stretch as a fallback, not a first resort:** if the
   fastest intelligible Edge TTS rate is still too slow, the RVC output
   can be sped up with `ffmpeg atempo` (pitch-preserving) — but beyond
   ~1.15× this audibly rushes consonants and shortens the pauses that
   *are* Bahgat's timing. Fix the source first; use atempo only for a
   final 5–15% trim, and A/B it.

### Two more source-audio rules from the RVC guides

- **Loud, clear input converts better.** "Louder input audio tends to
  work better for pronunciation quality. If the input is too quiet, then
  the voice starts to sound mumbly. If possible, amplify the input
  performance before processing, then reduce the converted output audio
  back down" (Kenneth Lamar). Edge TTS output is already clean and loud,
  so this is satisfied — but do not feed RVC a quiet or MP3-recompressed
  intermediate; keep the chain WAV → RVC → Opus.
- **"Mispronunciations are minimized by speaking loudly, slowly, and
  clearly"** (Kenneth Lamar) — which directly conflicts with "speak fast
  like Bahgat". That tension is real: the faster the source, the more the
  converter has to track. It is another reason to ladder the rate rather
  than jumping to +50%.

### Sources — (e)

- Eachlabs, RVC v2 guide, published 2026-11-09 —
  https://www.eachlabs.ai/blog/rvc-v2-build-your-own-rvc-model
- Xport Studio, "Best RVC Settings: Pitch, Index Rate, Protect Explained",
  2026-10-24 — https://xportstudio.com/blog/best-rvc-settings
- Ultimate RVC (PyPI), parameter reference (`--index-rate`,
  `--filter-radius`, `--rms-mix-rate`, `--protect`, `--f0-method`),
  accessed 2026-11-26 — https://pypi.org/project/ultimate-rvc/0.1.19/
- RVC fork CLAUDE.md, CLI inference parameter table, accessed 2026-11-26 —
  https://github.com/dinhnguyen2210/retrieval-based-voice-conversion-webui/blob/HEAD/CLAUDE.md
- Microsoft Learn, "Speech Synthesis Markup Language (SSML) document
  structure and events", accessed 2026-11-26 —
  https://learn.microsoft.com/hr-hr/azure/ai-services/speech-service/speech-synthesis-markup-structure
- Microsoft Q&A, "How to change speech speed (rate)…", accessed 2026-11-26 —
  https://learn.microsoft.com/en-us/answers/questions/5723830/how-to-change-speech-speed-rate-when-use-input-tex
- Edge-TTS-Compatible README (rate/speed mapping: `1.5` → `+50%`,
  `0.5` → `−50%`; voice list incl. `ar-EG-ShakirNeural`), accessed
  2026-11-26 —
  https://github.com/joey-kot/edge-tts-compatible/blob/HEAD/README.md
- Kenneth Lamar, "A Guide to Voice Clones", accessed 2026-11-26 —
  https://kennethmlamar.com/posts/voice-clones-guide/
- Apatero, "AI Voice Cloning Open Source Guide 2026", accessed 2026-11-26 —
  https://www.apatero.com/blog/ai-voice-cloning-open-source-guide-2026
- Project source: `tools/voice.py` (`rate="+5%"`, `pitch="+0Hz"`,
  voice `ar-EG-ShakirNeural`); `training/colab/rvc_config.md`
  (inference `index_rate ≈ 0.75`).

---

## (f) OmniVoice-specific knobs that affect speaking speed / prosody

### What exists (upstream `k2-fsa/OmniVoice`, PyPI `omnivoice`)

The upstream model card (Hugging Face, `k2-fsa/OmniVoice` mirror, accessed
2026-11-26; paper arXiv:2604.00688, Zhu et al., 2026) documents
`model.generate()` with these generation parameters:

| Knob | What it does | Relevance to "slow / mediocre style" |
|---|---|---|
| **`speed`** (float, default 1.0) | Speaking-rate multiplier: `>1.0` faster, `<1.0` slower. The single most relevant knob — it is the direct equivalent of Edge TTS's SSML rate, but inside the zero-shot model | **This is the fix for "feels slow" in OmniVoice.** The comparison run never set it (see below), so the slow result was produced at the default 1.0. Try `speed=1.15`, `1.25`, `1.35` on the same sentence and reference, and listen. One caution from a downstream server's docs: "rates below 1.0 can clip the first word" (omnivoice-edu) — no equivalent warning was found for rates above 1.0, but intelligibility still degrades as speed rises; ladder it |
| **`duration`** (float, seconds) | Fixes the total output duration; **overrides `speed`** if both are given | Useful for a controlled A/B (force the same sentence to, say, 4 s vs 5.5 s), but it is a blunt instrument — it stretches/compresses the whole utterance uniformly. Do not use it as the daily control; use `speed` |
| **`num_step`** (int, default 32; 16 for faster inference) | Diffusion steps. 32 is the quality default; 16 is ~2× faster to generate | **Affects generation quality / compute, not speaking rate.** More steps = cleaner diffusion sampling, not faster speech. Do not raise `num_step` expecting a faster voice, and do not lower it expecting one either. The comparison notebook already used 32, the right default. A downstream wrapper's default is 48 with a 1–128 range (omnivoice-edu) — again, a quality/latency dial, not a prosody dial |
| **`language_id`** (`"arz"`, `"arb"`, …) / `language` | Language hint. `arz` = Egyptian Arabic (23.23 h in OmniVoice's training data); `arb` = Standard Arabic (1,483.53 h) | Affects **dialect and pronunciation**, not speed. `arz` is the right first try for Bahgat; if `arz` sounds unstable, `arb` is the fallback (more data, more Fusha-leaning). The comparison notebook already tries `arz` first with an `arb`/auto fallback. Language choice will not fix slowness |
| **`ref_text`** vs Whisper auto-transcribe | Transcript of the reference clip. If omitted, the model auto-transcribes with Whisper | Affects **alignment quality**, not speed directly — but a wrong auto-transcript (Whisper on fast, profanity-heavy Egyptian dialect is heavily garbled — see `docs/voice-training-report.md` §3) misaligns the reference, which can make the clone's prosody wander. Supplying a **hand-checked** `ref_text` is cheap and removes one variable. The comparison notebook already supports this (reads `training/transcripts/xtts_reference.txt` if present) |
| **Reference clip choice** | 3–10 s of the target speaker; the model conditions timbre *and* style on it (§(a)) | **The biggest prosody lever in OmniVoice, after `speed`.** A calm/slow reference yields calm/slow output; a fast, loud, shouting reference yields faster, more aggressive output. The comparison used one reference clip (the 7.16 s XTTS reference). Re-running with 2–3 different references — one calm, one fast/shouting, one mid — on the *same* sentence is the cheapest informative experiment in the whole project |
| **`instruct`** (voice design mode) | Text attributes: gender, age, pitch, accent, dialect, whisper | Only for voice-*design* mode (no reference audio), not voice *cloning* mode. The documented attributes include pitch and dialect, but there is **no documented "angry / fast / shouting" style attribute**, and Chinese dialects / English accents are the only dialect examples given. Do not expect `instruct` to add Bahgat's aggression to a clone |
| **Non-verbal tags in text** | `[laughter]`, `[sigh]`, `[surprise-ah]`, `[question-en]`, etc., inline in the input text | Can add a laugh / sigh / surprised interjection, which helps a *bot* feel less flat. The tag list is English-centric (`[question-en]`, `[surprise-oh]`…); whether they trigger naturally on Arabic text is unverified. Worth one test, not a strategy |
| **`seed`** | Reproducibility; in auto-voice mode fixes which voice is chosen | Useful for A/B comparisons (same seed, different `speed`), not a style control |
| `guidance_scale`, `t_shift`, `position_temperature`, `class_temperature`, `denoise`, `postprocess_output` | Lower-level diffusion / post-processing controls (documented in `docs/generation-parameters.md` and in the `omnivoice-tts-inference` PyPI docs: defaults `guidance_scale` 2.0, `t_shift` 0.1, `position_temperature` 5.0, `denoise` True, `postprocess_output` True — the latter "shortens pauses longer than 1 s to 1 s and trims leading/trailing silence to 100 ms") | **No source found** linking any of these to speaking speed or style in a controllable way. `postprocess_output`'s pause-shortening is mildly relevant (it trims long pauses, which could *help* a slow feel) but it is a default-on cleanup, not a dial to tune for style. Leave them at defaults |

### What the comparison run actually used — and what it did not test

From `training/colab/bahgat_zeroshot_omnivoice_vs_xtts.ipynb` (read
2026-11-26): the OmniVoice call was

```python
gen_kwargs = dict(text=TEST_SENTENCE, ref_audio=REF_WAV, num_step=32)
# + ref_text if a transcript file was present
audio = model.generate(language_id='arz', **gen_kwargs)
```

So the "slow / mediocre style" verdict was produced with **`speed` unset
(= 1.0 default), one reference clip, `num_step=32`, `language_id='arz'`**.
The two knobs most likely to change the verdict — `speed` and reference
clip choice — were never varied. That does not invalidate the verdict
(the timbre judgement stands), but it means **OmniVoice's style has not
actually been tested yet** — only its default-speed, single-reference
behaviour has. Before concluding OmniVoice cannot do Bahgat's style, run
the 3 × 3 grid: `speed` ∈ {1.0, 1.2, 1.35} × reference ∈ {calm, fast/
shouting, mid}, same sentence, same `language_id='arz'`, same seed, and
score speed/style by ear. That is nine generations on a T4, a few minutes
of work.

### What I could not find (honest gaps)

- **No OmniVoice-specific "style / emotion / anger" parameter** in the
  upstream README, the generation-parameters doc as summarised by
  downstream mirrors, or the skill references checked. The model's
  prosody control surface is, as far as the public docs show: `speed`,
  `duration`, reference clip, language, and the non-verbal tags. If a
  finer style control exists, it is not in the documented `generate()`
  API.
- **No published guidance on how `speed` interacts with cloning
  quality** (e.g. whether >1.3 degrades timbre similarity or only
  intelligibility). The AMD Radeon Cloud docs for hosted OmniVoice list
  `speed` 0.25–4.0 as a plain range with no quality warning; treat the
  upper end with suspicion until heard.
- **VoiceStudio's own app layer** (the Electron app + FastAPI backend)
  applies a mastering chain (high-pass + compressor) on top of the model
  output, per the project's VoiceStudio evaluation — that affects
  *polish/loudness*, not speed or style, and the comparison notebook
  deliberately tests the raw upstream model, so the app layer is out of
  scope for the style question.
- **No evidence that `num_step` changes prosody.** Any claim that "more
  diffusion steps = more expressive" would be speculation; the docs
  describe it purely as a quality/speed trade-off.

### Sources — (f)

- Hugging Face, `k2-fsa/OmniVoice` (mirror `Bgeorge/OmniVoice`), model card
  incl. Generation Parameters (`num_step=32`, `speed=1.0`, `duration=10.0`),
  accessed 2026-11-26 — https://huggingface.co/Bgeorge/OmniVoice
  (upstream: https://github.com/k2-fsa/OmniVoice ; paper
  arXiv:2604.00688, Zhu et al., 2026)
- HuggingFace skills, "OmniVoice — Omnilingual Zero-Shot TTS" (SKILL.md),
  accessed 2026-11-26 —
  https://github.com/luckyegg168/huggingface-skills/blob/HEAD/omnivoice/SKILL.md
- AgentArea, "omnivoice-tts" skill (generation parameters, JSONL fields),
  accessed 2026-11-26 —
  https://agentarea.ai/skills/reason-machines-trending-skills-skills-omnivoice-tts/
- omnivoice-edu (aparsoft), OmniVoice TTS server README (`num_step`
  default 48, `speed` 1.0, "rates below 1.0 can clip the first word",
  `duration` overrides `speed`), accessed 2026-11-26 —
  https://github.com/aparsoft/omnivoice-edu
- AMD Radeon Cloud Docs, "OmniVoice" (`speed` 0.25–4.0, `num_step` 1–64,
  `duration`, `seed`), accessed 2026-11-26 —
  https://amd-aim.github.io/radeon-cloud-docs/models/omnivoice/
- PyPI, `omnivoice-tts-inference` (generation-config defaults incl.
  `postprocess_output` pause-trimming), accessed 2026-11-26 —
  https://pypi.org/project/omnivoice-tts-inference/
- Project source: `training/colab/bahgat_zeroshot_omnivoice_vs_xtts.ipynb`
  (§3: `num_step=32`, `language_id='arz'`, no `speed` argument);
  `training/colab/voicestudio_evaluation.md` (§(f) language table:
  `arz` 23.23 h, `arb` 1,483.53 h).

---

## Bottom line for this project

1. **The slow/mediocre style is a source problem, not a timbre problem —
   and not a "more RVC training" problem.** RVC keeps the donor
   performance's timing, pauses and emphasis. The current source is
   Shakir at `rate="+5%"` — essentially his calm default. Fix the source
   first: ladder Edge TTS rate (+15% → +25% → +35%) on real bot lines,
   vary it by mood (angry faster/louder), and shape rhythm with short
   sentences, `!`, and `<break>` placement. Expect the answer near
   +20–30%, not +5%.
2. **22.54 min is enough; 30 min is the right stopping point.** The set
   is inside every guide's sweet spot (10–30 min; 15–20 min recommended).
   Grow it to ~30 min only with *diverse* minutes — fast, shouting,
   angry Bahgat, short interjections, questions — from the raw files
   already on disk, cleaned to the same solo-speaker bar. Beyond 30 min
   the guides unanimously say returns flatten; do not chase 60 min.
3. **Audit the dataset's register mix before adding minutes.** If the
   22.54 min is mostly measured debate, the RVC index will be good at
   measured debate and weak at shouting — which is the bot's main
   register. Count (or at least eyeball) the share of fast/loud/angry
   clips; if it is small, the next cleaning pass should deliberately
   favour those passages.
4. **Keep the planned RVC hyperparameters: v2, 40 kHz, RMVPE, batch 4,
   150 epochs, save every 10.** All are inside the community consensus,
   and 40 kHz is forced anyway by the T4 (48 kHz needs ~24 GB) and by the
   16 kHz sources. The one judgement call is epochs: 150 is the low end
   of the 150–300 band — mitigate by listening to checkpoints (100/120/
   150, then 180–200 only if 150 sounds undertrained), and roll back at
   the first robotic/metallic sign rather than pushing to 300+.
5. **At inference, start at index rate 0.5–0.75, protect 0.33, filter
   radius 3, RMS mix 0.25, transpose 0 — and change one dial per test.**
   Lower index rate first for metallic/gritty artefacts; lower protect
   slightly for mushy s/t; keep RMS mix low so shouts stay shouts and
   whispers stay whispers. None of these dials changes speed — do not
   tune them looking for speed.
6. **OmniVoice has not actually been tested for style yet.** Its
   "slow" verdict came from a single run at default `speed=1.0` with one
   reference clip. Before writing it off, run the 3 × 3 grid
   (`speed` 1.0 / 1.2 / 1.35 × calm / shouting / mid reference, `arz`,
   same sentence). `speed` is OmniVoice's direct fix for slowness, and
   reference-clip choice is its style lever. If that grid still sounds
   mediocre, OmniVoice is out on style grounds with evidence, not on a
   default-settings verdict.
7. **GPT-SoVITS is the only path in this stack that can *learn*
   Bahgat's prosody from text — but Arabic is unverified.** It predicts
   duration/prosody tokens during fine-tuning, which RVC structurally
   cannot do. Keep it as the fallback experiment (it needs the same
   22.54 min set), judge it by ear on Arabic, and do not assume its
   Chinese/Japanese prosody results transfer to Egyptian dialect.
8. **What no tool in this stack can fix:** a flat source performance
   (RVC and OmniVoice both inherit it), a monotone training set (no model
   invents a register it never heard), or a missing consent question
   (the voice belongs to a real living person — the parody labelling is a
   mitigation, not consent; see `docs/voice-training-report.md` §5).
   The honest ceiling is: *Bahgat's timbre, speaking the rhythm you feed
   it, in the registers you trained it on.* Everything in this document
   is about getting the input side of that sentence right.

---

## All sources (accessed 2026-11-26 unless a publication date is given)

- Apatero — RVC Training Dataset Preparation 2026, publ. 2026-02-18 —
  https://apatero.com/blog/rvc-training-dataset-preparation-tips-2026
- Apatero — AI Voice Cloning Open Source Guide 2026 —
  https://www.apatero.com/blog/ai-voice-cloning-open-source-guide-2026
- NiceVois — RVC Dataset Preparation: How Much Audio? —
  https://nicevois.com/guides/rvc-dataset-preparation
- The Vocal Market — How Much Vocal Data Do You Need to Train a Singing
  Voice Model —
  https://thevocalmarket.com/blogs/enterprise/how-much-vocal-data-to-train-voice-model
- Kenneth Lamar — A Guide to Voice Clones —
  https://kennethmlamar.com/posts/voice-clones-guide/
- VoiceChanger.live / Echo — How to Train Your Own RVC Voice Model —
  https://voicechanger.live/hub/how-to-train-rvc-model
- PropelRC — RVC WebUI Voice Conversion Guide —
  https://www.propelrc.com/rvc-webui-voice-conversion/
- SpeechData.ai — The Data Behind Voice Cloning —
  https://www.speechdata.ai/blog/voice-cloning-training-data
- Mimicore — RVC Voice Training for Beginners —
  https://mimicore.app/rvc-for-beginners/
- 101 AI Tools — Fish Audio voice cloning guide —
  https://101aitools.com/guides/fish-audio-voice-cloning-how-to-get-clean-ethical-results
- Eachlabs — RVC v2: Build Your Own RVC Model and Dial In the Settings,
  publ. 2026-11-09 — https://www.eachlabs.ai/blog/rvc-v2-build-your-own-rvc-model
- Xport Studio — Best RVC Settings: Pitch, Index Rate, Protect Explained,
  2026-10-24 — https://xportstudio.com/blog/best-rvc-settings
- HAWX Tech — Train a Local RVC Voice Model with Clean Audio —
  https://www.hawxtech.net/train-a-local-rvc-voice-model-with-clean-audio-samples.html
- Nivant Labs — RVC: Retrieval-based Voice Conversion —
  https://nivantlabs.com/blog/ai-tools-rvc/
- Applio studio production guide —
  https://github.com/froggeric/applio-macos-native-app/blob/HEAD/STUDIO_PRODUCTION_GUIDE.md
- ChangeLyric — How To Make an AI Voice Model That Actually Sounds Good,
  updated 2026-04-17 — https://changelyric.com/blog/ai-voice-model-guide
- NexGPU — RVC VRAM Requirements — https://nexgpu.net/en/models/rvc/
- Mojo Audio — RVC Model Sample Rate Distribution in the Wild, 2026-03-20 —
  https://github.com/itsdevcoffee/mojo-audio/blob/HEAD/docs/research/03-20-2026-rvc-sample-rate-distribution.md
- Ultimate RVC (PyPI) — parameter reference —
  https://pypi.org/project/ultimate-rvc/0.1.19/
- RVC fork CLAUDE.md — CLI inference parameters —
  https://github.com/dinhnguyen2210/retrieval-based-voice-conversion-webui/blob/HEAD/CLAUDE.md
- MattModeCode — Phase-0 research matrix — voice-clone backends, 2026-07-17 —
  https://github.com/mattmodecode/double-chin/blob/HEAD/.goal/research/matrix.md
- Wty2003328 — GPT-SoVITS v4 (LoRA fine-tune), voice-cloning-guide —
  https://github.com/wty2003328/voice-cloning-guide/blob/HEAD/docs/models/gpt-sovits-v4.md
- DeepWiki — GSV-TTS-Lite (timbre/style decoupling) —
  https://deepwiki.com/chinokikiss/GSV-TTS-Lite/1-overview
- DeepWiki — Voice Cloning Guide (Chatterbox) —
  https://deepwiki.com/gokhaneraslan/chatterbox-finetuning/6.2-voice-cloning-guide
- Hugging Face — software-mansion/Reverb-TTS —
  https://huggingface.co/software-mansion/Reverb-TTS
- Microsoft Learn — SSML document structure and events —
  https://learn.microsoft.com/hr-hr/azure/ai-services/speech-service/speech-synthesis-markup-structure
- Microsoft Q&A — How to change speech speed (rate) —
  https://learn.microsoft.com/en-us/answers/questions/5723830/how-to-change-speech-speed-rate-when-use-input-tex
- Edge-TTS-Compatible README —
  https://github.com/joey-kot/edge-tts-compatible/blob/HEAD/README.md
- Hugging Face — k2-fsa/OmniVoice (mirror Bgeorge/OmniVoice) —
  https://huggingface.co/Bgeorge/OmniVoice
  (upstream https://github.com/k2-fsa/OmniVoice ; paper arXiv:2604.00688,
  Zhu et al., 2026)
- HuggingFace skills — OmniVoice SKILL.md —
  https://github.com/luckyegg168/huggingface-skills/blob/HEAD/omnivoice/SKILL.md
- AgentArea — omnivoice-tts skill —
  https://agentarea.ai/skills/reason-machines-trending-skills-skills-omnivoice-tts/
- omnivoice-edu (aparsoft) — OmniVoice TTS server —
  https://github.com/aparsoft/omnivoice-edu
- AMD Radeon Cloud Docs — OmniVoice —
  https://amd-aim.github.io/radeon-cloud-docs/models/omnivoice/
- PyPI — omnivoice-tts-inference —
  https://pypi.org/project/omnivoice-tts-inference/
