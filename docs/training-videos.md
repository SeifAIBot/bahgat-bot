# Training videos — Bahgat Saber

Split as Seif asked: (A) voice training, (B) style / jokes / traits training.
Source: public YouTube / TikTok / Telegram clips found by web search on 2026-11-25.
**Important: audio cleanliness has NOT been verified by listening yet.**
Before any RVC / GPT-SoVITS training, each clip must be downloaded, checked for
solo speech, no music, no street noise, no overlapping guests, and cut to clean segments.
Street / Times Square lives are noisy and are NOT suitable for voice training.

Main channel: https://youtube.com/@bahgatsaber11 — 247k subscribers, 494 videos (per fan post, Oct 2026).
Telegram clip library: https://t.me/s/bahgatsaber1?before=447 — many 6–21 min clips, useful for sampling.

## A. Voice training — cleanest solo audio (indoor, Bahgat leads)

1. حوار مع كارما — 28 min — https://www.youtube.com/watch?v=wjz_JxcJTiM
   - Main channel @bahgatsaber11. Bahgat leads the conversation. Best long indoor sample.
2. مناظرة مع شيخ — 20+ min, chapters — https://www.youtube.com/watch?v=-F3b9XGrrbs
   - Heated debate, fast replies, anger. Has a guest, so cut only Bahgat's turns.
3. بث بهجت صابر اليوم 6/11/2026 — https://www.youtube.com/watch?v=9cldVFbHJ5g
   - Recent live, clear voice. Check for guest overlap before use.
4. الحوار الأجرأ مع كوماندا — https://www.youtube.com/watch?v=mixpWS-TGm8
   - Main channel. Long dialogue, Bahgat dominant.
5. مداخلات مع لجان كيف يدير السيسي البلد — https://www.youtube.com/watch?v=MML3TRN72NQ
   - Call-ins, Bahgat mostly solo between calls. Good for varied intonation.

Voice plan: 10–20 min total clean audio is the target for RVC (10 min minimum per RVC docs).
GPT-SoVITS can start from ~1 min clean, but 5–10 min is far better. Zero-shot XTTS v2
needs only ~6 sec but will sound less like him, especially shouting / laughing.

## B. Style / jokes / traits — most famous, many clips

These are for text persona: catchphrases, timing, insults, reactions, humour.
Do NOT use noisy clips from this list for voice training without cleaning.

1. حوار جريئ بهجت صابر والكوماندا — compilation — https://www.youtube.com/watch?v=dBjN21s49vQ
   - Funniest call-ins, roasts, quick comebacks.
2. بهجت صابر يفحم ضيفاً مسيحياً — https://www.youtube.com/watch?v=qdOtUjTTLZs
   - Fierce confrontation, anger + dominance.
3. بهجت صابر ولينا وحوار ساخن — https://www.youtube.com/watch?v=Oli_neDUV_Y
   - Long interrogation style, teasing, provocation.
4. نقاش ساخن بين بهجت صابر وبنت لجنة — https://www.youtube.com/watch?v=y8UR7BHh0bo
   - Argument with an opponent, escalation.
5. حقيقة عمل لينا في شقق الدعارة: بهجت صابر — https://www.youtube.com/watch?v=solcRS6dsjs
   - Long live 30/10/2026, bold / no-filter talk.
6. بهجت صابر: قوم يا مصري — meme short — https://www.youtube.com/watch?v=qQgMC-yiQdI
   - Signature chant / catchphrase.
7. أقوى 20 دقيقة ضحك متواصل مداخلات نار — listed on sm3ha as 14,155 views, 9:30
   - No verified direct YouTube URL in search results — do not guess a URL, find it via the main channel / Telegram library.
8. اضحك مع شتايم بهجت صابر #10 — 47,054 views, 4:20 — same note as above.
9. ضحكة الموسم — 124,804 views, 34:34 — same note as above.
10. Telegram library (above) — dozens of short clips, best place to sample many different moods quickly.

## Do NOT use for training
- لحظة القبض على بهجت صابر — https://www.youtube.com/watch?v=yGYz7CrtFcw
  - Street, police, shouting, crowd noise. Useful only as an emotion reference (panic / anger), never for voice.
- Any clip where two people talk over each other, music plays, or the mic echoes.

## Next step (when Seif approves)
1. Download A1–A3, run Whisper transcription, split into Bahgat-only clean segments.
2. Build `persona/bahgat/examples.md` from B1–B6 transcripts (paraphrase style, do not copy long verbatim rants into the repo).
3. Test XTTS v2 zero-shot first (fast), then train RVC on the clean set if quality is insufficient.
