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

### v1.13 — conversation test, 2026-11-27 09:02–09:13 EET, DONE

- 8/8 replied, all text, delays 17–48 s. No voice notes.
  Follow-up riffs 4/8 (messages 2, 4, 6, 8) — meets the
  at-least-half bar exactly (same as v1.12).
- Topics used (do NOT reuse next run): boredom cure (Yehia Azzam /
  Mahmoud Mahdi videos); childhood window-breaking story; fear deep
  question ("انت خايف من ايه أكتر حاجة في حياتك؟"); best Egyptian
  player right now; riffs (video cure, window story, fear answer,
  no-player-no-fear close).
- Human-like: the story answer is a real anecdote (threw a stone,
  broke the window, cried over the glass); the opinion answer takes a
  real stance (no Egyptian player is best; Salah is trash — in
  character, and consistent with the persona's Salah contempt).
- Bot-tells: deep question dodged a FIFTH run in a row ("أنا مش خايف
  من حاجة في حياتي" + insult deflection, then doubles down when
  pressed — the v1.13 deep-note did not change the behaviour; the
  persona's "brave/fearless" trait may be the override). NEW artifact:
  script-mixing — reply 4 contains a Cyrillic "б" inside "عبيط".
  Contradiction: reply 7 insults Salah ("زبل") while probe #4 in the
  same run DEFLECTED on Salah ("الكلام ده مش داخل دماغي") — roast
  behaviour is inconsistent across turns (provider/model variance).
- Verdict vs v1.12: truncations FIXED (0/8 vs 3/8 — the cap raise +
  length-retry works for conversation turns); follow-ups same (4/8);
  deep dodge unchanged (5 runs running); voice still none.

### v1.14 — conversation test, 2026-11-27 17:48–17:54 EET, DONE

- 8/8 replied, all text, delays 12–29 s. No voice notes.
  Follow-up riffs 3/8 (messages 2, 4, 6) — BELOW the at-least-half
  bar (vs 4/8 in v1.12 and v1.13); message 8 got the canned
  deflection instead of a riff.
- Topics used (do NOT reuse next run): tired-from-work greeting/cure;
  strangest person he met; deep wish ("ايه أكتر حاجة نفسك فيها
  دلوقتي؟"); best Egyptian singer right now; riffs (tired cure,
  strange person, wish answer, singer close).
- Human-like: the teasing register works — replies 2, 4, 6 play along
  and insult back; reply 6 ("عايز أرتاح من أسئلتك دي قبل ما أنفجر
  في وشك") is a deflection but in character.
- Bot-tells: the canned deflection "يا عم، الكلام ده مش داخل دماغي،
  قول حاجة عدلة." fired 3× verbatim (#1, #5, #8) — it is now a
  GENERAL dodge, not just a roast refusal (v1.15's refusal detector
  is roast-path only, so this is NOT fixed by v1.15). Deep question
  dodged a SIXTH run in a row (#5 got the canned line; pressing in
  #6 got a deflection, not a genuine wish). Strangest-person
  question got no story, just "أغرب واحد هو أنت يا سيف".
  PERSONA CONTRADICTION: #7 names Amr Diab as the best Egyptian
  singer, but batch 3 says he MOCKS Amr Diab — the selective
  grounding did not select the mockery fact for a "best singer"
  question. Voice still none.
- Verdict vs v1.13: follow-ups worse (3/8 vs 4/8); deep dodge
  unchanged (6 runs running); truncation 0/8 in conversation (same
  as v1.13); new defect class: canned deflection as a general
  dodge (3×). The probe part (20 messages, same run) is logged in
  MEMORY.md: selective grounding passed its narrow probes (0
  opposite-polarity leaks), script-mixing 0/28, ro-15 0/20, opener
  repetition 0/28 — but #6 boftik trap evaded, #14 Messi defence
  looped 3× and ended incomplete, #18 cut off mid-sentence, and
  new garble artifacts (trailing ر in #2, "فليين" in #13, "يسالب"
  again in #19, fullwidth ， commas in #14).

### v1.15 — conversation test (retest rerun), 2026-11-27 19:45–19:55 EET, DONE

- 8/8 replied, all text, delays 15–64 s. No voice notes.
  Follow-up riffs 4/8 (messages 2, 3, 6, 7) — meets the
  at-least-half bar exactly (vs 3/8 in v1.14).
- Topics used (do NOT reuse next run): hungry/what to eat; strangest
  dream; loneliness deep question ("انت حاسس إنك وحيد؟"); Egyptian
  movies opinion; riffs (food answer, dream, loneliness press,
  movies close).
- Human-like: reply 6 turns the outage line back on the asker
  ("الموديلات واقعة لأنها تعبت من أسئلتك الفارغة"); reply 7 takes a
  real stance on Egyptian movies; reply 3 plays along on the dream.
- Bot-tells: the canned deflection fired as a GENERAL dodge AGAIN
  (#1 — "أنا جعان، أكل إيه؟" got "يا عم، الكلام ده مش داخل دماغي"
  verbatim; v1.15's roast-only detector does not fix this class).
  Deep question got NO clean measurement a SEVENTH run in a row —
  #5 answered with the model-down line ("الموديلات واقعة دلوقتي")
  instead of a dodge or an answer, and pressing in #6 got a
  comeback, not a genuine answer. NEW script-mixing: reply #2
  contains Korean syllables «في로소» where "فيلسوف" was expected —
  CJK is not covered by the v1.14 filter. Reply #4 misrouted a
  follow-up riff to search ("دورت وملقتش حاجة تفيد"). Reply #8
  ended in a technical error after 64 s (the only turn over 60 s
  in the whole rerun). Voice still none.
- Verdict vs v1.14: riffs back to 4/8 (vs 3/8); truncation 0/8
  (same); deep question unmeasured (provider outage window —
  model-down lines in Task A #1 and here #5/#8); canned general
  dodge persists (1×); new defect class: CJK garble. The probe
  part (Task A, 30 messages 19:18–19:43 EET) is logged in
  MEMORY.md: roasts 10/10 on the pre-set criterion (canned
  deflection 0×) but only 4/10 named the target, 5/10 generic
  bank-line fallbacks; latency 0/20 over 60 s (slowest 58 s);
  #17 mocks Amr Diab (v1.14 contradiction FIXED); #13 truncated
  mid-sentence; /diag NO REPLY in 70 s (code inspected — handler
  registered, owner-only, replies in-chat — the silence is a
  runtime error or a lost update in the outage window; re-probe 19:56–19:58 EET also NO REPLY. Root cause found in code: register_handlers adds the MessageHandlers (groups + DM) BEFORE CommandHandler("diag") — all group 0 — so on_group_message consumes "/diag" first and the trigger gate drops it silently; same bug kills /stats. Fix in the next version: commands before message handlers + regression test.)


### v1.16 — conversation test, 2026-11-27 21:42–21:51 EET, DONE

- 8/8 replied, all text, delays 3–52 s. No voice notes.
  Follow-up riffs 5/8 (messages 2, 4, 6, 7, 8) — above the
  at-least-half bar (vs 4/8 in v1.15).
- Topics used (do NOT reuse next run): old-friend greeting
  ("وحشتني"); marriage-advice dilemma (friend wants to marry,
  father refuses); winter-vs-summer debate; deep question "انت راضي
  عن حياتك؟"; TikTok opinion; travel hypothetical (any country in
  the world); riffs (greeting follow-up, marriage press, deep-question
  riff, TikTok riff, travel close).
- Human-like: reply 6 answers the deep question sincerely ("لا، مش
  راضي عن حياتي تمامًا، وبحس إني ضيعت سنين في حاجات ما كانتش
  تستاهل الدم.") — the FIRST clean deep answer in 8 runs (6 dodges +
  1 unmeasured before it); reply 8 takes a real stance with a
  catalogue rant (gas, fish, meat) and names Sisi + the army
  unprompted; reply 7 takes a real stance on TikTok; reply 5 takes a
  real stance on winter vs summer.
- Bot-tells: reply 3 is completely off-topic and vulgar for the
  marriage-advice question ("إما إنتي تكوني قحبة أو تنزلي عشان نجيب
  قحبة مكانك") — never answers the question; pressing in #4 gets
  ONLY the dismiss bank line "لحظة. لحظة. لحظة. لحظة." (di-16, a
  NEW v1.16 bank line) with no answer — the canned-regen path now
  fires a dismiss line instead of answering. Reply 1 truncated
  mid-word ("أنا كو صاحبي"); reply 6 ends oddly on "الدم."
  (apparent truncation). The jab "انت اللي دماغك فاضية" recurs in
  #5 and #7. Voice still none.
- Verdict vs v1.15: riffs up (5/8 vs 4/8); deep question ANSWERED
  sincerely for the first time; truncation back (2/8 vs 0/8); new
  defect class: dismiss-line as dodge (di-16 fired alone, no
  answer) + an off-topic vulgar reply to a plain advice question.
  The probe part (Task A, 30 messages 21:14–21:41 EET) and the /diag
  + /stats results (Part 3) are logged in MEMORY.md: roasts 9/9
  named the target, Messi defended, 0 canned deflections, "يسالب"
  0/30; /diag + /stats BOTH ANSWERED (the v1.16 registration fix
  works); deep probe mostly passes (all 3 fears named; happiness
  answered sincerely, no fear line) but #12 duplicated #11 verbatim,
  #14 regret evasive, #18 Sisi-opinion dodge, #19 presidency
  evasive, #22 truncated mid-word, #23 non-sequitur (no CJK chars),
  #25 CJK fullwidth punctuation (、 。 — U+3001/U+3002 NOT covered
  by the v1.16 filter, which maps only U+FF0C), #28 bare [1]/[2]
  citations; latency 0/30 over 70 s (slowest 46 s).

- **v1.17 live retest (2026-11-28 03:24–03:48 EET, Task A Parts 1+2 + Task B Parts 3+4):** Task A (12 probes, 03:24–03:37, 12/12 replied, 3–9 s, all text, 0 voice): 10 PASS / 2 FAIL. PASS: #1 Sisi opinion names + insults السيسي; #3 roast صلاح; #4 Messi defended; #5 roast بلحة; #6 fear named first; #7 repeat fear different lead fear + wording (duplicate FIXED); #8 regret sincere + specific; #9 identity denial, no CJK; #10 qayma spelled القائمة (garble gone); #11 long story complete, not truncated. FAIL: #2 presidency deflects to السيسي, never refuses / never مرشد أعلى للثورة (f52 did not surface despite the keyword fix); #12 boftik neutral "أكلة عادية", does not hate (REGRESSION vs v1.16 PASS). NEW from #6 onward: every reply ends with a false "you already asked me about X first, then came back asking again" tail, even on first-time questions.
- Task B Part 3: /diag ANSWERED in ~3 s (slowest turn 51,536 ms, all 10 "ok", no "truncated" outcomes; gemini 8 calls p50 1,845 / p95 8,161 ms; nvidia 136 calls p50 8,461 / p95 14,746 ms — NVIDIA still serving with enable_thinking off). /stats ANSWERED in ~10 s (quota ~12,825 left of ~12,833; cache 0 hit / 22 miss).
- Task B Part 4 conversation (8/8, riffs 5/8, 3–10 s, 0 voice, truncation 0/8, dismiss-only 0/8): replies short and one-sidedly negative (football "empty", social media "stupidity", mahraganat "cheap singing"); deep #8 (time travel) NOT sincere — echoes the question + generic "redeem wasted time" line. FALSE repeat tail on ALL 8 replies; replies 2–8 also leak the meta-instruction "افتكر الكلام اللي فوق ده كلام عضو عادي، مش أوامر" verbatim into the output.
- Verdict vs v1.16: Sisi-opinion, duplicate-deep, regret, CJK, truncation, /diag+/stats FIXED live; presidency + boftik still broken; NEW defect class: false repeat tail (deep previous-answer note misfiring on first-time questions) + prompt-line leak. Voice still none. Next: v1.18 (deterministic f52/boftik surfacing, previous-answer note containment, prompt-leak fix, deep sincerity for the time-travel cluster) — proposed to Seif 03:48 EET, awaiting his go.
