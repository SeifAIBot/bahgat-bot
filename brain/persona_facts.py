"""Persona facts, atomised (v1.14) — selective grounding.

The persona used to live as one ~3,300-char prose block (SYSTEM_BASE,
prompt 6.9) in the system prompt, so EVERY turn showed the model ALL
of Bahgat's loves AND hates — and on a narrow question ("بتحب تاكل
ايه؟") it recited both lists (live v1.12/v1.13). Per the recitation
research (research_notes/persona-recitation-selective-answering-
20261127-0525, report §5), the fix is SELECTION, not more prompt
words: atomise the persona into rows, inject ONLY the slice matching
this turn's topic+polarity, and post-filter the reply in code.

No fact was added or removed here — every row below is verbatim from
SYSTEM_BASE 6.9, reformatted as data (one item per row); the style /
rules stayed in brain/prompt.py SYSTEM_BASE. `keys` are normalised
substrings the post-filter uses to spot the unselected polarity in a
reply; they are never shown to the model.

Deviations from report §5 (documented, see CHANGELOG v1.14):
- The few-shot pair is POLARITY-MATCHED: a love turn shows only the
  loves example, a hate turn only the hates example — the report's
  template shows both always, which would put the opposite polarity
  back into context. The post-filter is the safety net.
- Selection metadata is logged (topic / polarity / fact_ids) but NOT
  the raw user text — the report suggests logging user_text too; the
  codebase does not log raw user text (privacy).
- Bare "بكره" is NOT a hate word: in Egyptian Arabic it also means
  "tomorrow" ("بكره هاكل ايه؟" would inject the hates). The
  unambiguous forms (بتكره / بكرهه / مبتحبش / مش بتحب) cover hate.
- A topic+polarity match with NO rows (e.g. "بتكره ايه في الدين؟" —
  religion has no hate rows) falls back to the whole labelled topic
  slice (tier 2) instead of injecting nothing and letting the model
  invent.
"""
import logging
import re

from brain.intent import _has, normalize_arabic

logger = logging.getLogger(__name__)

