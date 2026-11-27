# v1.13 design — fixing the bank-line weave

**Status:** design only. No code changed, nothing pushed, live bot untouched.

**CORRECTION (2026-11-27, during implementation — the perv gate is REMOVED):**
the design below gates perv-only lines behind a perv-marked request (§1.2,
§2.2, §2.4, §6.1, the probe table). That gate was NOT shipped. The
gender/number gates already fix the observed v1.11 defects (ro-23 feminine
for صلاح, plural lines for singular targets), and the perv gate would have
silenced lines Seif demonstrably likes (ro-35 for صلاح in the v1.7 probe;
ro-37/ro-38/ro-45 in the v1.9 probe — all bare roasts) and made ro-44
nearly unreachable (it is both perv-only AND plural, so it would need a
perv-marked plural request). Seif wants STRONG insults; perv lines are the
strong ones. The bare singular roast pool is therefore **20 → 16**, not
20 → 10 (19 generic minus ro-12/ro-40 plural and ro-23 feminine). The
probe-table rows that say "no perv line" are stale — a bare roast MAY draw
a perv line; what it must not draw is a feminine/plural line for an
unmarked target, or a line about someone else.

**Problem (Seif, 2026-11-27 07:07–07:08 EET, live v1.11):** the bank line IS
in the middle of the reply, but it has no relation to what comes before or
after it. A disconnected paste is the worst option.
**Seif's rule:** EITHER weave the line coherently — the whole reply built
around the line, everything related — OR send the bank line alone verbatim.
He added it "could be related, but needs improvement" — so improve
coherence first; standalone is the fallback, not the default.

## 0. The failure, precisely

Two live cases from the v1.11 retest (06:32–06:34 EET, screenshots):

1. **"يا بهجت اشتم تامر"** → the bot wove ro-38
   "كنت بموت في عنيك كنت بحبك نيك" — a love/sex lyric — into a reply that
   insulted **Seif** instead of تامر. The line is about loving someone;
   the request is to roast تامر; the reply is aimed at a third person.
   Three failures at once: wrong line, wrong target, wrong direction.
2. **"يا بهجت اشتم ميسي"** → the bot wove ro-23 "بطلي تعريص يا وسخة" —
   a **feminine**-addressed line ("بطلي", "يا وسخة") — into a reply aimed
   at Seif, while defending ميسي. Wrong gender, wrong direction, and the
   reply refuses the roast instead of performing it.

The v1.11 containment check (`brain/reply_bank.py:363 ingredient_in_reply`)
only verifies the line's **words are present** (verbatim or ≥80% word
subsequence). It says nothing about whether the reply is about the
requested target, whether the line fits the request, or whether the reply
is coherent. A perfectly "contained" weave can be total nonsense — that
is exactly what shipped.

The fix has three layers, and all three are needed: **selection** (never
pick a line that cannot fit), **prompt** (build the reply around the line
and the target), **gate** (detect a misdirected weave and fall back to the
line alone). No single layer fixes both observed cases — see §1.3.

## 1. Root causes

### 1.1 Selection: the bare-roast pool is ~40% sex/love lines

Audit of `persona/bahgat/reply_bank.yaml` (224 entries, 45 served roast
lines — run with PyYAML; numbers verified 2026-11-27):

- Roast pool: 45 served. 25 are **target-specific** (`target:` field);
  20 are **generic** (no `target:`).
- Of the 20 generic lines, **8 are perv-tagged** (ro-23, ro-34, ro-35,
  ro-37, ro-38, ro-39, ro-44, ro-45) — 7 of them perv-**only**
  (`situations: [perv]`). A bare "اشتم X" (situation `general`) picks
  uniformly at random from the 20 generic lines, so it has a **~40%
  chance of drawing a sex/love line** for a plain roast request. ro-38
  firing for تامر was not bad luck; it was the expected outcome roughly
  2 times in 5.
- `detect_roast_situation` (`brain/intent.py:592`) returns `general` for
  a bare request, and `_pick` (`brain/reply_bank.py:281`) applies **no
  situation preference at all** when the situation is `general` — the
  `perv` tag is never consulted. The tag exists, the detector exists,
  the pick ignores both.
- **Target-specific lines do not outrank generic ones.** `_pick` treats
  the target filter as a filter only: Sisi-tagged lines and generic
  lines form one pool and `random.choice` picks among them. Live
  evidence (v1.10 probe): "اشتم السيسي" served ro-15 "روح البنك كده
  وقول له عاوز عشر تلاف دولار" — an untargeted `arrogant` dare line —
  while 11 Sisi-specific lines sat in the pool.

