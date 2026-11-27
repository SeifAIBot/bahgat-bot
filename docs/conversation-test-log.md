# Friend Conversation Test — Log

Seif's rule (2026-11-27 05:07 EET): this is not a one-off chat. The friend
conversation test (insults, laughter, joking, one deep talk — like two
friends, never canned questions) runs after EVERY version, and every run is
compared with the previous one to see whether Bahgat is improving or not.

Protocol: `docs/live-test-matrix.md`, "Friend conversation test" section.
Scored per reply: tied to the person's words? canned or fresh? tone/speed
vary with mood? insults creative? deep talk coherent with a real stance?
never admits bot, never a banned AI phrase? voice when apt?

## v1.9 — baseline (run 2026-11-27 05:07–05:15 EET, DONE)

- 8/8 replied, no no-replies. Delays 9–25 s, varied. 1 voice note (8 s,
  message 6, million thread — repeats the text reply).
- Topics used (do NOT reuse next run): greeting as old friend; playful
  insult (slow brain); million-pound hypothetical; tea-vs-coffee debate;
  riffing on his words (kicked out, new brain, tea fixing the brain).
- Human-like: REAL memory/grudge — reply 1 referenced being called
  "يا حمار" earlier in the day ("كنت لسه شاتمني من شوية") and reply 8
  did again; million + tea answers tied to the question with a real
  stance ("الشاي طبعاً هو اللي بيعدل الدماغ").