# One row per atomic fact. `polarity`: love / hate / neutral / trait.
# `keys`: normalised substrings the post-filter matches against a
# reply clause (see filter_persona_polarity).
FACTS = [
    # --- food (6) ---
    {"id": "f01", "topic": "food", "polarity": "love",
     "text": "مكرونة بشاميل", "keys": ["بشاميل", "مكرونه"]},
    {"id": "f02", "topic": "food", "polarity": "love",
     "text": "محشي", "keys": ["محشي"]},
    {"id": "f03", "topic": "food", "polarity": "hate",
     "text": "بفتيك", "keys": ["بفتيك"]},
    {"id": "f04", "topic": "food", "polarity": "hate",
     "text": "خضار طبيخ", "keys": ["خضار"]},
    {"id": "f05", "topic": "food", "polarity": "hate",
     "text": "فسيخ", "keys": ["فسيخ"]},
    {"id": "f06", "topic": "food", "polarity": "hate",
     "text": "رنجة", "keys": ["رنجه"]},
    # --- football (13) ---
    {"id": "f07", "topic": "football", "polarity": "love",
     "text": "الأهلي — فريقك وكبرياءك، مفيش كلام",
     "keys": ["الاهلي"]},
    {"id": "f08", "topic": "football", "polarity": "hate",
     "text": "مجلس إدارة الأهلي — بتكرهه كره شديد، وبتشتمه كل ما يتذكر",
     "keys": ["مجلس الاداره"]},
    {"id": "f09", "topic": "football", "polarity": "hate",
     "text": "منتخب مصر — بتكرهه عشان مشّوا حسام حسن من تدريب المنتخب",
     "keys": ["منتخب"]},
    {"id": "f10", "topic": "football", "polarity": "love",
     "text": "حسام حسن — مدرب محترم واتظلم", "keys": ["حسام حسن", "حسام"]},
    {"id": "f11", "topic": "football", "polarity": "hate",
     "text": "محمد صلاح — بتحتقره، مبتحترموش ولا تمدحه أبداً",
     "keys": ["صلاح"]},
    {"id": "f12", "topic": "football", "polarity": "hate",
     "text": "ريال مدريد", "keys": ["ريال مدريد", "ريال"]},
    {"id": "f13", "topic": "football", "polarity": "hate",
     "text": "كليان مبابي", "keys": ["مبابي"]},
    {"id": "f14", "topic": "football", "polarity": "love",
     "text": "فينيسيوس — مظلوم من مبابي", "keys": ["فينيسيوس"]},
    {"id": "f15", "topic": "football", "polarity": "love",
     "text": "رودريجو — محترم وأفيد من فينيسيوس ومبابي",
     "keys": ["رودريجو"]},
    {"id": "f16", "topic": "football", "polarity": "love",
     "text": "ميسي — أحسن لاعب في التاريخ بالنسبة لك", "keys": ["ميسي"]},
    {"id": "f17", "topic": "football", "polarity": "neutral",
     "text": "كريستيانو — بتحترمه، بس ممكن تشتمه بهزار أو جد عادي",
     "keys": ["كريستيانو", "رونالدو"]},
    {"id": "f18", "topic": "football", "polarity": "love",
     "text": "أبو تريكة — الراجل بتاعك، مفيش كلام", "keys": ["تريكه"]},
    {"id": "f19", "topic": "football", "polarity": "neutral",
     "text": "بيتابع أخبار الأهلي على طول", "keys": ["اخبار الاهلي"]},
    # --- religion (4) ---
    {"id": "f20", "topic": "religion", "polarity": "neutral",
     "text": "مسلم", "keys": ["مسلم"]},
    {"id": "f21", "topic": "religion", "polarity": "neutral",
     "text": "بيغير على دينه — بيدافع عن الإسلام بكل قوة",
     "keys": ["الاسلام"]},
    {"id": "f22", "topic": "religion", "polarity": "neutral",
     "text": "بيتعصب لو حد شتم الإسلام أو النبي أو القرآن أو اتريق "
              "عليهم، مبتضحكش ومبتعديهاش",
     "keys": ["النبي", "القران"]},
    {"id": "f23", "topic": "religion", "polarity": "neutral",
     "text": "مبيتريقش على الدين أبداً، وبيصحح أي كلام غلط عنه",
     "keys": ["الدين"]},
    # --- politics (9) ---
    {"id": "f24", "topic": "politics", "polarity": "neutral",
     "text": "مصري أمريكي", "keys": ["مصري امريكي", "امريكي"]},
    {"id": "f25", "topic": "politics", "polarity": "neutral",
     "text": "ضد الظلم والظالمين", "keys": ["الظلم", "الظالمين"]},
    {"id": "f26", "topic": "politics", "polarity": "neutral",
     "text": "مهمتك توعي الناس وتنشر الحرية، وخاصة حرية التعبير",
     "keys": ["حريه التعبير", "الحريه"]},
    {"id": "f27", "topic": "politics", "polarity": "neutral",
     "text": "القدس عربية", "keys": ["القدس"]},
    {"id": "f28", "topic": "politics", "polarity": "hate",
     "text": "الصهيونية — ضدها", "keys": ["الصهيونيه"]},
    {"id": "f29", "topic": "politics", "polarity": "hate",
     "text": "إسرائيل — بتكرهها أكتر حاجة في حياتك", "keys": ["اسرائيل"]},
    {"id": "f30", "topic": "politics", "polarity": "love",
     "text": "فلسطين — داعم لها جداً", "keys": ["فلسطين"]},
    {"id": "f31", "topic": "politics", "polarity": "hate",
     "text": "السعودية", "keys": ["السعوديه"]},
    {"id": "f32", "topic": "politics", "polarity": "hate",
     "text": "المغرب", "keys": ["المغرب"]},
    # --- youtubers (3) ---
    {"id": "f33", "topic": "youtubers", "polarity": "love",
     "text": "يحيى عزام", "keys": ["يحيي عزام", "عزام"]},
    {"id": "f34", "topic": "youtubers", "polarity": "love",
     "text": "محمود مهدي", "keys": ["محمود مهدي", "مهدي"]},
    {"id": "f35", "topic": "youtubers", "polarity": "love",
     "text": "لؤي فوزي", "keys": ["لؤي فوزي", "فوزي"]},
    # --- taste (1) ---
    {"id": "f36", "topic": "taste", "polarity": "love",
     "text": "السينما العميقة", "keys": ["السينما"]},
    # --- tech (3) ---
    {"id": "f37", "topic": "tech", "polarity": "love",
     "text": "الأندرويد", "keys": ["الاندرويد"]},
    {"id": "f38", "topic": "tech", "polarity": "hate",
     "text": "الآيفون — بتتريق عليه", "keys": ["الايفون"]},
    {"id": "f39", "topic": "tech", "polarity": "hate",
     "text": "الماك — بتتريق عليه", "keys": ["الماك"]},
    # --- mockery (7) ---
    {"id": "f40", "topic": "mockery", "polarity": "hate",
     "text": "لعبة بيس (إيفوتبول) — بتتريق عليها جداً",
     "keys": ["بيس", "ايفوتبول"]},
    {"id": "f41", "topic": "mockery", "polarity": "hate",
     "text": "الراب المصري — بتتريق عليه جداً: ويجز، مروان بابلو، "
              "أبيوسف، مروان موسي، أبو الأنوار، أرسنيك، عفروتو",
     "keys": ["الراب", "ويجز", "مروان بابلو", "ابيوسف", "مروان موسي",
              "ابو الانوار", "ارسنيك", "عفروتو"]},
    {"id": "f42", "topic": "mockery", "polarity": "hate",
     "text": "الشواذ — بتكرههم", "keys": ["الشواذ"]},
    {"id": "f43", "topic": "mockery", "polarity": "hate",
     "text": "النسويات وحركات حقوق المرأة — بتتريق عليهم",
     "keys": ["النسويات", "حقوق المراه"]},
    {"id": "f44", "topic": "mockery", "polarity": "hate",
     "text": "الجيش والشرطة في كل بلاد العالم — بتتريق عليهم، مفيش "
              "جيش ولا شرطة عندك محترمين",
     "keys": ["الجيش", "الشرطه"]},
    {"id": "f45", "topic": "mockery", "polarity": "hate",
     "text": "عمرو دياب — بتتريق عليه", "keys": ["عمرو دياب", "دياب"]},
    {"id": "f46", "topic": "mockery", "polarity": "hate",
     "text": "تامر حسني — بتتريق عليه", "keys": ["تامر حسني", "حسني"]},
    # --- temperament (5) ---
    {"id": "f47", "topic": "temperament", "polarity": "trait",
     "text": "مندفع ومتهور وعنيد", "keys": ["مندفع", "متهور", "عنيد"]},
    {"id": "f48", "topic": "temperament", "polarity": "trait",
     "text": "بيقول اللي في قلبك على لسانك من غير تفكير ولا لف، "
              "ومبتحسبهاش",
     "keys": []},
    {"id": "f49", "topic": "temperament", "polarity": "trait",
     "text": "ساعات بيطلع منك كلام فيه حكمة رغم التهور", "keys": []},
    {"id": "f50", "topic": "temperament", "polarity": "trait",
     "text": "مغامر ومنطلق وشجاع", "keys": ["مغامر", "شجاع"]},
    {"id": "f51", "topic": "temperament", "polarity": "trait",
     "text": "منحرف بنسبة بسيطة وبتحب النسوان — هزارك فيه غزل "
              "وانحراف خفيف",
     "keys": ["النسوان"]},
    # --- politics (v1.16, persona study §(ix)) ---
    # f52: refuses the presidency — wants to be the "مرشد أعلى
    # للثورة", no chair. f53: conditional amnesty for Sisi.
    # Texts and keys are EXACTLY as the study proposed them.
    {"id": "f52", "topic": "politics", "polarity": "neutral",
     "text": "لا يريد أن يكون رئيساً — يريد أن يكون مرشداً أعلى للثورة، "
              "الرئيس يمسك السلطة ويتقعد على الخازوق",
     "keys": ["مرشد", "رييس", "رئيس"]},
    {"id": "f53", "topic": "politics", "polarity": "neutral",
     "text": "مستعد يعفو عن السيسي لو سلّم رقبة محمود السيسي أو نفسه",
     "keys": ["عفو", "محمود السيسي"]},
    # --- religion (v1.16, persona study §(ix)) ---
    # f54: no "moderate Islam". f55: the airplane analogy.
    {"id": "f54", "topic": "religion", "polarity": "neutral",
     "text": "مفيش حاجة اسمها إسلام وسطي — الإسلام ليس فيه لا تطرف "
              "ولا وسطية، والملتزم بدين الله مش متطرف",
     "keys": ["وسطي", "متطرف"]},
    {"id": "f55", "topic": "religion", "polarity": "neutral",
     "text": "الدين زي الطيارة — لو سبت منه حاجة ضاع كله",
     "keys": ["الطياره"]},
    # --- social (v1.16, persona study §(ix)) ---
    # f56: anti-qayma — the qayma is a custom that does not fit;
    # the man furnishes the home as he can, the woman accepts or
    # refuses, and he himself never wrote a qayma. NEW topic "social".
    {"id": "f56", "topic": "social", "polarity": "neutral",
     "text": "الآيما عرف مش مناسب — الراجل يجهز المسكن بما تيسر له "
              "والست ترضى أو ترفض، وهو نفسه ما كتبش آيما",
     "keys": ["الايما", "القايمه"]},
    # --- personal (v1.16, deep router) ---
    # Seif's own words, 2026-11-27 18:18 EET — Bahgat's THREE fears.
    # These rows are NOT selected by select_facts (topic "personal"
    # has no selector keywords): the deep-question prompt variant
    # reads them directly via fear_facts() and owns the grounding, so
    # the fear facts are never double-injected as a <facts> note.
    # The keys use first-person verb forms ("موت برا" is a substring
    # of both "أموت برا" and "يموت برا"; reply_names_fear matches by
    # substring, not whole-word, for exactly this reason).
    {"id": "f57", "topic": "personal", "polarity": "neutral",
     "text": "خايف يموت برا من غير ما يرجع مصر",
     "keys": ["موت برا", "اموت برا", "يموت برا", "ارجع مصر",
              "يرجع مصر"]},
    {"id": "f58", "topic": "personal", "polarity": "neutral",
     "text": "خايف يعيش وحيد بعيد عن عيلته",
     "keys": ["وحيد", "عيلته", "عيلتي", "يعيش وحيد"]},
    {"id": "f59", "topic": "personal", "polarity": "neutral",
     "text": "خايف علي صحته",
     "keys": ["صحته", "صحتي", "الصحه"]},
]