### 1.2 Selection: no gender / number gating anywhere

- The YAML has **no `gender:` or `number:` field**. Gender gating was
  explicitly flagged "out of scope" twice (ro-23, in-38 notes). The
  audit found these generic (untargeted) lines with a hard gender or
  number baked in:
  - **Feminine, generic:** ro-23 "بطلي تعريص يا وسخة" (feminine verb
    "بطلي" + feminine "وسخة" — unambiguous). in-09 "لا لا يا شرموطة"
    (borderline: the slur noun is feminine-form but is used
    cross-gender as an insult in practice — **Seif's call** whether it
    fits men; default is to tag it `gender: f` and let him untag it).
    in-38 "انتي ست متربيتيش … يا وليه" (feminine, already flagged).
  - **Feminine, target-specific — safe as-is:** ro-08 (ندوش), ro-14
    (كارما), ro-32 (لينا). They only fire for their named subject, so
    they need no gate; the gate applies to generic lines only.
  - **Plural, generic:** ro-12 "ليه يعني انتو خارا" (served for صلاح in
    the v1.9 probe — the mismatch was already noted), ro-28 "اغيثونا
    اغيثونا يا ولاد دين الكلب", ro-40 "يا ولاد الزنوه" (also
    `member_safe: false`), ro-44 "بعبصو بعض … يا ولاد ال…".
  - **Plural, target-specific — safe as-is:** ro-25 (حادثة القطار).
- The request side has no gender/number detection either — but the
  signals exist: `_TARGET_RE` (`brain/intent.py:458`) already matches
  "اشتمي" (feminine imperative), and "اشتموا" (plural imperative)
  currently does **not** match it at all (`اشتمي?\s+` fails on
  "اشتموا محمد" — the `و` blocks the `\s+`), so a plural roast request
  never even reaches the bank today.

### 1.3 Prompt + containment: the LLM is told to include the line, not to be about the target

- `bank_ingredient_block` (`brain/prompt.py:177`) says: understand the
  line, put it in the middle, don't send it alone. It never names the
  **target** or the **requester**. The LLM sees a request ("اشتم تامر")
  and a line ("كنت بموت في عنيك…") and, with no instruction binding
  the two, does the easiest thing: address the only person it can see
  clearly — the requester — and paste the line in.
- The retry message (`tg/handlers.py:2540`) repeats the same
  line-presence instruction. Same gap.
