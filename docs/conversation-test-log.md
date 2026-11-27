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

- 4/8 replied within 60 s (delays 13–32 s); 4 no-reply within 60 s.
  BUT the 4 "missing" replies are not missing: each nudge's reply
  answers the ORIGINAL question (msg 3's reply answers msg 2's job
  question, msg 5's answers msg 4's football question, msg 7's
  answers msg 6's regret question), so the bot was replying
  ~100–113 s late (msg 2 → 113 s, msg 4 → 102 s, msg 6 → 101 s;
  msg 8's reply never observed — the run ended at 06:00). Not
  ignoring him; answering very slowly in conversation. v1.9 was
  8/8 at 9–25 s. Functional retest the same morning (05:39–05:45)
  had LLM replies at 8–18 s, so the slowness is not constant —
  suspect LLM provider slowness/retries, or v1.10's WARP processes
  / pod CPU. Needs diagnosis; the v1.11 retest re-measures it.
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
  a real answer); the ~100 s reply latency; no voice notes this
  run. No repeated reply twice, no truncation this run.
- Verdict vs v1.9: WORSE on responsiveness (4/8 in-window vs
  8/8), same on deep-question dodging; better on repeats and
  truncation. Next run (v1.11) must beat: replies within 60 s,
  answer the personal question for real.