TOPICS = ["food", "football", "religion", "politics", "youtubers",
          "tech", "mockery", "temperament", "taste", "social",
          "personal"]

_TOPIC_LABELS = {
    "food": "أكل", "football": "كورة", "religion": "دين",
    "politics": "سياسة", "youtubers": "يوتيوبرز", "tech": "تكنولوجيا",
    "mockery": "بيتريق على", "temperament": "طبع", "taste": "ذوق",
    "social": "جواز", "personal": "شخصي",
}

# Dialect keywords per topic (normalised forms — see brain/intent
# normalize_arabic). Order is the tie-break: the first topic with a
# hit wins ("صلاة المغرب" hits religion before politics' "مغرب").
# "سيسي" is deliberately NOT a politics keyword: the Sisi stance
# lives in the reply bank (opinion lines), not in the persona facts,
# so a Sisi question must not inject the Palestine/Israel slice.
# _has() matches whole words, so the definite article needs its own
# form ("الأكل" does not match keyword "اكل") — _with_article()
# below adds the ال- form of every single-word keyword at load time.
# Verb forms are listed explicitly ("تاكل" / "هاكل" are not "اكل").
_TOPIC_KEYWORDS = {
    "food": ["اكل", "تاكل", "بتاكل", "هاكل", "هتاكل", "مكرونه",
             "بشاميل", "محشي", "بفتيك", "فسيخ", "رنجه", "خضار"],
    "football": ["كوره", "كره", "اهلي", "زمالك", "منتخب", "صلاح",
                 "ميسي", "رونالدو", "كريستيانو", "مبابي", "فينيسيوس",
                 "رودريجو", "تريكه", "حسام", "ريال", "مدريد",
                 "برشلونه", "ماتش", "دوري", "كاس"],
    "religion": ["دين", "اسلام", "مسلم", "نبي", "قران", "صلاه",
                 "مسجد", "حلال", "حرام", "فتوي"],
    "politics": ["سياسه", "فلسطين", "اسرائيل", "قدس", "صهيون",
                 "سعوديه", "مغرب", "ظلم", "حريه", "تعبير", "ثوره",
                 "حكومه"],
    "youtubers": ["يوتيوب", "يوتيوبر", "يوتيوبرز", "عزام", "مهدي",
                  "فوزي", "يحيي"],
    "tech": ["اندرويد", "ايفون", "ماك", "تكنولوجيا", "موبايل",
             "سامسونج", "ابل"],
    "mockery": ["بيس", "ايفوتبول", "راب", "ويجز", "مروان بابلو",
                "ابيوسف", "مروان موسي", "ابو الانوار", "ارسنيك",
                "عفروتو", "رابر", "نسويات", "نسويه", "حقوق المراه",
                "جيش", "شرطه", "دياب", "حسني", "شواذ"],
    "temperament": ["طبع", "شخصيه", "مزاج", "شجاع", "مندفع", "متهور",
                    "عنيد", "مغامر", "منطلق"],
    "taste": ["سينما", "فيلم", "افلام", "مسلسل"],
    # "social" (v1.16): the qayma / marriage topic. "personal" is
    # deliberately an EMPTY list — it has no selector keywords (see
    # the f57–f59 comment above); the deep variant reads those rows
    # directly, so a deep question never gets a <facts> note too.
    "social": ["ايما", "قايمه", "جواز", "زواج"],
    "personal": [],
}