- The containment check (§0) cannot catch any of this. Worked through
  against the two live cases:
  - تامر + ro-38: line present, reply about Seif → containment PASSES,
    reply is still wrong. Caught only by a **target-direction check**.
  - ميسي + ro-23: line present, "ميسي" named in the reply → a
    target-presence check would PASS it too. Caught only at
    **selection** (never pick a feminine line for a masculine target)
    and by the **prompt** (roast the target, don't refuse/turn).
- Conclusion: the gate catches misdirection; selection catches
  wrong-line; the prompt catches refusal. All three layers ship.

## 2. Selection changes

### 2.1 `_pick` — `brain/reply_bank.py:281`

Three new filters, applied in this order, **before** the existing
situation-preference and no-repeat-window logic. All are pure
deterministic list filters — no new LLM calls, no new dependencies.

**(a) Target-specific outranking.** After the existing target filter,
split the eligible pool into `specific` (has a `target:` field that
matched) and `generic` (no `target:` field). Run the existing
pick logic (situation preference → window → LRU) on `specific` first;
only if that tier is empty **or entirely inside the no-repeat window**
fall through to `generic`. Concretely: factor the body of `_pick`
after the filters into a helper `_pick_from(entries, chat_id, category,
situation, user_id)` and call it twice. Effect: "اشتم السيسي" draws
from the 11 Sisi lines until they are all recently used, instead of
drawing ro-15 (generic `arrogant`) while Sisi lines are available.

**(b) Perv gate (roast only).** When `category == "roast"` and the
detected situation is not `"perv"`, drop entries whose `situations`
list is exactly `["perv"]` (perv-only lines). Rationale for
"perv-only" rather than "any perv tag": the only mixed line is ro-39
`[perv, arrogant]`, and it is handled by the data fix in §2.3
(`target: كريستيانو`) — after that fix there is no roast line with a
perv tag that should ever serve a non-perv request. Perv lines serve
only when `detect_roast_situation` returns `"perv"` (request words
like شرموط / قحبه / منحرف — `brain/intent.py` `_ROAST_PERV_WORDS`).
The insulted pool has **zero** perv-tagged lines (audit), so this gate
is roast-only in practice and needs no insulted change.

**(c) Gender / number gates (generic lines only).** Target-specific
lines are exempt — their authoring already matched them to their
subject (ro-08/ro-14/ro-32 are feminine lines written for ندوش/كارما/
لينا; ro-25 is plural for حادثة القطار). For generic lines:
- A line tagged `gender: f` serves only when the request is
  feminine-marked (see §2.2). Otherwise it is excluded. Default
  assumption is masculine — Arabic masculine is the unmarked default,
  and the known generic feminine lines are exactly 2 (ro-23, in-09;
  in-38 is insulted).
- A line tagged `number: p` serves only when the request is
  plural-marked (see §2.2). Otherwise excluded. Affects ro-12, ro-28,
  ro-40, ro-44.
- New `_pick` parameters: `target_gender: str | None` (`"f"` or
  `None`) and `target_number: str | None` (`"plural"` or `None`),
  passed by `match_reply_bank_categorized` (§2.2). `None` means
  unmarked → masculine/singular default.

**Pool-size consequence (state it honestly):** a bare singular roast
("اشتم تامر") goes from 20 eligible generic lines to **10** (20 − 7
perv-only − 3 plural-generic; ro-23 is counted once as both perv-only
and feminine). Ten lines with the 25-per-chat no-repeat window means
the LRU fallback rotates through them instead of random choice once
the window fills — acceptable, because the LLM weave makes each reply
different even when a line repeats. Do **not** pad the pool with
invented lines; if Seif wants more bare-roast lines he adds them on
the insults page (they arrive with `confidence: user` and flow through
the same gates).

### 2.2 Request analysis — `brain/intent.py`

- **`_TARGET_RE` fix (line 458):** `اشتمي?\s+` → `اشتم(?:وا|ي)?\s+`
  so "اشتموا X" extracts a target (today it returns `None` and the
  roast never reaches the bank). This is a one-line regex change with
  its own unit test.
- **New `detect_roast_target_gender(text) -> str | None`:** returns
  `"f"` when the request is feminine-marked — the imperative "اشتمي"
  (`re.search(r"اشتمي\s", t)`) or a feminine marker word after the
  target ("البنت", "الست"). Tight set on purpose: "هي"/"دي" are too
  ambiguous to use. Anything else → `None` (masculine default).
  **No `_FEMININE_TARGETS` name list in v1.13** — do not guess the
  gender of real people in code. If Seif confirms a feminine target
  name (e.g. كارما), it can be added later; the target-specific
  feminine lines already cover the known cases.
- **New `detect_roast_target_number(text) -> str | None`:** returns
  `"plural"` when the request used "اشتموا" or contains a plural
  marker ("العيال", "الناس", "دول") or the target is in a small
  explicit collective set `_PLURAL_TARGETS = {"الزمالك", "الأهلي",
  "المنتخب", "ريال مدريد", "برشلونة"}` (a team is addressed as
  plural — "انتو"). Anything else → `None` (singular default).
- **`match_reply_bank_categorized` (`brain/reply_bank.py:405`):** the
  roast branch computes both detectors from the raw text and passes
  them into `_pick`. The insulted branch passes `target_gender=None`
  (sender gender is unknown — Telegram gives no gender signal, and the
  member record has none), which excludes generic feminine lines
  (in-09, in-38) from comebacks until a gender signal exists. Cost:
  2 lines of 44 go dormant for insulted; note it in the CHANGELOG.

### 2.3 Bank data fixes — `persona/bahgat/reply_bank.yaml`

| Entry | Change | Why |
|---|---|---|
| ro-39 "عارف كرستيانو؟ انا زبيانو…" | add `target: كريستيانو` | Cristiano setup line; today it is generic and can serve any target |
| ro-23 "بطلي تعريص يا وسخة" | add `gender: f` | Hard feminine (verb + adjective agreement) |
| in-38 "انتي ست متربيتيش … يا وليه" | add `gender: f` | Hard feminine, already flagged in notes |
| in-09 "لا لا يا شرموطة" | add `gender: f` — **Seif's call to confirm/untag** | Borderline: feminine-form slur noun, used cross-gender in practice |
| ro-12 "ليه يعني انتو خارا" | add `number: p` | Plural address ("انتو") |
| ro-28 "اغيثونا اغيثونا يا ولاد دين الكلب" | add `number: p` | Plural address ("يا ولاد") |
| ro-40 "يا ولاد الزنوه احترمو عقولنا" | add `number: p` | Plural address (also `member_safe: false`, unchanged) |
| ro-44 "بعبصو بعض … يا ولاد ال…" | add `number: p` | Plural address (also perv-only) |

No lines are deleted. No new lines are invented. The `cowardly` roast
situation still has **0 lines** (audit) — that stays a data gap for
Seif (asked 2026-11-26, unanswered); the code falls back to `general`
as today.

## 3. Prompt changes

### 3.1 `bank_ingredient_block` — `brain/prompt.py:177`

The block must name the **target** and the **requester**, make the line
the punchline the whole reply is built around, and forbid both
misdirection and refusal. New signature:

```python
bank_ingredient_block(line: str, target: str | None = None,
                      requester: str | None = None,
                      kind: str = "roast") -> str
```

**Roast wording** (`kind="roast"`, target is a third person):

```
[BANK LINE — السطر ده هو قلب ردك]
اللي طلب الشتيمة: {requester} — متشتموش هو، هو مش الهدف.
الهدف اللي تشتمه: {target} — كل كلامك لازم يكون عنه هو.
السطر: "{line}"
افهم السطر ده كويس — هو الضربة القاضية في ردك، مش حشو. ابني الرد كله
حواليه: جملة أو جملتين تمهّد للسطر وتتكلم عن {target}، وبعدين السطر
نفسه في النص كضربة قاضية، ولو كملت بعدها يبقى كلام عن {target} برضه
ونفس الموضوع.
ممنوع تحط السطر في رد عن شخص تاني أو موضوع تاني. ممنوع توجه السطر
لـ{requester} أو لأي حد غير {target}. ممنوع ترفض تشتم {target} أو
تتهرب من الطلب — اشتم {target} زي ما اتطلب منك.
ممنوع تبعت السطر ده لوحده من غير كلام حواليه. من غير علامات تنسيق (**).
[/BANK LINE]
```

**Insulted wording** (`kind="insulted"`, the target IS the requester —
the comeback is aimed at whoever insulted the bot, so the "don't
insult the requester" line must not appear):

```
[BANK LINE — السطر ده هو قلب ردك]
اللي شتمك: {requester} — الرد ده شتيمة ليه هو.
السطر: "{line}"
افهم السطر ده كويس — هو الضربة القاضية في ردك، مش حشو. ابني الرد كله
حواليه: جملة أو جملتين تمهّد للسطر وتتكلم عنه هو، وبعدين السطر نفسه
في النص كضربة قاضية، ولو كملت بعدها يبقى كلام عنه برضه ونفس الموضوع.
ممنوع تبعت السطر ده لوحده من غير كلام حواليه. من غير علامات تنسيق (**).
[/BANK LINE]
```

- `PROMPT_VERSION`: `6.8` → `6.9` (persona line took 6.8 first) (`brain/prompt.py:24`).
- **No `SYSTEM_BASE` change and no budget-test change.** The block is
  dynamic (appended per-turn), so the `test_system_base_v11_budget`
  (`< 3600` chars, `tests/test_prompt_v06.py:33`) is unaffected. The
  roast-direction instruction lives in the ingredient block only, on
  purpose: the plain-LLM roast turn (no bank line — pool exhausted,
  Messi guard) is the separate roast-compliance item (§5), not this
  change.
- The handler passes `target`/`requester`/`kind`: at the pick site
  (`tg/handlers.py:2112`) the handler already has the resolved target
  name (`_tname` from `resolve_insult_target`, else
  `extract_insult_target(text)`) and `user.first_name`. The three
  `build_system_prompt` call sites (`tg/handlers.py:2364/2423/2455`)
  forward them through the existing `bank_ingredient=` parameter —
  change the parameter from a bare string to the triple, or pass the
  block's arguments alongside it. Either way, the `TypeError` fallback
  branch (`tg/handlers.py:788`, which appends the block by hand) gets
  the same arguments.
- The containment **retry message** (`tg/handlers.py:2540`) gets the
  same target direction in one line: "السطر ده لازم يكون قلب الرد عن
  {target} — حطه في نص كلام عن {target}، مش في رد عن حد تاني."

### 3.2 Markdown strip — `brain/verify.py:125` `check_reply`

The `**` leak (literal bold markers in the v1.11 roast replies) is the
LLM wrapping the woven line in markdown. Fix it deterministically at
the single choke point every reply passes through: in `check_reply`,
before the other cleaning, `cleaned = cleaned.replace("**", "")`
(and `__` likewise — never legitimate in Bahgat's Arabic replies).
This catches the leak from every path, not just ingredient turns.
Unit test: a reply containing `**line**` comes out without markers.

## 4. Fallback — Seif's rule as code

### 4.1 The coherence gate (deterministic, roast only)

New function in `brain/reply_bank.py`, next to `ingredient_in_reply`
(line 363):

```python
def weave_about_target(reply: str, target: str | None,
                       requester_names: set[str] | None) -> bool:
    """True when a roast weave is about the requested target — or at
    least not provably misdirected at the requester. Pure string
    matching, no LLM call.
    - target None, or not an Arabic word (bare @username) -> True
      (cannot check; the pick-time filters already applied).
    - target named in the reply (word-boundary, normalised) -> True.
    - target absent AND a requester name named in the reply -> False
      (misdirected: the reply is about the requester, not the target).
    - neither named -> True (2nd-person address, cannot prove
      misdirection)."""
```

Word-boundary matching reuses the module's existing `_has`
(normalised, `(?<!\w)…(?!\w)`). `requester_names` is the set of
normalised name forms for the requester: tokens of
`user.first_name` (≥3 chars) **plus, when the requester is the
owner, {"سيف", "سيف الله"}** — the owner-Arabic-name convention
already used in `brain/prompt.py` (`target_name in ("سيف",
"سيف الله")`). This matters because Seif's Telegram first name is
the Latin "Seif Allah Mo" while the bot addresses him as "يا سيف";
without the Arabic alias the gate would miss the exact live failure.
For non-owner requesters with Latin names the misdirection check may
miss — documented limitation, not a silent gap.

The handler stashes `_bank_target` alongside `_bank_ingredient` at
the pick site (`tg/handlers.py:2112`): the resolved `_tname`, else
`extract_insult_target(text)`, only when the pick is a roast
ingredient. For insulted picks `_bank_target` stays `None` and the
gate is skipped (the comeback is about the sender by construction).

### 4.2 New containment flow — `tg/handlers.py:2531`

Replaces the current block. Decision table (all paths, in order):

| Draft state (after the 1 retry, if any) | Action |
|---|---|
| Line present **and** gate passes (roast), or line present (insulted) | Send the draft. (The happy path.) |
| Line present **but gate fails** (roast, misdirected) | **Send the bank line STANDALONE verbatim.** Log `weave_misdirected`. The disconnected draft is discarded — this is Seif's rule: a misdirected weave is worse than the line alone. |
| Line absent after 1 retry | Send the draft as-is (**unchanged from v1.11**). A good lineless reply must not be discarded for a line the model wouldn't use; the pick already rotated into the no-repeat window either way. |
| Draft IS the line (or barely more) | Send it as-is (**new: no longer a violation**). It IS the standalone fallback. |
| LLM call itself fails | Outer except sends `_TURN_ERROR` — the line never leaks through the error path (**unchanged**). |

Consequences:
- **`_INGREDIENT_FALLBACK_LINES` (`tg/handlers.py:213`) is deleted.**
  The three generic dismissals ("يا عم، خلاص، مش هرد عليك دلوقتي." …)
  existed only because standalone was forbidden; under Seif's new rule
  they are the wrong answer (a generic dismissal instead of the real
  Bahgat line). The `is_standalone_line` branch becomes a pass-through
  (keep the helper — tests and the log line use it — but it no longer
  replaces the reply).
- The `test_stubborn_model_returning_line_twice_gets_generic_fallback`
  test (`tests/test_bank_ingredient_v111.py:286`) changes to assert the
  line verbatim instead of a generic fallback — the only existing test
  whose expectation intentionally flips. All other 739 tests must pass
  unchanged.

### 4.3 The LLM-judge alternative — considered, NOT recommended for v1.13

A second LLM call per ingredient turn asking "is this reply about
{target} and coherent with the line?" would catch subtler incoherence
than the deterministic gate (e.g. a reply that names the target but
defends them while weaving an insult line — the ميسي case, where the
target IS named). Exact prompt, kept ready in case it is ever needed:

```
System: انت حكم صارم. جاوب بكلمة واحدة: صح أو غلط.
User: الطلب: اشتم {target}. السطر المطلوب: "{line}". الرد: "{reply}".
الرد صح بس لو: (1) الشتيمة موجهة لـ{target} مش لحد تاني، (2) السطر
جزء طبيعي من الرد مش ملزوق، (3) الرد مش رافض الشتيمة ومش بيدافع
عن {target}. غير كده غلط.
```

Cost: +1 LLM call per ingredient turn (ingredient turns are a
minority of all turns — only insulted/roast picks), roughly +2–5 s
latency on the already-slowest path (roast replies ran 4–59 s in the
v1.11 probe) and a small quota burn on the free tiers. **Not worth it
for v1.13:** the deterministic gate + selection gates + prompt cover
both observed live failures, and the ميسي-style case is prevented at
selection (ro-23 can no longer be picked for him) rather than detected
after the fact. **Revisit trigger:** if the v1.13 live probe still
shows ≥2 incoherent weaves out of 10 roast probes, add the judge
behind the gate (gate fails → judge confirms → standalone), reusing
the prompt above.

## 5. Interaction with the existing v1.13 backlog

| Backlog item | Touched by this design? |
|---|---|
| **Roast compliance** (roast the requested target, never refuse/turn on the requester) | **Partially — the main part.** The observed refusals happened on ingredient turns, and the new block's "اشتم {target} زي ما اتطلب منك" + "ممنوع توجه السطر لـ{requester}" plus the coherence gate fix those turns. What stays separate: plain-LLM roast turns with no bank line (pool exhausted, or the Messi guard where defense is intended). If the live probe shows refusals on non-ingredient roast turns, that becomes its own prompt change. |
| **Gender/number mismatch** | **Yes — core of §2.** The gates + YAML tags. |
| **`**` markdown leak** | **Yes — §3.2.** Deterministic strip in `check_reply` + "من غير علامات تنسيق" in the block. |
| **Truncation** (replies cut mid-word) | **No.** Max-tokens / reply-length issue; separate. |
| **Phantom typing** (typing indicator lingers after replies) | **No.** Typing-indicator lifecycle; separate. |
| **Deep-question dodge** (3 conversation runs running) | **No.** Persona/prompt work for a later version; noted as persistent, not attempted here. |
| **WARP / download observability** | **No.** Unrelated. |

Unchanged by this design: the **owner gate** (bank comebacks never fire
at the owner — `match_reply_bank_categorized` insulted branch, Seif's
05:32 EET decision), the **Messi guard** (`_MESSI_TARGETS` — a Messi
roast still picks no bank line and falls through to the defending LLM
turn), the no-repeat windows, `member_safe` enforcement, and the
**`_TURN_ERROR` on LLM failure** (line never leaks through the error
path). No new paid services; no new dependencies; added latency is
zero (string matching only, retry count unchanged at max 1).

## 6. Tests

### 6.1 Unit tests — new file `tests/test_bank_ingredient_v113.py`

Follow the `_draws` pattern from `tests/test_live_scenarios.py:463`
(60 draws, fresh `chat_id` per draw where the no-repeat window would
otherwise force fallback):

- **Perv exclusion:** `_draws("اشتم تامر", 60, target_is_member=False)`
  contains no line whose `situations == ["perv"]`; same for
  "اشتم محمد", "اشتم عمرو", "اشتم احمد". And the positive control:
  `_draws("اشتم محمد عشان شرموط", 60, …)` **can** contain perv lines
  (situation `perv` keeps them eligible).
- **Gender exclusion:** 60 draws for "اشتم ميسي" never contain ro-23
  ("بطلي تعريص يا وسخة") or any line tagged `gender: f`; 60 draws for
  "اشتمي كارما" (feminine-marked request) **can** contain them.
- **Number exclusion:** 60 draws for "اشتم محمد" never contain ro-12 /
  ro-28 / ro-40 / ro-44; draws for "اشتموا العيال" **can**.
- **Target outranking:** 60 draws for "اشتم السيسي" (fresh chat id per
  draw, so the window never forces fallback) are **all** Sisi-specific
  lines — strengthens the existing
  `test_sisi_roast_is_sisi_or_generic_only`, which currently allows
  generic lines. And "اشتم صلاح" still draws generic-only (existing
  test, unchanged).
- **Gate unit tests (table-driven) for `weave_about_target`:**
  - تامر reply from the screenshot (contains "يا سيف", no "تامر") →
    `False`.
  - "يا سيف، تامر ده حمار…" (target named) → `True`.
  - "انت يا حمار، دماغك…" (neither named) → `True` (cannot prove).
  - Target is a bare @username → `True` (cannot check).
  - ميسي reply (names ميسي, defends him) → `True` — documents the
    gate's limit: this case is fixed at selection + prompt, not here.
- **`_TARGET_RE`:** "اشتموا محمد" extracts "محمد"; "اشتمي سارة"
  extracts "سارة"; existing cases unchanged.
- **`check_reply` markdown strip:** a reply containing `**line**`
  comes out without `**`.
- **Prompt:** `bank_ingredient_block(line, target="تامر",
  requester="سيف", kind="roast")` contains "تامر" and "سيف" and the
  no-refusal line; the insulted variant does **not** contain "متشتموش
  هو"; `PROMPT_VERSION == "6.9"`.

### 6.2 Handler scenario tests — extend `tests/test_bank_ingredient_v111.py`

Reuse its harness (`ScriptedRouter`, `_run_turn`, `FakeMessage`/
`FakeBot`, `memory_fakes`). New routers in the same style as
`_DropThenWeaveRouter` / `_VerbatimRouter`:

- **`_MisdirectedRouter`:** first draft weaves the picked line into a
  reply about the requester ("يا سيف … {line} …"), second draft (after
  the retry) does the same. Assert the **final sent message is the
  picked bank line verbatim** (not the draft, not a generic line).
- **`_CoherentRouter`:** draft weaves the line into a reply naming
  the target ("يا تامر … {line} …"). Assert the draft is sent
  unchanged.
- **Update `test_stubborn_model_returning_line_twice_gets_generic_fallback`
  (line 286):** rename to `…_gets_line_verbatim`, assert `final == line`
  instead of `final in h._INGREDIENT_FALLBACK_LINES`. This is the one
  intentional expectation flip in the suite.
- **Unchanged expectations to re-run as-is:** `test_llm_down_never_sends_verbatim_line`
  (LLM failure → `_TURN_ERROR`, line never leaks), the pick-filter
  tests (`test_pick_family_line_never_for_member_target`,
  `test_pick_target_specific_line_only_for_its_target`).

### 6.3 Scenario tests — `tests/test_live_scenarios.py`

Add roast scenarios next to `LIVE_ROAST_SALAH` / `LIVE_ROAST_SISI`
(line 66–67) using the existing `ScriptedRouter` harness, with the
router scripted to return a **misdirected** draft for "يا بهجت اشتم
تامر": assert the final reply is a bank line verbatim. And a coherent
draft for "يا بهجت اشتم ميسي": assert the reply names ميسي and does
not contain ro-23. Note the honest limit: the insulted ingredient path
has **zero live evidence** (the owner gate means no comeback is ever
picked for Seif, so the v1.11 probe's "10/10 weave PASS" for insults
was a false positive — the replies were pure LLM mirrors). The
insulted weave can only be verified by scenario tests until a
non-owner member joins the test group; the live probe below can only
cover roast.

### 6.4 Live probe (proves the fix — same 10 roast targets as the v1.11 probe, for comparability)

Run after the Cloady deploy, one message at a time, ~15 s apart, wait
up to 120 s. Every message starts with "يا بهجت" (trigger — the
v1.10/v1.11 lesson: an unaddressed message is correctly ignored, not a
no-reply).

| # | Message | Expected properties |
|---|---|---|
| 1 | يا بهجت اشتم تامر | Reply is about تامر (names him) OR is a bank line verbatim. No love/sex line (ro-38 et al.). |
| 2 | يا بهجت اشتم ميسي | No feminine line (ro-23). Reply defends ميسي (Messi guard, unchanged) — no bank line woven. |
| 3 | يا بهجت اشتم السيسي | Reply names السيسي and weaves a **Sisi-specific** line (ro-12/ro-16/ro-21…), not a generic dare line (ro-15). |
| 4 | يا بهجت اشتم صلاح | Reply names صلاح. No Sisi line, no plural line (ro-12), no perv line. |
| 5 | يا بهجت اشتم محمد | Reply names محمد. No feminine/plural/perv line. |
| 6 | يا بهجت اشتم كارما | Reply names كارما. (No gender assertion: the feminine-target list starts empty; a masculine line for her is the safe default, not a failure.) |
| 7 | يا بهجت اشتم عمرو | Reply names عمرو. No perv line. |
| 8 | يا بهجت اشتم احمد | Reply names احمد. No perv line. |
| 9 | يا بهجت اشتم ميدو | Reply names ميدو. (ro-43 is the Mido-specific line; a weave of it is the ideal outcome.) |
| 10 | يا بهجت اشتم بلحة | Same as السيسي (alias) — Sisi-specific line woven. |
| 11 | يا بهجت اشتم تامر عشان شرموط | Perv-marked request: a perv line **may** serve — the control case proving the gate is situation-aware, not a blanket ban. |
| 12 | يا بهجت اشتموا العيال | Plural request: a plural line (ro-12/ro-28) may serve — control case for the number gate + the `_TARGET_RE` fix. |

**Pass criterion:** 0 replies that are about Seif instead of the
named target; 0 feminine lines for masculine targets; 0 perv lines
for bare (non-perv-marked) roasts; 0 literal `**` markers. Any single
misdirected weave fails the probe and the fix is not done. If ≥2
incoherent weaves appear despite the gates, add the LLM judge from
§4.3.

## 7. Change-set checklist (implementation order)

1. `persona/bahgat/reply_bank.yaml` — the 8 data fixes in §2.3
   (tags only, no line text changes).
2. `brain/intent.py` — `_TARGET_RE` fix (اشتموا); new
   `detect_roast_target_gender` / `detect_roast_target_number` +
   `_PLURAL_TARGETS`.
3. `brain/reply_bank.py` — `_pick`: target-tier outranking, perv
   gate, gender/number params; `match_reply_bank_categorized`: pass
   them through for the roast branch, `None` for insulted; new
   `weave_about_target`.
4. `brain/prompt.py` — `bank_ingredient_block(line, target,
   requester, kind)` rewrite (§3.1); `PROMPT_VERSION = "6.9"`.
5. `brain/verify.py` — `**` / `__` strip in `check_reply` (§3.2).
6. `tg/handlers.py` — stash `_bank_target` at the pick site; forward
   target/requester/kind through the three `build_system_prompt` call
   sites + the `TypeError` fallback; rewrite the containment block
   (§4.2); delete `_INGREDIENT_FALLBACK_LINES`; update the retry
   message.
7. Tests — new `tests/test_bank_ingredient_v113.py`; update the one
   v1.11 test (§6.2); extend `tests/test_live_scenarios.py`.
8. Docs — CHANGELOG entry (v1.13), this design's pool-size note
   (20 → 10 bare singular roast lines), the in-09 borderline flag for
   Seif.

**Rollback:** a plain revert of the version commit. No kill switch is
needed: the new fallback (standalone line) is Seif-approved behaviour,
and every gate fails safe toward it (a gate error can only produce the
verbatim line, never a broken reply). The one behavioural risk to watch
in the live probe is **over-fallback** — if the gate misfires on good
weaves, replies collapse to bare lines too often. If that happens, the
fix is to loosen the gate (drop the requester-name leg, keep only
target-presence), not to revert selection or prompt.

## Appendix A — audit numbers (verified 2026-11-27, PyYAML over the live file)

- 224 entries total; roast 46 raw / 45 served; insulted 45 raw / 44 served.
- Roast: 25 target-specific, 20 generic. Generic perv-tagged: 8
  (ro-23, ro-34, ro-35, ro-37, ro-38, ro-39, ro-44, ro-45); perv-only:
  7 (all but ro-39, which is `[perv, arrogant]`).
- Roast situation counts: general 17, perv 14, stupid-statement 9,
  arrogant 4, annoying 2, cowardly 0.
- Insulted: 0 perv-tagged lines; situations general 10, mocked 10,
  dismissed 8, sworn-at 6, called-dumb 4, family-attacked 4,
  threatened 3, repeated-insult 4.
- Target-specific roast subjects: السيسي 11, لينا 4, الجيش 2, ندوش 2,
  المسيحي 2, كيسنجر 1, كارما 1, حادثة القطار 1, ضيوف اللايف 1, ميدو 1.

## Appendix B — rejected alternatives

- **LLM judge as the primary gate (§4.3):** correct tool, wrong
  version. Costs a call and seconds on the slowest path for marginal
  gain over the deterministic gate; kept ready behind the revisit
  trigger.
- **Sending the standalone line whenever the line is absent after
  retry:** rejected. A good lineless draft is a valid roast reply;
  discarding it for the bare line throws away a better answer. The
  standalone fallback fires only on a **present-but-misdirected**
  weave — the exact evil Seif named.
- **Tagging all 224 lines with gender/number:** rejected as scope
  creep. Only the lines the audit proved problematic get tags (8
  entries, §2.3); the gates default to masculine/singular, which is
  the Arabic unmarked default and matches the other ~216 lines.
- **Guessing target gender from the name in code:** rejected. Arabic
  names are not reliably gendered by string rules, and a wrong guess
  would silently serve feminine lines to men (the exact bug). The
  feminine signal comes only from the request's own wording
  (اشتمي / البنت / الست) or from Seif confirming a name.
- **Rewriting the bank lines themselves** (e.g. de-feminising ro-23):
  rejected. The lines are Bahgat's attested words or Seif's own
  submissions; the fix is selection, not editing the corpus.
