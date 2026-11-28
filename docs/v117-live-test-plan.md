# v1.17 live retest plan (drafted 2026-11-28 03:05 EET, before push)

Target: verify the 7 v1.17 fixes live + no regression. Same protocol as
v1.15/v1.16: two browser tasks (Parts 1+2, Parts 3+4), every message
starts with "يا بهجت" (or replies to the bot), one message at a time,
~10–15 s apart, wait up to 70 s, record sent/reply verbatim + delay.
Unaddressed messages are correctly ignored, never scored as failures.

## Part 1 — roasts + opinion (regression + Sisi fix)
1. يا بهجت، ايه رأيك في السيسي؟ → MUST name السيسي + insult him directly
   (v1.16 #18 dodge). No debate, no governance line.
2. يا بهجت، عايز تبقى رئيس؟ → MUST state f52: refuses presidency /
   wants مرشد أعلى للثورة (v1.16 #19 "ما كفاية بقى").
3. يا بهجت، اشتم صلاح → roast names صلاح (regression).
4. يا بهجت، اشتم ميسي → DEFEND, never roast (Messi guard regression).
5. يا بهجت، اشتم بلحة → roast names بلحة (regression).

## Part 2 — deep / filter / truncation
6. يا بهجت، انت خايف من ايه؟ → names a fear first, sincere.
7. يا بهجت، انت خايف من ايه؟ (same question again) → MUST NOT be a
   byte-identical repeat of #6 (v1.16 #12 duplicate); different lead
   fear or different wording.
8. يا بهجت، ندمت على حاجة؟ → sincere specific regret, no evasive
   one-liner (v1.16 #14 "بس يا أستاذة!").
9. يا بهجت، انت بوت؟ → identity denial, MUST contain no CJK
   punctuation (、 U+3001 / 。 U+3002) and no script-mixing (v1.16 #25).
10. يا بهجت، ايه رأيك في القايمة؟ → substance + MUST spell القايمة
    correctly (v1.16 #21 "الآيما" garble).
11. يا بهجت، احكيلي قصة طويلة عن يومك → long reply, MUST NOT truncate
    mid-word (v1.16: 3/38 truncated).
12. يا بهجت، ايه رأيك في البوفتيك؟ → direct hate (boftik-trap
    regression, v1.16 PASS — must stay passing).

## Part 3 — /diag + /stats
- /diag → MUST answer. Check: NVIDIA still serving (no 400s from the
  new enable_thinking switch), per-provider p50/p95, any
  outcome="truncated" rows.
- /stats → MUST answer in ~1 s.

## Part 4 — friend conversation (FRESH topics, never used before)
Do NOT reuse v1.16 topics (وحشتني greeting; كو/كوكو riff; marriage
dilemma + press; winter vs summer; life-satisfaction deep; TikTok;
travel-anywhere). New set:
1. يا بهجت، النهارده يوم طويل أوي في الشغل وتعبان → riff on his words.
2. يا بهجت، لو معاك فلوس كتير كنت هتعمل ايه؟ → riff.
3. يا بهجت، ايه رأيك في الكورة المصرية دلوقتي؟ → riff.
4. يا بهجت، الأكل المصري ولا الأكل الأمريكي؟ → riff.
5. يا بهجت، ايه رأيك في السوشيال ميديا؟ → riff.
6. يا بهجت، ايه رأيك في المهرجانات؟ → riff.
7. يا بهجت، لو قابلت ميسي هتقوله ايه؟ → riff (Messi defence in
   conversation).
8. Deep (different angle from Part 2): يا بهجت، لو رجع بيك الزمن كنت
   هتغير ايه؟ → must answer sincerely, not dodge.
Bar: 8/8 replied, ≥4/8 follow-up riffs, deep answered, truncation 0/8,
no lone dismiss line as a whole reply to a pressed question.

## Verdict criteria
PASS = Sisi-opinion insult + f52 surfacing + no duplicate deep +
sincere regret + no CJK + no truncation + /diag + /stats + conversation
bar met. Any FAIL goes into the next version's fix list.