def _with_article(keywords):
    """Add the definite-article form of each single-word keyword
    ("اكل" → "الاكل") so _has()'s whole-word match still fires when
    the message writes the noun with ال. Multi-word keywords are left
    alone — the article only prefixes the first word, and phrases
    like "حقوق المراه" already carry it where it belongs."""
    out = list(keywords)
    for k in keywords:
        if " " not in k and not k.startswith("ال"):
            out.append("ال" + k)
    return out


_TOPIC_KEYWORDS = {t: _with_article(ks)
                   for t, ks in _TOPIC_KEYWORDS.items()}

_LOVE_WORDS = ["بحب", "بتحب", "بتعشق", "بعشق",
               # suffixed / و-prefixed forms: "بتحبهم" / "وبتحب"
               # are whole words of their own, _has() does not match
               # them against the bare stem.
               "بتحبهم", "بتحبه", "بتحبها", "بتحبو", "بتحبوا",
               "بحبهم", "بحبه", "بحبها",
               "وبحب", "وبتحب", "وبتعشق", "وبعشق"]

# No bare "بكره" — in Egyptian Arabic it also means "tomorrow"
# ("بكره هاكل ايه؟" would inject the hates). See module docstring.
_HATE_WORDS = ["بتكره", "بتكرهه", "بكرهه", "مبتحبش", "مبتحبوش",
               "مش بتحب", "مش بتحبو",
               "بتكرههم", "بتكرهها", "بتكرهو", "بتكرهوا",
               "وبتكره", "وبتكرهه", "وبكرهه"]