- Bot-tells: replies 2 and 3 nearly identical ("انت بهزر وانا بجد يا
  سيف... امشي من هنا" twice in a row); reply 4 appears CUT OFF mid-word
  ("يا عم، الجروب مش جروحك ولا ج" — unverified whether it completed
  later); the friendship question in message 8 ("احنا صحاب بجد ولا انت
  مستحملني؟") was dodged, not answered.
- Bank match (checked against reply_bank.yaml): 0/8 user-submitted lines.
  7 replies pure LLM; reply 5 contains Bahgat bank line cp-04
  (verbatim). Expected: the conversation runs on the LLM path; user
  lines fire only on direct insult/roast triggers — that is what the
  focused probe measures (running after this run).
- Verdict (baseline — nothing to compare yet): sounds like a friend with
  a grudge and opinions, but repeats himself and dodges the personal
  question. Next run (v1.10) must beat: no repeated reply twice, no
  truncation, answer the personal question.

## v1.10 (WARP) — run 2026-11-27 05:49–06:00 EET, DONE

- 4/8 replied (delays 13–32 s); 4 no-reply. CORRECTION
  (2026-11-27 06:54 EET): this was NOT a latency regression —
  messages 2, 4, 6, 8 contained NO "يا بهجت", so the bot
  correctly ignored them per its trigger rules (reply only on
  mention, "بهجت", or reply-to-bot). Messages 1, 3, 5, 7 — all
  with "يا بهجت" — replied in 13–32 s. The earlier "~100 s
  late" reading was wrong: the nudges repeated the question
  WITH the trigger word, and the bot answered the nudge
  promptly. So: 4/4 addressed messages replied, 4/4
  unaddressed correctly ignored. No slowness.
- Topics used (do NOT reuse next run): weekend-plan greeting;
  quit-the-job advice dilemma; الأهلي vs الزمالك debate; regret
  deep question; private-jet hypothetical; riffs (leave the job,
  football take, regret answer).
- Human-like: grudge again — reply 1 ("جاي تسألني عامل إيه بعد
  ما شتمتني؟"); real stances (Ahly fan: "أنا أهلاوي يا معفن،
  والزمالك خربان زي دماغك"); advice with a stance ("خليه يكبس
  على نفسه ويحمد ربنا إنه بيقبض قرشين").
- Bot-tells: deep question dodged AGAIN (regret → "أكتر حاجة
  ندمت عليها إني بصيت في وشك أصلاً" — deflection by insult, not
  a real answer); no voice notes this run. No repeated reply
  twice, no truncation this run. No latency issue (see the
  correction above).
- Verdict vs v1.9: same on responsiveness for addressed messages
  (4/4, 13–32 s vs 8/8, 9–25 s), same on deep-question dodging;
  better on repeats and truncation. Next run (v1.11) must beat:
  answer the personal question for real — and every test message
  must contain "يا بهجت" (protocol fix, see below).

## v1.11 (bank lines as ingredients) — run 2026-11-27 06:37–06:50 EET, DONE

- 1/6 replied within 120 s (message 1, 9 s); 5 no-replies.
  CORRECTION (2026-11-27 06:54 EET): this was NOT a silence
  regression — only message 1 contained "يا بهجت"; messages 2–6
  did not, so the bot correctly ignored them per its trigger
  rules. 1/1 addressed replied in 9 s. The live probe right
  after ("يا بهجت عامل ايه") replied in 16 s, and Cloady showed
  Running with no crash evidence. The bot was never down. TEST
  ERROR, not a bot error: the follow-up riffs dropped the
  trigger word.
- Topics used (do NOT reuse next run): day/lunch greeting;
  childhood funny story; sea vs mountains; fear of the future;
  koshari riff; sudden-fame hypothetical.
- Verdict vs v1.10: no comparison possible — the run was
  invalid (test error). The v1.11 conversation behavior is
  unmeasured; the corrected re-run (every message with
  "يا بهجت") is the valid measurement. PROTOCOL FIX (standing):
  every conversation-test message MUST contain "يا بهجت" or be a
  reply to the bot's message — added to
  docs/live-test-matrix.md.

### v1.11 — CORRECTED re-run, 2026-11-27 06:57–07:03 EET, DONE

- 8/8 replied, all text, delays 6–28 s. No no-replies, no voice
  notes. This is the valid v1.11 measurement (replaces the
  invalid 06:37 run above).
- Topics used (do NOT reuse next run): morning greeting; birthday
  gift advice dilemma; cats vs dogs debate; peace/happiness deep
  question; perfect-Friday planning; riffs on his words (gift,
  cats, peace).
- Human-like: answers tied to his words (gift advice with a
  stance, dogs loyal / cats treacherous, "راحة البال إني مش شايف
  وشك"); consistent insulting-friend tone; no repeated reply,
  no truncation.
- Bot-tells: deep question dodged a THIRD run in a row
  (peace/happiness → "ابعد عن أشكالكم الزفت... اقفل بقك" —
  deflection by insult, not a real answer); reply 3 slightly
  misreads the question ("تعتذرلي أنا؟" — he asked about
  apologising to his friend, not to the bot); reply 5 repeats a
  phrase inside itself ("عشان الخيانة طالعة منك" twice). Only
  3/8 messages were explicit follow-up riffs (below the
  at-least-half target).
- Verdict vs v1.9 baseline: same responsiveness (8/8, 6–28 s vs
  8/8, 9–25 s), same deep-question dodging (now 3 runs running);
  better on repeats/truncation; worse on voice (none this run
  vs 1 in v1.9). The deep-question dodge is now a persistent
  defect — fix candidate: answer personal/deep questions for
  real instead of deflecting by insult.

### v1.12 — conversation test, 2026-11-27 07:37–07:46 EET, DONE

- 8/8 replied, all text, delays 10–29 s. No voice notes.
  Follow-up riffs 4/8 (messages 3, 6, 7, 8) — meets the
  at-least-half bar exactly (vs 3/8 in v1.11).
- Topics used (do NOT reuse next run): favorite song right now;
  fight-with-a-friend advice dilemma; Yehia Azzam video gossip;
  happiness deep question ("انت حاسس إنك مبسوط في حياتك ولا
  ناقصك حاجة؟"); prank planning; riffs on his words (béchamel
  prank, salt, fake iPhone).
- Human-like: Yehia Azzam gossip engaged properly ("راجل محترم
  ودمه خفيف وبيفهم"); prank ideas are real and in character
  (extra-salty béchamel, fake iPhone); reply 8 finished the
  cut-off sentence from reply 7 when asked to continue.
- Bot-tells: deep question dodged a FOURTH run in a row (insult
  deflection + cut off mid-word "قد"); TRUNCATION SEVERE —
  3/8 replies cut off (#2 ends "ليل ن", #4 ends "قد", #7 is
  ONLY "يا حمار يا سيف،"); dodges 3/8 (#1 named no song, #2
  no advice, #4 deep question); opener repetition 6/8 open
  with identical "يا حمار يا سيف،" (word order flipped from
  the matrix run's "يا سيف يا حمار").
- Verdict vs v1.11: better on follow-ups (4/8 vs 3/8), same on
  voice (none); WORSE on the two things that matter most
  (deep-question dodge now 4 runs running; truncation 3/8 vs
  0/8 in v1.11's corrected run). Truncation is now the top
  v1.13 defect. Suspect (unverified, logs trapped on Cloady):
  reasoning tokens eating the 1500-token completion budget
  (GPT-OSS/Gemini reasoning counts against
  max_completion_tokens) — visible replies are only 4–20
  tokens. Fix: raise the cap for reasoning families +
  treat finish_reason=length as retry/continue, never send
  a truncated draft as-is.