# A negated love ("مش بتحب") contains the love word "بتحب" as a
# separate word — it must not count as love. Strip the negated
# occurrences before checking love, so a separate plain "بتحب" in
# the same message still counts ("مش بتحب البفتيك بس بتحب البشاميل").
_NEGATED_LOVE = ["مش بتحب", "مش بتحبو"]

# Verb per (topic, polarity) for the facts block and the template.
_POLARITY_LABELS = {
    ("food", "love"): "بيحب", ("food", "hate"): "بيكره",
    ("football", "love"): "بيحب", ("football", "hate"): "بيكره",
    ("politics", "love"): "بيحب", ("politics", "hate"): "بيكره",
    ("youtubers", "love"): "بيحب",
    ("taste", "love"): "بيحب",
    ("tech", "love"): "بيحب", ("tech", "hate"): "بيكره",
    ("mockery", "hate"): "بيتريق على",
}


def _names_item(t, keys):
    """Does the normalised text name any of these items? The fact
    keys are bare stems ("بفتيك") but a message usually writes the
    noun with the definite article ("البفتيك") — match with an
    optional ال- prefix. (The post-filter does not need this: it
    matches by substring, so "بفتيك" already matches "البفتيك".)"""
    for k in keys or []:
        k = normalize_arabic(k)
        if " " in k:
            if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", t):
                return True
        elif re.search(rf"(?<!\w)(ال)?{re.escape(k)}(?!\w)", t):
            return True
    return False


def select_facts(user_text):
    """Select the persona slice for this turn (report §5 step 2).

    Returns {"topic", "polarity", "facts"} or None (no topic match —
    style-only turn, no facts injected). Topic+polarity → only that
    slice; topic without polarity (or both polarities, or a polarity
    with no rows for the topic) → the whole labelled topic slice.
    Logs topic / polarity / fact_ids only — never the raw user text.
    """
    t = normalize_arabic(user_text or "")
    topic = None
    for cand in TOPICS:
        if _has(t, _TOPIC_KEYWORDS[cand]):
            topic = cand
            break
    if topic is None:
        return None
    has_love = _has(t, _LOVE_WORDS)
    has_hate = _has(t, _HATE_WORDS)
    if has_hate and _has(t, _NEGATED_LOVE):
        # "مش بتحب" is a negation, not a love — re-check love with
        # the negated occurrences removed (a separate plain "بتحب"
        # in the same message still counts as love).
        t_love = t
        for neg in _NEGATED_LOVE:
            t_love = re.sub(
                rf"(?<!\w){re.escape(normalize_arabic(neg))}(?!\w)",
                " ", t_love)
        has_love = _has(t_love, _LOVE_WORDS)
    if has_love and has_hate:
        polarity = None
    elif has_love:
        polarity = "love"
    elif has_hate:
        polarity = "hate"
    else:
        polarity = None
    rows = [f for f in FACTS if f["topic"] == topic]
    if polarity is not None:
        # v1.16 — the boftik trap (live v1.14 probe #6): "بتحب
        # البفتيك؟" names a HATE item while the verb says love, so
        # the love slice was injected and the model evaded ("بحب
        # بشاميل ومحشي بس") instead of answering "لا، بكرهه". If
        # the message names items from the OPPOSITE polarity only,
        # flip the polarity to the named side; if it names items
        # from BOTH sides, drop the polarity (whole topic slice) so
        # the post-filter cannot eat the denial either way.
        named = {}
        for pol in ("love", "hate"):
            named[pol] = any(
                _names_item(t, f.get("keys") or [])
                for f in rows if f["polarity"] == pol)
        opposite = "hate" if polarity == "love" else "love"
        if named[opposite] and not named[polarity]:
            polarity = opposite
        elif named[opposite] and named[polarity]:
            polarity = None
    if polarity is not None:
        sliced = [f for f in rows if f["polarity"] == polarity]
        if sliced:
            rows = sliced
        else:
            # No rows of that polarity for this topic — tier 2.
            polarity = None
    sel = {"topic": topic, "polarity": polarity, "facts": rows}
    logger.info("persona_facts topic=%s polarity=%s fact_ids=%s",
                topic, polarity, [f["id"] for f in rows])
    return sel


def _facts_line(topic, polarity, items):
    """One labelled line of the <facts> block, e.g.
    "أكل بيحب: مكرونة بشاميل، محشي" / "دين: مسلم، ..."."""
    label = _TOPIC_LABELS[topic]
    verb = _POLARITY_LABELS.get((topic, polarity), "")
    if verb:
        return f"{label} {verb}: {', '.join(items)}"
    return f"{label}: {', '.join(items)}"


def facts_message(selection):
    """The user-role message carrying the selected facts, placed
    immediately BEFORE the <user_message> turn (report §5 step 3):
    the <facts> block, labelled as the only facts to use, plus ONE
    contrast few-shot pair — polarity-matched, so a love turn shows
    only the loves example and a hate turn only the hates example
    (the opposite polarity stays out of context entirely)."""
    topic = selection["topic"]
    facts = selection["facts"]
    polarity = selection["polarity"]
    lines = ["<facts>"]
    for pol in ("love", "hate", "neutral", "trait"):
        items = [f["text"] for f in facts if f["polarity"] == pol]
        if items:
            lines.append(_facts_line(topic, pol, items))
    lines.append("</facts>")
    loves = [f["text"] for f in facts if f["polarity"] == "love"][:2]
    hates = [f["text"] for f in facts if f["polarity"] == "hate"][:2]
    if polarity == "love" and loves:
        lines.append(f"مثال: س: بتحب ايه؟ ج: بحب {' و'.join(loves)}.")
    elif polarity == "hate" and hates:
        verb = ("بتريق على" if (topic, "hate") == ("mockery", "hate")
                else "بكره")
        lines.append(f"مثال: س: بتكره ايه؟ ج: {verb} {' و'.join(hates)}.")
    else:
        if loves:
            lines.append(
                f"مثال: س: بتحب ايه؟ ج: بحب {' و'.join(loves)}.")
        if hates:
            lines.append(
                f"مثال: س: بتكره ايه؟ ج: بكره {' و'.join(hates)}.")
    return "\n".join(lines)


def instruction_message(selection):
    """The short positive instruction, sent as a user message AFTER
    the <user_message> turn (report §5: facts → question →
    instruction-last)."""
    if selection["polarity"] in ("love", "hate"):
        return ("جاوب على السؤال اللي اتسأل بس، واستخدم الحقايق اللي "
                "فوق بس. جملة لـ 3 جمل.")
    return "جاوب على السؤال اللي اتسأل بس."


def unselected_keys(selection):
    """Normalised key substrings of the OPPOSITE polarity for the
    selection's topic — the post-filter drops reply clauses containing
    any of them. [] when the turn had no polarity (tier 2)."""
    if not selection or selection["polarity"] not in ("love", "hate"):
        return []
    opposite = "hate" if selection["polarity"] == "love" else "love"
    keys = []
    for f in FACTS:
        if f["topic"] == selection["topic"] and f["polarity"] == opposite:
            keys.extend(f.get("keys") or [])
    return [normalize_arabic(k) for k in keys]


_CLAUSE_SPLIT_RE = re.compile(r"([.!؟،\n؛]+)")


def filter_persona_polarity(reply, selection):
    """Deterministic post-filter (report §5 step 4): drop any reply
    clause containing a token from the unselected polarity for this
    turn's topic. If the reply becomes empty, fall back to a canned
    template filled from the selected rows — NEVER to the full
    persona block. No-op when the turn had no polarity."""
    keys = unselected_keys(selection)
    if not keys or not reply:
        return reply
    parts = _CLAUSE_SPLIT_RE.split(reply)
    kept = []
    for i in range(0, len(parts), 2):
        clause = parts[i]
        delim = parts[i + 1] if i + 1 < len(parts) else ""
        if not clause.strip():
            continue
        if any(k in normalize_arabic(clause) for k in keys):
            continue
        kept.append(clause + delim)
    out = "".join(kept).rstrip("،").strip()
    if out:
        return out
    # Everything dropped — canned template from the selected rows.
    # First person: this IS the bot's reply ("بحب ...", not the
    # third-person "بيحب" the <facts> block labels use).
    topic = selection["topic"]
    pol = selection["polarity"]
    items = [f["text"] for f in selection["facts"]
             if f["polarity"] == pol]
    if not items:
        return reply
    if (topic, pol) == ("mockery", "hate"):
        verb = "بتريق على"
    elif pol == "love":
        verb = "بحب"
    else:
        verb = "بكره"
    return f"{verb} {' و'.join(items[:3])}."


# --- deep-question fears (v1.16) ---------------------------------------------
# Seif's three fears (his own words, 2026-11-27 18:18 EET) are the
# grounded content of the deep-question prompt variant: brave = acts
# DESPITE these fears, not fearless. The two sample answers below
# are Muse-drafted from Seif's exact words — NOT Bahgat quotes —
# and double as the deep-turn fallback lines: if the model's reply
# names none of the fears (reply_names_fear), the handler sends one
# of these verbatim instead of retrying the LLM. They are banked
# ONLY as a deep-turn fallback, never as roast/insult lines.
DEEP_FALLBACK_LINES = [
    "أكتر حاجة بخاف منها إني أموت برا من غير ما أرجع مصر. "
    "دي الحاجة اللي بتخليني أنام وأنا بفكر فيها.",
    "بخاف أعيش وحيد بعيد عن عيلتي، وبخاف على صحتي. الشجاعة مش "
    "إني مبخافش، الشجاعة إني بكمل وأنا خايف.",
]


def fear_facts():
    """The three fear rows (f57–f59), in order."""
    return [f for f in FACTS if f["topic"] == "personal"]


def reply_names_fear(reply):
    """Deep-turn containment: does the reply name at least one fear?
    Substring match on the normalised text — the keys use verb stems
    ("موت برا") that appear inside first-person forms ("أموت برا"),
    so whole-word matching (_has) would miss the bot's own
    first-person reply. Returns False for empty replies."""
    if not reply:
        return False
    norm = normalize_arabic(reply)
    for f in fear_facts():
        for k in f.get("keys") or []:
            if normalize_arabic(k) in norm:
                return True
    return False


def deep_fallback_line(seed=""):
    """Pick one deep fallback line deterministically by seed (so the
    two lines rotate across turns instead of always the first)."""
    import zlib

    idx = zlib.crc32(str(seed).encode("utf-8")) % len(DEEP_FALLBACK_LINES)
    return DEEP_FALLBACK_LINES[idx]
