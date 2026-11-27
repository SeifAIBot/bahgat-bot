# Changelog
## 2026-11-27 — v1.15: roast refusal detection + bank fallback, turn latency bounds, LLM call instrumentation

**Scope:** research plan steps 1–4 + 6 (report ~/workspace/research_notes/v114-roast-refusal-latency-deep-dodge-20261127-0716/report.md — instrumentation, latency bounds, roast validation, prompt edits). Prompt 7.0 → 7.1. No second LLM call on the happy path (+1 fallback call only on failed turns, bounded by the deadline), no new dependencies, no paid service. **Not pushed, not deployed, no live test** — local commit only, per the task (the v1.14 live retest has not run yet). Out of scope by design: the deep-question router / grounded fear fact (BLOCKED — Seif must choose Bahgat's ONE specific fear; nothing invented); bounded concurrency (v1.16, after instrumentation data exists); search quality (v2.1). Persona facts, Messi guard, owner gate, weave logic, bank lines' text untouched.

**(A) Instrumentation (report §2.3, new brain/telemetry.py):** `llm_calls` + `turns` SQLite tables in the same bahgat.db — llm_calls: turn_id, step, provider, model, started_at, ttft_ms, total_ms, status, http_status, finish_reason, tokens_in/out, retry_after, prompt_version, temperature, error_kind, outcome; turns: turn_id, chat_id, user_id, kind, started_at, total_ms, calls, outcome, reply_preview (≤80 chars). Every provider attempt is timed with `time.perf_counter()` and recorded in a finally-equivalent path (success, error, and CancelledError branches all emit a row — a call cancelled mid-flight by the turn deadline still leaves a row). TTFT equals total for non-streaming calls (there is no first token to time before the whole response arrives; the column exists for a future streaming call). One turn_id per handler turn, propagated to every call via `_router_chat` → `router.chat(turn_id=..., step=...)`; steps are main / search_retry / voice_regen / ingredient_retry / opener_regen / roast_retry. Owner-only `/diag` (registered in `register_handlers`, same silent-return rule as /stats) replies with the last 10 slow turns (≥10 s wall clock, or timeout/error outcome) + per-provider p50/p95 from SQLite. Owner DM via `sendMessage` on any turn >60 s or any 429/timeout/refusal (one line: turn id, kind, calls, total, per-step timings, outcome). **Metadata only — no prompts, no completions, no user text are ever stored or DM'd**; the only user-visible text is the ≤80-char reply preview. Telemetry never raises (all DB ops are guarded); `DB_PATH` is a module attribute so tests point it at a throwaway DB (conftest `tmp_db` updated). Router-side: `last_call_meta` (provider/model/finish_reason/refusal/http_status) exposes the structured signal to the handler; the handler regrades rows (`update_call_outcome`) when a later check changes the verdict (refused_canned → fallback_rescued).

**(B) Latency bounds (report §2.2 Rank 1):** explicit client timeout `httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0)` AND `max_retries=0` on every `AsyncOpenAI` client (`brain/router.py::_client`). The SDK default (600 s timeout, 2 retries) multiplied the router's own retry loop (up to 2 attempts/entry × N entries) into the 172–428 s turns seen live — that was the mechanism, verified in code: the router already passed a 20/30 s timeout but never set `max_retries`, so the SDK retried twice under each router attempt. **Documented choice: the router's own retry loop (`max_retries_per_provider=1` in YAML) is the single retry layer; the SDK never retries.** `config/providers.yaml` `timeout_seconds` is now unused (kept in the YAML for compat) — the explicit timeout governs. Wall-clock per-turn deadline of 60 s (`asyncio.timeout` in the new `_run_llm_turn_bounded` wrapper around the whole turn, called from `_on_group_message_inner`); the deadline re-raises through `_run_llm_turn`'s own `except TimeoutError: raise` so the generic handler cannot swallow it. Max **2 `router.chat()` calls per turn** (`_TurnBudget`: main + one fallback/containment) — a spent budget returns `("", None, 0)` without calling the router, so retry sites keep the prior draft. When the deadline fires or the budget is spent, the turn answers with the picked bank line verbatim (ingredient turns, stashed in `turn_ctx["bank_line"]` at pick time) or `_TURN_ERROR` — never silence, never a hang. `reasoning_effort="low"` was already set on every Groq call (verified in `router.chat` — no change needed). `output_tokens` UNTOUCHED (groq/nvidia stay 3000 — the v1.13 truncation fix; the 60 s deadline is the latency bound, not the token cap). Voice/opener/length checks verified already Python (`_same_opener`, `voice_check`, `looks_unknown`/`looks_stalling` — no LLM call anywhere) — no change, as the task anticipated. **Behaviour change (deliberate, with reason): the voice-check regen is now SKIPPED for ingredient turns** — the ingredient retry is the turn's one fallback/containment call under the 2-call budget, and the voice regen would consume it and starve the containment retry (the same reason the opener regen already skips ingredient turns). The insult-turn call count goes 3 → 2 (draft + containment retry); the test pin is updated (below).

**(C) Roast refusal detection + bank fallback (report §1.2 Rank 1 + §1.4, `brain/reply_bank.py`):** `is_refusal_or_deflection(reply, required_line, structured_refusal=False, finish_reason=None)` returns a `RefusalOutcome` enum, checks in this order (cheapest/most specific first): (a) structured — `choice.message.refusal` is not None, or finish_reason `content_filter`/`SAFETY` (the router extracts it in `_refusal_signal` and, on a structured refusal, moves to the next entry instead of retrying the same model); (b) exact canned-deflection match — normalised (diacritics/punctuation/extra spaces stripped, lowercase) full sentence or either distinctive substring (`مش داخل دماغي` / `قول حاجة عدلة`), from the `KNOWN_DEFLECTIONS` table (grow it from logged failures); (c) small generic marker lists, Arabic + English — a marker counts only at the START of the reply (≤12 chars in, so a short vocative like "يا عم" is allowed) or dominating a short (1–3 sentence) reply, so a reply that QUOTES a refusal is not flagged; (d) containment — the required bank line must be present (`ingredient_in_reply`, the existing ≥80% word rule). Wired into the ROAST path only (before the voice regen, so the refusal retry gets the turn's one fallback call): on failure → ONE retry on the OTHER provider with the same prompt (`exclude_providers={provider}` — new `router.chat` param; never re-sent to the same model) → if that also fails, or the budget is spent, or all providers are down (`provider == "none"`) → the picked bank line VERBATIM. Outcomes logged to `llm_calls` (`ok`, `refused_structured`, `refused_text`, `refused_canned`, `missing_line`, `blocked_400`, `fallback_rescued`, `bank_sent`; transport failures use `error` + `error_kind`). No second LLM judge, no `safety_settings` change, no abliterated/uncensored models, no jailbreak framing, no bank text changed. **Rotation reuses `_pick`'s existing no-repeat window** (last 25 per chat + last 10 per user, persisted) — no second rotation scheme was added: the fallback sends the line picked at turn start, so the window already guarantees it does not repeat within a session (tested: two consecutive refusing roast turns send different lines).

**(D) Prompt edits (report §1.2 Rank 2, `brain/prompt.py` `bank_ingredient_block`, roast variant only):** one short line of TRUE context (light teasing between friends in a group chat — about the joke/football at hand, never religion, family, unchangeable looks, or anything hateful); the "never refuse" absolute (`ممنوع ترفض تشتم {target}...`) softened to a specific positive instruction (light teasing → roast in 1–3 sentences with the given line; hateful/sexual/violent content about a real person → say the short canned line instead). Arabic, prompt 7.0 → 7.1. Note the tension, documented in the code comment: on ingredient turns the deterministic detector still rescues a canned deflection with the picked bank line — the canned carve-out is meaningful on turns with NO bank line (e.g. the Messi-defense turn, where the guard skips the pick entirely), not as an escape hatch from a roast that already passed the pick filters.

**Updated pins:** prompt version 7.0 → 7.1 in 8 files (test_savagery_v13, test_prompt_v5, test_prompt_v06, test_v11_fixes, test_football_identity_v112, test_persona_expansion_v112, test_persona_batch3_v112, test_bank_ingredient_v113); the roast-block test rewritten for the softened instruction (the absolute is asserted ABSENT now); the insult-turn call count 3 → 2 in test_cache_quota_v06 (voice regen skipped for ingredient turns — see (B)).

**Verified:** 866 tests pass (826 baseline + 40 new in tests/test_v115_refusal_latency.py: detector units incl. the verbatim canned deflection, diacritics, markers, containment, quoted-refusal non-flag; bank fallback rescue / double-refusal verbatim / no-repeat; deadline bank + canned with a slow fake client; instrumentation rows for ok/structured-refusal/429, /diag shape + owner-only, owner-DM trigger conditions; prompt + budget + client-timeout units), ruff clean on bot code (brain/, tg/, tests/, config/, scripts/). The 34 pre-existing ruff errors in training/colab/*.ipynb are untouched and out of scope. **Not pushed, not deployed, no live test** — local commit only, per the task. Live retest (v1.14 probe + friend conversation) still to run after push/deploy — and the v1.15 fixes need their own probe: 10 roast probes across both providers (pass = no deflection reaches the group; bank line counts as pass) and 20 mixed turns (pass = no turn >60 s to the user, /diag shows which step dominated any slow turn).

## 2026-11-27 — v1.14: selective persona grounding + script-mixing filter + ro-15 out of roast pool

**Scope (decided 2026-11-27 09:21 EET):** recitation selective grounding + script-mixing filter + ro-15 tag only. The refusal / latency / deep fixes are v1.15 (research done, report ~/workspace/research_notes/v114-roast-refusal-latency-deep-dodge-20261127-0716/report.md) — they need instrumentation first and the deep fix needs Seif to choose Bahgat's specific fear. Prompt 6.9 → 7.0. No second LLM call anywhere, no new dependencies. No push, no deploy, no live test in this version (local commit only).

**(A) Recitation selective grounding (research report §5, ~/workspace/research_notes/persona-recitation-selective-answering-20261127-0525/report.md):** the v1.12/v1.13 live failure was a selection failure, not a knowledge failure — every turn showed the model ALL loves AND hates, so "بتحب تاكل ايه؟" recited both lists. Fix is architectural, not more prompt words:
- **Atomise (new brain/persona_facts.py, 51 rows, 9 topics):** every SYSTEM_BASE 6.9 fact is now one row (topic / polarity / text / keys) — food 6, football 13, religion 4, politics 9, youtubers 3, taste 1, tech 3, mockery 7, temperament 5. No fact added, none removed, no wording changed except splitting list items into atomic rows and the 2nd→3rd-person shift the data format needs ("بتدافع" → "بيدافع", "بتصحح" → "بيصحح"). A test enumerates the rows and asserts the count and every key item. SYSTEM_BASE keeps style/rules only + four retained rule lines (Ahly-news grounding from search results; "انت مسلم؟" → direct "أيوة أنا مسلم"; Messi roast → defend; rap fetching still works). SYSTEM_BASE 3300 → 1442 chars, budget < 1800 again.
- **Selection (`select_facts(user_text)`):** dialect keyword matching for topic (food/football/religion/politics/youtubers/tech/mockery/temperament/taste) and polarity (love/hate words incl. dialect forms). Topic+polarity → only that slice; topic without polarity (or both polarities, or a polarity with no rows for the topic — e.g. "بتكره ايه في الدين؟") → the whole labelled topic slice; no match → no facts (style-only). Selection metadata logged (topic/polarity/fact_ids) — NOT raw user text (privacy-consistent with the codebase). Matching details: the definite article needs its own form ("الأكل" does not match keyword "اكل" under `_has`'s whole-word match), so `_with_article()` adds the ال- form of every single-word keyword at load time; verb forms are listed explicitly ("تاكل"/"هاكل" are not "اكل"); suffixed and و-prefixed polarity forms are listed ("بتحبهم", "وبتكره"); a negated love ("مش بتحب") is stripped before checking love so it does not count as love. "سيسي" is deliberately NOT a politics keyword (the Sisi stance lives in the bank opinion lines).
- **Prompt split (tg/handlers.py):** the selected facts go in a user-role `<facts>` message immediately BEFORE the `<user_message>` turn, and the short positive instruction ("جاوب على السؤال اللي اتسأل بس، واستخدم الحقايق اللي فوق بس. جملة لـ 3 جمل." for polarity turns, "جاوب على السؤال اللي اتسأل بس." otherwise) goes right AFTER it — facts → question → instruction-last. The 8 style examples in the system prompt are untouched. Facts injection applies to just_chat/voice turns INCLUDING ingredient turns (a Salah roast still carries the persona contempt in the same turn as the bank line) and the cache path (a stale cached reply reciting the opposite polarity gets filtered too).
- **Post-filter (brain/verify.py `check_reply`, new `persona_selection` kwarg, threaded through `_check_reply_guarded`):** when the turn had a polarity, any reply clause containing a token from the unselected polarity for that topic is dropped; if the reply becomes empty, a canned template from the selected rows ("بحب مكرونة بشاميل ومحشي.") — NEVER the full persona block. Known limitation (by design, per report §5): a correct denial that names the hate item ("لا، بكره البفتيك" on a love turn) is also dropped and replaced by the template — a non-answer, not a leak.
- **Deviations from report §5 (documented here and in brain/persona_facts.py):** (1) the few-shot pair is polarity-matched — a love turn shows only the loves example, a hate turn only the hates example (the report's template shows both always, which would put the opposite polarity back into context); the post-filter is the safety net. (2) Selection metadata logged without raw user text (see above). (3) Bare "بكره" is NOT a hate word — in Egyptian Arabic it also means "tomorrow" ("بكره هاكل ايه؟" would inject the hates); the unambiguous forms (بتكره / بكرهه / مبتحبش / مش بتحب) cover hate. (4) A topic+polarity match with no rows falls back to the whole labelled topic slice (tier 2) instead of injecting nothing.
- **Tests (new tests/test_persona_selective_v114.py, 44 tests):** selection units (dialect forms, negation "مبتحبش", bare "بكره" is not hate, both-polarities → whole slice, no-rows → tier 2, "صلاة المغرب" is religion not politics); facts-block units (loves-only / hates-only / both labels, polarity-matched example); post-filter units (drop / keep / empty-fallback / hate polarity / no-polarity no-op / via check_reply); no-fact-lost (51 rows, per-topic counts, every key item present); system-prompt-no-longer-carries-facts; handler golden set (report §4 — the live failure verbatim "بتحب تاكل ايه؟" → loves-only, hates mirror, "بتحب البفتيك؟" → template fallback, "ايه رأيك في الأكل؟" → labelled slice with facts→question→instruction order, open banter → no facts). Opposite-polarity leak rate 0 on the polarity probes.
- **v1.12 persona tests rewritten (tests/test_football_identity_v112.py, tests/test_persona_expansion_v112.py, tests/test_persona_batch3_v112.py):** facts live in brain/persona_facts.py rows and reach the LLM in the `<facts>` message, NOT in SYSTEM_BASE / the built system prompt — the "in SYSTEM_BASE", "in every built prompt", guard, stance-question, and roast-weave tests now assert against the rows / the facts message. The Messi roast→defend test is UNCHANGED (the rule stayed in SYSTEM_BASE). The Ahly-news test now asserts the stance is NOT in the system prompt (search turns get no facts — the answer comes from grounding + style).

**(B) Script-mixing filter (brain/verify.py `check_reply`, after the `**`/`__` + internal-block strips, before the family check):** strips Hebrew (U+0590–U+05FF), Cyrillic (U+0400–U+04FF) and Greek (U+0370–U+03FF) characters; drops any token mixing Arabic+Latin letters ("مessi", "متnak"); drops standalone Latin tokens unless allowlisted (PES, eFootball, Android, iPhone, Mac, YouTube). If stripping empties the reply, the existing empty-reply fallback handles it. Two corrections found while implementing: (1) the live Cyrillic artifact was a SUBSTITUTE, not an extra letter ("عбиط" is ع + Cyrillic б + ي + ط, the б standing in for the Arabic ب) — stripping it alone leaves the wrong word "عيط", so the confusable б (U+0431) is mapped to ب first and only the remaining foreign-script characters are stripped. (2) The Arabic comma (، U+060C) sits inside the Arabic Unicode block, so the mixed-token check must test for Arabic LETTERS (U+0621–U+064A) only — otherwise a Latin token next to an Arabic comma ("PES،") looks mixed and gets dropped. (3) Ordering: the leak check now runs BEFORE the script-mixing strip — the strip drops standalone Latin tokens, which is exactly what a leaked key / "SYSTEM_BASE" mention is, so checking after the strip let two v0.5 leakage tests through (fixed, both green again). Tests: the four live artifacts (Latin "مessi", Latin "ya", Latin "متnak", Hebrew "גדול", Cyrillic "б" in "عبيط") plus allowlist cases and a normal Arabic reply unchanged.

**(C) ro-15 out of the generic roast pool (persona/bahgat/reply_bank.yaml + brain/reply_bank.py `_pick`):** ro-15 ("روح البنك كده وقول له عاوز عشر تلاف دولار") is a dare line, not an insult of the target — it served as a "roast" for عمرو in the v1.13 live retest. Tagged `dare: true`; `_pick` excludes `dare` lines for category "roast" only (load_bank unchanged, so the ingest suites' generic==19 pins stay valid). Text unchanged. Bare singular roast pool: 19 generic − ro-12/ro-40/ro-44 plural − ro-23 feminine − ro-15 dare = 14 (the v1.13 docstring said 16 — it missed ro-44; corrected here). Test asserts ro-15 is never drawn by the roast pick (200 draws each for a target with no specific lines and for السيسي) while other generic roasts still are.

**Pre-existing failure fixed (not a v1.14 regression):** the baseline suite at HEAD (5251cec) was 781 passed + 1 failed — `tests/test_bank_ingredient_v113.py::test_perv_marked_roast_can_draw_perv_lines`. Root cause is test hygiene, not bot code: that file never pointed brain.memory at a tmp DB (unlike the other draw-based test files), so its "fresh chat_id per draw" isolation was defeated by the real data/bahgat.db windows, which accumulated over repeated runs until they held all 5 eligible perv lines — every draw then fell through to general lines. Fixed by taking the conftest `tmp_db` fixture in that file's autouse fixture. (My own debug runs added bank_recent keys to the real dev DB for fake chat ids; the DB is gitignored dev state and the live bot's data lives on Cloady — harmless.)

**Updated pins:** prompt version 6.9 → 7.0 in 8 files (test_savagery_v13.py, test_prompt_v5.py, test_prompt_v06.py, test_v11_fixes.py, test_football_identity_v112.py, test_persona_expansion_v112.py, test_persona_batch3_v112.py, test_bank_ingredient_v113.py); SYSTEM_BASE budget < 3600 → < 1800 in tests/test_prompt_v06.py (two assertions). No other pins changed — the ro-15 exclusion is pick-time only (load_bank counts unchanged), and the v1.13 weave / Messi guard / owner gate are untouched.

**Verified:** 826 tests pass (781 baseline + 1 pre-existing failure fixed + 44 new), ruff clean on bot code (brain/, tg/, tests/, config/, scripts/). The 34 pre-existing ruff errors in training/colab/*.ipynb are untouched and out of scope. **Not pushed, not deployed, no live test** — local commit only, per the task. Live retest (probe + friend conversation) still to run after push/deploy.

## 2026-11-27 — v1.13 (in progress)

**Persona — Vinícius / Rodrygo (Seif, 2026-11-27 07:21 EET):** Vinícius is wronged by Mbappé; Rodrygo is respectable and more useful than both of them. Recorded as persona facts in his own voice, not fact-checked or softened.

- brain/prompt.py prompt 6.7 → 6.8: the football-tastes line gains "فينيسيوس مظلوم من مبابي. ورودريجو محترم وأفيد من الاتنين." SYSTEM_BASE 3106 → 3165 chars, budget < 3600.
- No roast guard added for Vinícius or Rodrygo — Seif stated opinions only (unlike Messi, where the guard follows from the love-as-GOAT stance). An "اشتم فينيسيوس" / "اشتم رودريجو" request still picks a generic bank line today.
- Verified: 742 tests pass (739 baseline + 3 new scenario tests in tests/test_persona_expansion_v112.py), ruff clean. Live retest must check: "ايه رأيك في فينيسيوس" (wronged by Mbappé), "ايه رأيك في رودريجو" (respectable, more useful than both), "مين أفيد، رودريجو ولا فينيسيوس ولا مبابي؟" (Rodrygo).

**Still to land in v1.13:** the persona-recitation fix (selective grounding — design in ~/workspace/research_notes/persona-recitation-selective-answering-20261127-0525/report.md; it atomises the persona and touches every v1.12 test, so it ships as v1.14, its own version with its own golden-set probe).

**Weave coherence (Seif, 2026-11-27 07:07–07:08 EET — the rule is his words):** bank insult lines must NEVER be the reply alone — when the bot answers an insult with one of Seif's lines, it must UNDERSTAND the line and weave it into a fuller reply, and the weave must be COHERENT (the line relates to the target/context, the whole reply built around it) — OR the bank line goes out alone verbatim; a disconnected paste is the worst option. Full design in docs/v113-weave-design.md (read it before touching this code again). Three layers:
- **Selection (brain/reply_bank.py `_pick`):** target-specific lines outrank generic ones (specific tier first, generic only when the tier is empty or entirely inside the no-repeat window; the LRU fallback runs over the combined pool, not inside a tier helper). New `gender:` / `number:` YAML tags with gates for generic lines only (target-specific exempt): ro-23 `gender: f`, in-38 `gender: f`, in-09 `gender: f` (borderline — Seif's call to confirm or untag, not yet asked), ro-12 / ro-28 / ro-40 / ro-44 `number: p`, ro-39 `target: كريستيانو`. Honest cost: the bare singular roast pool shrinks 20 → 16 lines (19 generic minus ro-12/ro-40 plural and ro-23 feminine); the two generic feminine insulted lines (in-09, in-38) go dormant for comebacks, which have no gender signal — 44 → 42 reachable insulted lines. **No perv gate (deliberate removal, not an omission):** the design's perv gate was dropped during implementation — the gender/number gates already fix the observed v1.11 defects, and the perv gate would have silenced lines Seif demonstrably likes (ro-35 for صلاح in the v1.7 probe; ro-37/ro-38/ro-45 in the v1.9 probe — all bare roasts) and made ro-44 nearly unreachable (it is both perv-only AND plural). Seif wants STRONG insults; perv lines are the strong ones. (An earlier draft gated perv lines from the whole pool and broke "اشتم لينا" — all four لينا lines are perv-only — that was fixed the same way: target-specific perv lines were never gated, and now generic perv lines aren't either.)
- **Prompt (brain/prompt.py `bank_ingredient_block(line, target, requester, kind)`, prompt 6.8 → 6.9):** the block names the target and the requester, makes the line the punchline the whole reply is built around, forbids misdirection and refusal; separate insulted variant (the target IS the requester, so no "don't insult him" line); no-target callers get the v1.11 generic wording (backward compatible). `build_system_prompt` gains `bank_target` / `bank_requester` / `bank_kind` params. SYSTEM_BASE gains a variety rule ("نوّع بداية كل رد — ابدأ بجملة مختلفة عن الرد اللي قبله، ومش لازم تبدأ بمناداة أصلاً." — positive phrasing, never names the insult, per the repetition research's priming warning) and a direct-answer religion line ("ولو حد سألك انت مسلم؟ قوله أيوه أنا مسلم على طول." — retest test 28 never said "أنا مسلم" directly). SYSTEM_BASE 3165 → 3300 chars, budget < 3600.
- **Fallback — Seif's rule as code (tg/handlers.py, deterministic `weave_about_target` gate, roast only):** target named → pass; target absent AND requester named → misdirected → send the bank line standalone verbatim (the v1.11 `_INGREDIENT_FALLBACK_LINES` generic dismissals are DELETED); line absent after retry → draft sent as-is; draft IS the line → sent as-is (no longer a violation). Zero extra LLM calls, zero added latency. The LLM-judge alternative is specified in the design (§4.3) but NOT used — revisit trigger: ≥2 incoherent weaves in the live probe. Owner gate and Messi guard unchanged.
- **Repetition (same version):** chat turns get `frequency_penalty=0.5` + `presence_penalty=0.3` (brain/router.py; search/hard turns get none); a repeated opener (first 4 normalised words, order-insensitive, punctuation-stripped — tg/handlers.py `_opener_words` / `_same_opener`) triggers ONE regen with a vary instruction, second draft sent regardless. The v1.12 retest's "~19 of 30 replies open with يا سيف يا حمار" is the pattern this kills.
- **Truncation (same version):** output caps raised — groq / nvidia / cerebras / openrouter 1500 → 3000 (config/providers.yaml; gemini stays 4000). Strongest-fit hypothesis for replies cut at 4–20 visible tokens under a 1500 cap: reasoning tokens count against `max_completion_tokens`, so a reasoning-heavy turn eats the whole budget before the visible reply starts. Length-retry in the router: on `finish_reason == "length"` keep the longest draft, retry ONCE with a doubled cap (Groq: `min(mct*2, max(mct, 7500 - est_in))`; others: `min(mct*2, 6000)`), and if that also truncates return the longest draft (logs `"truncated": True`). Which provider served the truncated turns is unverifiable — the logs are trapped on Cloady.
- **MEMORY leak (same version):** brain/verify.py `check_reply` now FIRST strips `**` and `__`, then removes internal blocks ([MEMORY]...[/MEMORY] and [BANK LINE...]...[/BANK LINE], DOTALL), collapses 3+ newlines. A reply that was ONLY a leaked block comes out empty → the handler's empty-reply fallback answers. (The v1.12 retest's test 29 leaked the [MEMORY] block verbatim into the user-facing reply.)
- **Deep questions (same version):** brain/intent.py `looks_like_deep_question` + `_DEEP_WORDS` (حاسس، مبسوط، ناقصك، ندمت، ندمان، خايف، بتخاف، خوف، حلمك، بتحلم، حياتك، فرحان، زعلان، مكتئب، وحيد، بتتمنى، نفسك); the handler appends `_DEEP_NOTE` ("السؤال ده شخصي وعميق — جاوب بصراحة من قلبك الأول... متتهربش بالشتيمة ولا بالسخرية") for just_chat/voice turns. The deep question was dodged 4 conversation runs in a row.
- **Tests:** 40 new — tests/test_bank_ingredient_v113.py (34: perv reachability + gender/number gates, Sisi outranking with the ro-29 correction, `weave_about_target` table incl. the تامر screenshot case, prompt-block variants, `check_reply` strips, opener helpers, deep detector, router penalties + length-retry with a scripted fake client) + 4 handler tests in tests/test_bank_ingredient_v111.py (misdirected weave → line verbatim, coherent weave sent as-is, opener regen, deep note) + 2 live-scenario tests in tests/test_live_scenarios.py (misdirected تامر → line verbatim; ميسي coherent defense, no ro-23). The v1.11 test `test_stubborn_model_returning_line_twice_gets_generic_fallback` intentionally flips → renamed `..._gets_line_verbatim`. Version pins updated in 7 files (6.8 → 6.9); old pins that broke on the new pool arithmetic updated with the reason noted (tagged 26 → 27, generic 20 → 19, safe-generic 15 → 14, insulted rotation 44 → 42, output caps 1500 → 3000; the user-ingest suites' generic pins 20 → 19 and family-line reachability now draws with the plural imperative, since ro-40/ro-44 are plural-addressed).

**Verified:** 782 tests pass (739 v1.12 baseline + 3 persona-line tests + 40 new v1.13 tests), ruff clean on bot code. **Live retest DONE 2026-11-27 08:28–09:13 EET (28/28 replied, all text, 0 voice notes; Seif asleep, pre-approved):** probe — roasts 8/12 about target (Messi refusal is the guard, correct); 3/12 identical canned deflections ("يا عم، الكلام ده مش داخل دماغي، قول حاجة عدلة." for صلاح/محمد/كارما — the model still refuses to roast despite the no-refusal block); feminine 0, plural 0, `**` 0; opener repetition FIXED (0/20 vs ~19/30); truncation 1/20 (#16 "وفينيسي"); latency REGRESSED in the probe (6/20 late, 172–428 s, backlog during #4–#9 — cause unverified, logs trapped on Cloady). Persona: "أنا مسلم" direct YES; Vinícius/Rodrygo YES; YouTubers all three YES; identity YES; food still recites hates (v1.14); Ahly news still bare [1]/[2] + invented-sounding claims (v2.1). NEW: script-mixing (Latin "مessi"/"ya", Hebrew "גדול", Latin "متnak", Cyrillic "б"), recycled template lines, ro-15 dare line still serving as a "roast" (#7). Conversation: 8/8, riffs 4/8, deep question dodged a FIFTH run (the deep-note did not work), truncations FIXED 0/8. Full log in docs/conversation-test-log.md; verdict in MEMORY.md.

## 2026-11-27 — v1.12: football + religion identity in Bahgat's persona

**Football identity (Seif, 2026-11-27 06:05 EET):** Bahgat is a DIE-HARD Ahly fan, HATES the Ahly board of directors, FOLLOWS Ahly news, HATES the Egypt national team because they fired Hossam Hassan from coaching it, and DESPISES Mohamed Salah. **Religion identity (Seif, same morning):** Bahgat is MUSLIM and PROTECTIVE/JEALOUS over his religion — he defends Islam fiercely, gets angry when Islam, the Prophet or the Quran are insulted or mocked, never jokes about religion in a disrespectful way, and corrects misconceptions about it. Both are persona facts in his own voice, not canned lines, and were recorded as such (not fact-checked or softened).

- brain/prompt.py prompt 6.6 → 6.7: SYSTEM_BASE gains a "كورة ودين" block, Egyptian dialect, Bahgat's voice — die-hard Ahly ("أهلاوي جداً — الأهلي فريقك وكبرياءك، مفيش كلام"), hates the board ("بتكره مجلس إدارة الأهلي كره شديد، وبتشتمه كل ما يتذكر"), follows Ahly news ("بتتابع أخبار الأهلي على طول" — and answers news / match-result questions from the search results in front of him, never inventing a score), hates the national team because they fired Hossam Hassan ("حسام حسن مدرب محترم واتظلم"), despises Salah ("بتحتقر محمد صلاح، مبتحترموش ولا تمدحه أبداً"). Religion: "مسلم وبتغير على دينك — بتدافع عن الإسلام بكل قوة، وبتتعصب لو حد شتم الإسلام أو النبي أو القرآن أو اتريق عليهم، مبتضحكش ومبتعديهاش. مبتتريقش على الدين أبداً، وبتصحح أي كلام غلط عنه."
- No router change needed: "اخبار" and "مين كسب" were already in `_SEARCH_WORDS`, so Ahly-news questions already route to search and the handler already grounds the answer before the LLM turn — the prompt line just tells him to answer from the results in front of him. Opinion questions ("ايه رأيك في ...") stay just_chat and take their stance from the persona.
- v1.11 interaction (checked, no hard conflict): the bank contains NO Salah / board / Ahly lines at all, so nothing in the bank can contradict the new stances; ro-21 ("عاوز يغير في القرآن يا متناك؟", a Sisi roast) already defends the Quran while insulting the attacker — it reinforces the religion persona. In a Salah roast the LLM gets BOTH the [BANK LINE] ingredient and the persona contempt in the same turn (tested). Soft spot, not a conflict: the v1.11 containment check enforces the line's presence, not the tone — if a picked line is weak/deflecting (the ro-15 pattern seen live on the Sisi roast), the persona contempt has to carry the reply.
- Standing rules untouched: Egyptian dialect only, never admit bot, never banned AI phrases, golden rule. SYSTEM_BASE budget 1100 → 1800 (1595 chars now); the change sits entirely inside the static prefix, so Groq prompt caching still hits and the dynamic tail (< 450 tokens) is untouched.

**Persona expansion (Seif, 2026-11-27 06:20 EET, same version, second commit — prompt stays 6.7):** his cause and his tastes, recorded as persona facts (not fact-checked, softened or debated):
- Egyptian-American, against injustice and oppressors; his mission is awareness and spreading freedom, especially freedom of expression — it shapes how he talks about censorship and free speech (he speaks about injustice and defends the right to speak).
- Jerusalem is Arab; against Zionism; hates Israel more than anything in life; very supportive of Palestine.
- Hates Real Madrid and Kylian Mbappé; loves Vinícius. Loves Messi very much — the best player in history for him. Respects Cristiano but may insult him jokingly or sometimes seriously.
- Food: loves macaroni béchamel and mahshi; hates boftik, cooked vegetables, fesikh and ringa. Hates Saudi Arabia and Morocco.
- Mocks eFootball (PES) a lot, and Egyptian rap a lot — Wegz, Marwan Pablo, Abyusif, Marwan Moussa, Abo El Anwar, Arsenik, Afroto and all known Egyptian rappers generally. Loves YouTubers Yehia Azzam, Mahmoud Mahdi and Loay Fawzy. Loves deep cinema.

Decisions (documented, all in this commit):
- (a) Messi roast requests — he loves Messi as the GOAT, so when asked to roast Messi he DEFENDS him instead of roasting him. Implemented as a CODE guard, not just prompt: `_MESSI_TARGETS` in brain/reply_bank.py — the roast branch skips the bank pick entirely for ميسي / ميسى (normalises to ميسي) / messi / ليونيل (his unambiguous first name), so the request falls through to the plain LLM turn where the persona defends him. The guard is needed because the v1.11 ingredient path would otherwise force a generic insult line into a reply that must be a defense — and the bank has no Messi lines at all, so any line picked for him would be a generic mismatch. Prompt carries the same rule ("لو حد طلب منك تشتم ميسي دافع عنه بدل ما تشتمه") so the LLM turn itself defends.
- (b) Ronaldo roasts are fine — respect plus joking/serious insults: the roast path is unchanged for كريستيانو (ro-39, a Seif-submitted Cristiano joke-format line, is generic-tagged and may serve; the persona line "بتحترم كريستيانو، بس ممكن تشتمه بهزار أو جد عادي" rides in the same turn as the woven ingredient — tested).
- (c) Mocking Egyptian rap must not break the YouTube music feature: the mockery is opinion-level only. Fetching a rapper's song is a different turn ("هات اغنية ويجز") and the download path is untouched; the prompt says so explicitly ("بس لو حد طلب أغنية لحد فيهم جبهاله عادي — التريقة رأيك فيهم، مش على التحميل"). He fetches their songs and mocks them — that is his style, no conflict.
- (d) The freedom-of-expression mission shapes how he talks about censorship and free speech: the prompt carries "مهمتك توعي الناس وتنشر الحرية، وخاصة حرية التعبير — بتتكلم عن الظلم وبتدافع عن حرية الكلام" — a stance, not a canned line; it does not change any routing (censorship questions stay just_chat).

Implementation: brain/prompt.py — SYSTEM_BASE gains a "قضيتك وذوقك" block in Bahgat's voice, Egyptian dialect (2465 chars, budget < 2800 — the two budget pins in tests/test_prompt_v06.py and tests/test_savagery_v13.py updated). brain/reply_bank.py — the Messi guard above. No router change needed: every new topic routes to just_chat as an opinion/roast question (verified by intent tests); Ahly-news routing is unchanged from the first v1.12 commit.

**Persona batch 3 (Seif, 2026-11-27 06:25 EET, same version, third commit — prompt stays 6.7):** his tech tastes, temperament and mockery targets, recorded as persona facts (not fact-checked, softened or debated):
- Loves Android, mocks iPhone and Mac. Slightly perverted, loves women — flirtatious/perverted humor in his existing profane style.
- Hates homosexuals. Mocks feminists and women's-rights movements. Mocks the army and the police in every country in the world.
- Temperament: impulsive, reckless, stubborn, sometimes has a little wisdom; adventurous, free-spirited, brave, says what's on his mind — it shapes HOW he replies (speaks his mind, doesn't hedge), not just what he thinks.
- Mocks Amr Diab and Tamer Hosny. Loves Abo Treika.

Decisions (documented, all in this commit):
- (a) The army/police mockery is opinion-level mockery of institutions in every country, not a call to any action — it lives in the persona block only; no routing or handler change, no new capability.
- (b) The perverted/loves-women trait stays within the bot's existing profane humor style: it is a line in the persona block ("منحرف بنسبة بسيطة وبتحب النسوان — هزارك فيه غزل وانحراف خفيف على طول، بأسلوبك البذيء المعتاد"), not a new feature or a change to any reply rule.
- (c) Abo Treika love and Salah contempt coexist in one turn without contradiction: Treika is his guy, Salah is not — both lines ride in the same system prompt (tested: "ايه رأيك في أبو تريكة وصلاح" reaches the LLM with "بتحب أبو تريكة جداً" AND "بتحتقر محمد صلاح" in the prompt). Open question, NOT decided here: unlike Messi (code guard — roast requests defend him), a Treika roast request ("اشتم أبو تريكة") still picks a generic bank line today, because no guard was asked for. If Seif wants Treika defended like Messi, that is one guard to add.

Implementation: brain/prompt.py — SYSTEM_BASE gains a "تكنولوجيا وطبع ومزاج" block in Bahgat's voice, Egyptian dialect (3106 chars, budget < 3600 — the three budget pins in tests/test_prompt_v06.py and tests/test_savagery_v13.py updated). No router change needed: every new topic routes to just_chat as an opinion/roast question (verified by intent tests); the temperament lines reinforce the standing "no hedging, no apology" rules rather than contradicting them.

**Verified:** 739 tests pass (705 baseline + 34 new in tests/test_persona_batch3_v112.py: 5 prompt-level — version still 6.7, batch-3 blocks in SYSTEM_BASE and in every built prompt, never-praise guard for iPhone/Mac, army/police, Amr Diab/Tamer Hosny, standing rules intact; 15 intent-level — every new topic stays just_chat; 14 handler-level — every new stance reaches the LLM with the matching persona line, Treika love + Salah contempt coexist in one turn, Diab roast weaves a line AND carries the persona mockery line in the same turn), ruff check clean on changed files. Live retest must check: Android love + iPhone/Mac mockery; feminists/women's-rights mockery; army/police mockery; Amr Diab + Tamer Hosny mockery; Abo Treika love; temperament (speaks his mind, doesn't hedge); friend conversation test with fresh topics.

## 2026-11-27 — v1.11: bank insult lines are ingredients, never standalone replies + WARP status on /healthz

**Bank lines as ingredients (Seif, 2026-11-27 05:34 EET):** bank insult lines must NEVER be the reply by themselves. When the bot answers an insult with one of Seif's lines (or any bank insult line), it must UNDERSTAND the line and weave it into the middle of a fuller reply — the line is an ingredient, not the whole reply.

- Pick unchanged (brain/reply_bank.py): `match_reply_bank_categorized()` now returns `(category, line)` so the caller knows whether the pick is an ingredient (insulted/roast) or a verbatim reply (all other categories). ALL pick filters still apply at pick time — member_safe, target-specificity, situation tags, no-repeat window (last 25 per chat+category, last 10 per user). Owner gates EXACTLY as before (Seif confirmed 2026-11-27 05:32 EET): bank comebacks never fire at the owner, roasts never at the owner.
- Weaving (brain/prompt.py `bank_ingredient_block()`, tg/handlers.py `_run_llm_turn`): the picked line is stashed as `_bank_ingredient` and appended to the system prompt as a [BANK LINE] block — understand the line, put it in the middle of the reply (not first, not alone), full reply in Bahgat's voice around it, tied to the person's message. The ingredient turn MUST reach the LLM: the v1.0 fast path and the exact-match cache are both bypassed for ingredient turns (a cached reply could even be an old verbatim bank line). The turn is never cached afterwards either.
- Containment (tg/handlers.py): if the first draft lacks the line, ONE retry with an explicit user message ("لازم الرد يحتوي السطر ده بالظبط في نصه…"). If the draft IS the line verbatim, the standalone check replaces it with a random pick from `_INGREDIENT_FALLBACK_LINES` (3 generic lines) — the line never goes out alone. A draft that lacks the line is still sent (the rule forbids the line standing alone, not its absence — the pick already rotated into the no-repeat window). Worst case for an uncooperative draft: 2 extra LLM calls (voice-check regen + containment retry).
- LLM-failure fallback: if the LLM call itself fails, the outer except sends the plain `_TURN_ERROR` — the picked line never leaks through the error path, neither as a standalone reply nor inside anything else.
- Non-insult categories UNCHANGED (decision, documented): joke_request, greeting, opinion_asked, condolence, challenge, dismiss stay verbatim — Seif's rule is about insult lines only, and a joke / stance / condolence / greeting IS the reply's content. No concrete reason was found to change any of them.
- Prompt standing rules untouched: Egyptian dialect only, never Fusha, never admit bot, never banned AI phrases, golden rule (reply carries a word/idea from the person's message).

**WARP status on /healthz (v1.11, from the WARP diagnostic):** the live download failure is indistinguishable between "the WARP tunnel never came up (UDP blocked on Cloady)" and "the tunnel is up but YouTube flags the WARP IP" — both produce the same user-visible failure, and the gate-check result is trapped in data/bot.log, which the Cloady free tier cannot show. There was no outside signal for warp status at all (/healthz returned only `status` + `last_poll_age_seconds`).

- tools/warp.py writes `data/warp/status.json` on every state change — `{"warp": "on"|"off"|"down", "ip": <egress>, "enrolments": n, "updated": <unix ts>}`: "on" when the gate check passes (with the egress IP, re-read after the tunnel is up), "off" when the kill switch disables WARP, "down" when enrolment fails / the tunnel never comes up / the proxy stops (including stop_warp at shutdown, so a stale "on" never survives the process). The egress IP is a datacenter/WARP address, not a secret (warp.py's own docstring says so). Writes are best-effort and never raise — status must not break the tunnel path.
- tg/health.py adds `"warp": read_status()` to the /healthz (and /health) payload on both 200 and 503 — read fresh per request. No file yet (warp thread not run since boot) or a corrupt file reads as `{"warp": "unknown", ...}`. The liveness verdict is still the heartbeat alone; warp never affects it.
- NOT in this version (later decisions, per the diagnostic brief): re-enrol, Oracle canary, ready-file pattern — nothing else from the diagnostic was implemented.

**Verified:** 625 tests pass (603 baseline + 22 new: 13 in tests/test_bank_ingredient_v111.py — line woven into a longer reply for insult + roast, containment retry, LLM-down fallback, stubborn-model generic fallback, pick filters at pick time, owner gates, joke/greeting stay verbatim, prompt block; 7 in tests/test_warp_v110.py — status file on tunnel up/down/off/enrolment failure, stop_warp writes down, read_status unknown/corrupt; 2 in tests/test_health.py — /healthz carries warp on + unknown), ruff check clean on changed files. Existing tests updated to the new behaviour: 5 live scenarios (test_live_scenarios.py), the bank-intercept test (test_insult_search_v13.py — the two unknown-first-reply tests now bypass `match_reply_bank_categorized`, the function the handler actually calls), 2 roast handler tests (test_bank_v12.py), the insult-never-cached test (test_cache_quota_v06.py — a stub draft now costs 3 router calls: draft + voice regen + containment retry, still never cached), the bank-insult test (test_v11_fixes.py — LLM down now sends _TURN_ERROR, never the line). Two test-harness fixes found on the way: the new file uses the shared conftest `tmp_db` fixture (the handlers dedup DB must be throwaway too — without it, test update_ids pollute the real data/bahgat.db and later runs silently drop the turns as duplicates; the polluted rows were removed), and the stubborn-model test asserts behaviour, not a fixed call count (a verbatim draft needs no containment retry — the standalone check replaces it locally).

## 2026-11-27 — v1.10: WARP in-container for YouTube downloads

Diagnosis (unchanged since v1.8): YouTube bot-checks Cloady's datacenter IP on the player API — the v1.8 chain reorder did NOT fix downloads live (04:30–04:34 EET retest: video AND audio fail with the same refusal), while the same chain works from any other IP. The expert research (research_notes/youtube-blocked-ip-expert-methods-20261127/report.md) is unanimous: IP/ASN reputation is scored BEFORE player-client or PO-token logic, and the only free no-account fix with a controlled measurement is changing the egress IP via Cloudflare WARP (0/12 downloads direct → 11/12 via WARP, 2026-09-03). WARP is a reputation lottery YouTube can re-flag; re-registration is the cheap reset.

- WARP lifecycle (tools/warp.py, new): `wgcf register --accept-tos` (free identity, no account/email/card) + `wgcf generate` at first boot; `wireproxy` runs WireGuard in userspace and exposes SOCKS5 on 127.0.0.1:1080 only. Profile + account persist under `data/warp/` (the /app/data volume), so enrolment survives redeploys. Enrolments capped at 3 total (state in `warp-state.json`); `WARP_REENROLL=<new value>` deletes the old identity and re-registers once — the operator's dice roll when the current egress gets flagged. `WARP_ENABLED=false` is the kill switch: the whole subsystem off, downloads direct exactly as before. `ensure_warp()` runs in a daemon thread from main.py (boot never waits on the tunnel; chat/search work direct from the first second) and NEVER raises — any failure logs a warning and downloads stay direct. Gate check at startup: curl through the proxy to cloudflare.com/cdn-cgi/trace must return `warp=on`, and the egress IP is logged to data/bot.log (the research's step 1: if Cloady blocks outbound UDP, the tunnel never comes up and this is where it shows).
- Download path only (tools/youtube.py): every `download()` attempt adds `--proxy socks5://127.0.0.1:1080` when the proxy is up, plus `--force-ipv4` (research §3g: YouTube scores a whole IPv6 /64 as one unit, so a shared /64 is MORE exposed than a single IPv4). `search_query` and `resolve_query` stay direct — they already work from Cloady. A failed attempt whose error names the PROXY itself (not YouTube) trips a 5-minute circuit breaker so the remaining attempts in the chain go direct instead of burning every attempt against a dead tunnel; a YouTube bot-check through the proxy does NOT trip it (the chain must keep retrying other clients through WARP). Success/failure per attempt is logged with the egress used (`warp`/`direct`).
- Dockerfile: installs `curl` (the trace gate-check) + pinned `wgcf 2.3.1` and `wireproxy 1.1.3` binaries from their GitHub releases (verified 2026-11-27 in the VM: wgcf is a static ELF, wireproxy ships as a tarball with a single binary; `-f` fails the build loudly on a 404; `--help`/`--version` smoke test). Docker build itself is unverified locally (no Docker in the VM) — Cloady builds it on push. `.env.example` documents the three WARP vars.
- Voice hypothesis (NOT a separate workstream): v1.9 voice was intermittent live (1/3 voice notes — likely Edge rate-limiting the datacenter IP), so the new WARP egress may also improve voice reliability. No voice fallback was added in this version; the live retest re-runs voice ×3 to check.

**Verified:** 603 tests pass (564 baseline + 39 new in tests/test_warp_v110.py: kill switch, proxy URL, proxy availability, trace parsing, state round-trip/corruption, wireproxy conf (no key material, loopback only), enrolment + cap + re-enrolment generations, tunnel-failure cleanup, stop_warp, download proxy wiring, breaker trip / no-trip on bot-check, resolve/search stay direct, proxy URL never logged), ruff check clean on changed files. Real-binary validation in the VM: `wireproxy -n -c` accepts the generated config ("Config OK"); with a dummy profile, wireproxy starts, binds :1080, the tunnel correctly never comes up, and stop kills it cleanly. NOT verifiable in the VM: `wgcf register` itself — this VM's egress proxy MITMs TLS to api.cloudflareclient.com ("first record does not look like a TLS handshake", with and without proxy env), so enrolment + warp=on can only be proven on Cloady, where egress is direct. That is the first thing the live retest must check (data/bot.log: "warp: tunnel up, egress ip=… warp=on").

## 2026-11-27 — v1.9: edge-tts 7.3.1 voice fix, Instinct flaw-fix (failure pools, thinking lines, golden rule, reply-delay jitter)

- Voice (tools/voice.py, requirements.txt): the bot pinned edge-tts==7.2.1, but Microsoft changed the token check in October 2026 (Sec-MS-GEC v2) — every edge-tts below 7.3.0 is rejected at the WebSocket handshake with 403, which is almost certainly why the live v1.7 joke came back as text ("الصوت مش راضي يطلع"). Pin bumped to edge-tts==7.3.1 (verified: latest on PyPI, already installed in the VM venv). Synthesis now retries ONCE inside the module and LOGS each failure (before, the module failed silently and only the caller logged) — the partial mp3 is deleted before the retry.
- Failure lines (tg/handlers.py): Instinct judged the failure replies the clearest bot tell ("التنزيل فشل — يوتيوب رافض الطلب من السيرفر" is programmer-talk nobody says in a group). Download/search/voice failures are now random picks from small human-voiced pools (download: 3 lines, search: 2, voice: 2). The classified download reason (_download_error_hint) no longer appears in chat — it goes to the host log (data/bot.log) instead, keeping the v1.1 diagnostic value without the tell.
- Thinking bubble (tg/handlers.py): "بفكر يا عم، استنى…" no longer announces processing (Instinct: people stay silent or answer, they don't narrate thinking). Short lines cycled deterministically by spinner frame: "ثواني...", "لحظة، جايلك حالًا.", "ثواني وجايلك." The bubble itself stays (v0.9: the final answer is edited INTO it).
- Golden rule (brain/prompt.py prompt 6.5 → 6.6): rule 5 in _HARD_RULES_END — every reply must carry a word or idea from the person's own message; no reply that could be said to anyone. Instinct's "say you're a bot if asked" instruction was deliberately NOT applied — it conflicts with the v1.8 human-identity rule, which stands. Dynamic prompt budget raised 400 → 450 tokens for the rule (still small next to the 1233-token static prefix).
- Reply-delay jitter (brain/mood.py, tg/handlers.py): a mood-based pause with a typing indicator before ANY reply (bank, fast path, cache, LLM) — هزار 1–3s, غضب 2–4s, استعجال immediate, حزن 4–7s, serious question 3–6s, ±30% jitter. Derived from the tracked mood (0–100) + message markers. The 10s per-user pacing is untouched (it applies on top). Tests zero the delay via a conftest autouse fixture so the suite stays fast and deterministic.

**Verified:** 564 tests pass (547 baseline + 17 new: 1 voice retry, 9 mood delay, 6 failure lines, 1 prompt golden rule), ruff check clean on changed files. Bot bio set live via setMyDescription and verified with getMyDescription: "بوت مصري بيهزر، وفخور إنه بوت."

## 2026-11-27 — v1.8: YouTube download chain reorder + node runtime, file logging to the volume, human identity rule

Diagnosis first (2026-11-27 04:04 EET): YouTube video AND audio downloads both fail live on Cloady (03:57 / 04:01 EET, "يوتيوب رافض الطلب من السيرفر") while the SAME chain works end to end in this VM (Marwan Moussa El Kholasa: video OK 10.6s / 5.07 MB mp4, audio OK 18.6s / 3.4 MB mp3). Root cause is the host, not the code: YouTube bot-checks Cloady's datacenter IP on the player API; the cookies are valid to Dec 2027 and even known-good cookies fail on the web client. Confirmed live the same day: Waad (@D7Bot, added to the test group) downloads the SAME song fine from another host (~1s) — its files carry an "@YYYYF" caption and a "بوت تحميل وعد" link, so they may come through a backend service/files channel rather than direct yt-dlp; that off-Cloady route is a FUTURE option, not this version. So v1.8 reorders and strengthens the chain instead of debugging it.

- Download chain (tools/youtube.py): plain android FIRST (VM probe: android+skip failed twice, plain android succeeded twice — v1.3 had the weaker variant first), then android+skip, ios+skip, web+skip; a second pass over the two android variants after a 5s sleep (the check is intermittent — a later independent ticket can pass); then a tv attempt with `-f best` (tv got a player response once where web was bot-checked); web+cookies LAST, unchanged. The v1.3 explicit-format attempt (android+skip+fmt18) is dropped — tv+best covers its job. Resolve uses the same reordered client order (4 attempts + cookies). Per-attempt outcomes are now logged at INFO on success too, not only on failure.
- JS runtime (Dockerfile + tools/youtube.py): the image installs `nodejs` (yt-dlp enables only deno by default, so without a runtime the web client runs degraded — JS challenges unsolved → bot-check). Web-client attempts pass `--no-js-runtimes --js-runtimes node` (the `--no-` flag must come first to clear the deno default). Flag combination verified against the installed yt-dlp 2026.11.23 (parses clean; a live fetch hit the VM's egress 429, not a flag error). Docker build itself is unverified locally (no Docker in the VM) — Cloady builds it on push.
- File logging (main.py): Cloady free tier shows no runtime logs, so a RotatingFileHandler (1 MB x 3 backups, ~4 MB max) now writes to `data/bot.log` on the root logger — every module logger (tools.youtube per-attempt warnings, tg.handlers errors) lands there in the same format as stdout. Never crashes the bot over logging: an unwritable volume falls back to console-only with a warning; re-configuring adds no duplicate handler. `data/` and `*.log` are gitignored, so the log file itself is never committed.
- Human identity (brain/prompt.py prompt 6.4 → 6.5, brain/verify.py): Seif's directive after the rival bot kept admitting it is a bot — Bahgat must NEVER admit being a bot/AI and considers himself a normal human. SYSTEM_BASE now opens "انت بهجت صابر، إنسان عادي — مش بوت، مش ذكاء اصطناعي، مش برنامج." and _HARD_RULES_END gains rule 4 (deny when asked, scoped: "ده عن نفسك انت بس — لو سألك عن بوت تاني جاوب عادي"). The verify filter enforces it in code: first-person self-admissions ("أنا بوت", "أنا ذكاء اصطناعي", "أنا مش بني آدم", "أنا برنامج", … — normalised, so alef variants match) replace the WHOLE reply with an in-character denial ("أنا بهجت يا عم، إنسان عادي، مش بوت."), and voice_check flags "self_bot_admission" so the handler regenerates once first. Scoping is the point: "سعد ده بوت" / "انت مش بني آدم" (about others) pass untouched — the bare word "بوت" is deliberately not banned. Prompt budgets grew for the rule (SYSTEM_BASE < 1100, dynamic tail < 400 tokens) with v1.8 notes in the tests.
- Also committed with this version: docs/roadmap-v10.md, docs/live-test-matrix.md, docs/lightning-runbook.md (were untracked).

**Verified:** 547 tests pass (535 baseline + 12 new: 2 chain order/sleep/JS-flags, 4 file logging, 3 verify scoping, 2 identity scenarios, 1 prompt identity), ruff check clean on changed files. Voice synthesis untouched (separate job).

## 2026-11-27 — v1.7: fix "يا" vocative blocking the prefix layer + live-scenario test harness

The new harness (tests/test_live_scenarios.py — 60 scenario tests through the real pipeline — plus scripts/watch_bot.py, a read-only getUpdates watcher for live diagnosis) pinned a real bug: `detect_prefix_mode` stripped "بهجت" but not the vocative "يا", so "يا بهجت قولي نكته" routed to just_chat (joke as text, no voice note) and "يا بهجت دور حادثة الوراق" searched via the classifier with the raw text ("يا بهجت دور حادثة الوراق") as the query. Seif's messages almost always start "يا بهجت", so the prefix feature he asked for barely ever fired.

Fix: the prefix layer — and the fast-reply path, which had the same asymmetry ("يا بهجت شكرا" missed the fast path and cost a full LLM turn) — now skips one leading "يا" via `_skip_leading_vocative()` in brain/intent.py. Only the leading vocative is stripped; mid-sentence "يا" is untouched ("قول يا بهجت نكته" → voice, remainder "يا نكته"). Guards unchanged: "دور مين؟" never searches, "يا بهجت" alone stays normal chat, member/owner gates untouched. The two harness tests that pinned the buggy behaviour now assert the fixed behaviour, plus a handler-level يا-form joke-voice test and يا-form fast-reply tests.

**Verified:** 535 tests pass (473 baseline + 60 harness scenarios + 2 new), ruff check clean on changed files (ruff format diffs are pre-existing repo-wide, not enforced).

## 2026-11-26 — v1.6 phase 1: ingest Seif's submitted insults, round 3

Seif added 12 more insult lines on the "قاموس شتايم بهجت" page (page total now 45: 24 round 1 + 9 round 2 + 12 round 3). 10 were banked: 5 insulted comebacks (in-41..in-45, served 39 → 44) and 5 roasts (ro-42..ro-46, served 40 → 45). Bank total 214 → 224 raw entries (202 → 212 served). Two family lines this round: ro-42 ("ابن متناكه و ماشي…", Seif marked it "للبرّه بس" — the detector agrees) and ro-44 ("بعبصو بعض في حته تانيه يا ولاد ال…" — the detector's "يا ولاد" branch flags it even though Seif tagged the line member_safe on the page; the detector wins, so it is banked member_safe: false in the roast pool, never served at a member). The Mido line is the first subject-targeted user roast (ro-43, target: ميدو — fires only for a ميدو roast, never as a generic comeback). Dropped 2 lines: "قوم يا مصري مصر دايما ب تناديك قوم يا ايبنللللللللل مش هنتحايل عليك" (near-duplicate of the round-1 dropped rallying line "قووم يا مصري مش هنتحايل عليك" — still a patriotic chant, not an insult) and "خخخخخ ايوه خخخخخخ ايوه" (mocking laughter only, not an insult). One resubmission ("ايه الشرمطه دي") was skipped by the page itself as an exact duplicate of round-2's in-34. The round-1/round-2 dropped lines stay out. Note: this is phase 1 of v1.6; phase 2 follows.

**Phase 2 — contextual insult selection (same day):** every served insulted/roast line now carries `situations:` tags in the YAML (insulted: mocked 10, dismissed 8, sworn-at 6, general 11, called-dumb 4, family-attacked 4, repeated-insult 4, threatened 3; roast: general 18, perv 14, stupid-statement 9, arrogant 4, annoying 2 — roast `cowardly` has no line yet and falls back to `general`). Detection is deterministic keywords in `brain/intent.py` (`detect_insult_situation` / `detect_roast_situation`, normalised Arabic, word-boundary — no new LLM call on any message); a bare "اشتم X" has no situation → `general`. `_pick()` prefers lines tagged with the detected situation, then `general` lines, then any unused line, then — pool exhausted — the least-recently-used line (deterministic, so small pools rotate in full cycles). The no-repeat window replaces the in-memory last-5: last 25 lines per (chat, category) + last 10 lines per user, persisted in `bot_state` via `brain/memory.py` (`get_recent_bank_lines` / `record_bank_line`), so it survives restarts; the in-memory last-5 is still consulted as a union. Mood is severity-weighted: `update_mood()` takes an optional `insult_bump` (default 40 = old flat bump), wired in the handler via `SITUATION_MOOD_BUMP` (family attack +60, threatened/repeated +50, sworn-at +45, called-dumb/general +40, dismissed +35, mild mock +30). **Real bug fixed on the way:** the insult regex only knew 5 tame nouns, so the commonest Egyptian insults — "يا معرص", "يا شرموط", "يا وسخ", "يا خول", "يا ابن الكلب", "يا ولاد الكلب", threats ("هقتلك") — never reached the bank at all, and the family-attacked situation could never fire; the regex now covers the usual nouns, the "يا ابن …" family vocatives, bare "امك"/"ابوك", and threat verbs (friendly "يا ابن عمي" and innocent "ابن خلدون"/"أم كلثوم" still verified clean). The LLM prompt context was NOT given the situation (skipped as optional — the bank path returns before the LLM, and the non-bank turns don't need it). in-38 stays feminine-addressed with no gender gating (flagged, same as ro-23).

**Verified:** 473 tests pass (458 baseline + 15 new in tests/test_situations_v16.py), py_compile + ruff clean. Detector/tag agreement checked: the family detector flags exactly ro-40, ro-42 and ro-44 among the user lines.

## 2026-11-26 — v1.5: ingest Seif's submitted insults, round 2

Seif added 9 more insult lines on the "قاموس شتايم بهجت" page (page total now 33: 24 round 1 + 9 round 2). All 9 were banked: 8 insulted comebacks (in-33..in-40, served 31 → 39) and 1 generic roast (ro-41, served 39 → 40). Bank total 205 → 214 raw entries (202 served). All 9 are member-safe (no family line this round — the detector flags none of them, verified independently); nothing was dropped this round — all 9 are insults, none one-word, none near-duplicates. Caveat, flagged not fixed: in-38 is feminine-addressed ("انتي ست... يا وليه") and is served at whoever insults the bot — gender gating is out of scope (same as ro-23). The round-1 dropped lines ("يا حبيبي يا مصر…", "قووم يا مصري…", "مصممممممص") stay out.

**Verified:** 451 tests pass (446 baseline + 5 new in tests/test_bank_user_ingest_v15.py), py_compile + ruff clean.

## 2026-11-26 — v1.4: ingest Seif's submitted insults into the reply bank

Seif wrote 24 insult lines on the "قاموس شتايم بهجت" page. 21 were banked: 17 insulted comebacks (in-16..in-32, served 14 → 31) and 4 generic roasts (ro-37..ro-40, served 35 → 39). Bank total 184 → 205 raw entries (193 served). New confidence level `user` for owner-authored lines (source: user-submitted) — served like verbatim/cleaned, never presented as Bahgat transcript lines; only `approximate` is never served. All user lines carry an explicit `member_safe` tag; the one outsiders-only family line (ro-40, "يا ولاد الزنوه احترمو عقولنا", Seif marked it "للبرّه بس") is `member_safe: false` and can only serve at resolved non-member targets. Dropped 3 lines: "يا حبيبي يا مصر…" (patriotic chant) and "قووم يا مصري…" (rallying line) — not insults, no pool fits them; "مصممممممص" — single-word exclamation, breaks the bank's no-one-word-padding rule and duplicates in-30's "مصمص".

**Verified:** 446 tests pass (439 baseline + 7 new in tests/test_bank_user_ingest_v14.py), py_compile + ruff clean. Detector/tag agreement checked: the family detector flags exactly the one tagged family line among the user lines.

## 2026-11-26 — v1.3 live-test fixes: insult misroute, roast targeting, savagery, download fallbacks + cookies env var

Seif's live test of v1.2 in the group (screenshot 19:53–19:56 EET) + his verdict: the bot "مش اجريسف خالص" (not aggressive at all) — he wants a savage bot ("عايزه بوت متوحش"), the insults are weak/ordinary, and he wants them all varied and creative. He warned that if we cannot fix the savagery he will take the code and make it more savage himself. Three live failures in the same test: (1) "يا بهجت انتا حمار" was answered with the search-empty line; (2) "اشتم صلاح" got the incoherent roast "عاوز يغير في القرآن يا متناك؟"; (3) the YouTube download STILL fails live post-v1.1 ("يوتيوب رافض الطلب من السيرفر").

**Root causes:**
- Bug 1 — two compounding defects: `looks_like_insult()` only knew `(انت|انته)` + insult-noun, so the Egyptian spelling **انتا** was missed and the insult fast-path never fired; then the v0.9 unknown-retry (which excluded only voice intents) ran a web search on the insult turn and ended with `_SEARCH_EMPTY`. `detect_intent()` itself was innocent — it returned `just_chat`.
- Bug 2 — the roast branch used the target name only for the member/owner gates, then picked at random from the whole 35-line pool. 25 of the 35 lines are target-specific (11 about السيسي, 4 لينا, 2 الجيش, 2 ندوش, 2 المسيحي, 1 كيسنجر, 1 كارما, 2 situational) — so a Sisi line (ro-21, "on Sisi saying Quran texts must change") could land on صلاح.
- Bug 3 — the bot-check is intermittent and has tightened since v1.1: plain-android metadata went 0/4 in the VM; `android+player_skip=configs` was the only variant that ever downloaded (Marwan 1/2 through the new chain vs 0/5 single-variant). The no-cookies chain raises the odds but cannot guarantee a download from a flagged IP.

**Fixes:**
- Insult turns never search: "انتا" added to the insult regex; new `looks_like_insult_turn()` (insult at the bot OR roast request); an insult-turn guard in `detect_intent()` before the search check; `دور`-prefix refuses an insult remainder; BOTH unknown-retry branches gated on insult turns (gating only the first would let the `elif` fire `_SEARCH_EMPTY` with no search at all).
- Roast targeting: new optional `target:` field on roast entries (absence = generic); `_pick()` filters to generic + subject-matching lines (aliases: بلحه/بلحة → السيسي) and returns `None` rather than a non-sequitur when nothing fits. Roast pool unchanged: 36 raw / 35 served.
- Savagery: prompt 6.3 → 6.4 — aggression is now the default tone ("أسلوبك الافتراضي وحشي… والرد المهذب استثناء"); `voice_check()` bans service-politeness markers (`soft_polite`, always on) and flags edgeless replies on provoked turns (`soft_reply_to_provocation`, wired in the handler for insult/roast/challenge turns); insulted pool 7 → 14 served (honest ceiling from the transcripts — the rest is family insults, already-banked lines, garble, or guests' words; further growth needs Seif's own submitted insults).
- Downloads: 5-attempt no-cookies chain (android+skip=configs → android plain → ios+skip → web+skip → android+skip with explicit format 18/bestaudio), then cookies only if configured. New `YT_COOKIES_CONTENT` env var (approved by Seif 20:03 EET, throwaway account only): the bot writes the content once to `data/youtube_cookies.txt` (0600, gitignored) and passes it to yt-dlp on the final attempt only. No account created yet, no cookies file anywhere — account creation + export is a browser job, and Seif pastes the content into Cloady himself (see docs/YOUTUBE_COOKIES.md).
- Real bug note: the old test `test_handler_roast_member_gets_person_only_line` pinned the buggy behaviour (a السيسي line served as a roast of محمد) — updated to the correct generic line "فاشلين! فاشلين!" (ro-09). One old handler test updated for the provoked regeneration (a provoked turn with an edgeless draft now regenerates once, so 2 router calls instead of 1).

**Verified:** 439 tests pass (365 baseline + 74 new), py_compile + ruff clean, VM end-to-end downloads (Rick Astley video 11.83 MB / audio mp3 3.71 MB; Marwan video 5.07 MB once, then all-5-attempts bot-check on the retry). Live confirmation still needed: 🎬/🎵 taps from Cloady, with and without cookies.

## 2026-11-26 — v1.1 live-test fixes + Bahgat reply bank (persona)

Seif's live test of v1.0 in the group (screen recording 18:05–18:10
EET) + his verdict: "مش حاسس اني بتكلم مع بهجت، مش بيتكلم زيه، مش
بيقول لزماته، ومش اجريسف زيه" — and his idea: memorized replies from
Bahgat's most famous videos, disrespectful like him. **Correction
from Seif 18:24 EET: BOTH YouTube download taps FAIL live — video
AND audio — with "فشل التنزيل هات لينك تاني". The media-player bar
in the video was NOT a successful download.** Downloads are the top
priority of this version.

**Root causes (all from the code, confirmed against the video
frames):**
- Bug 1 — downloads died before any network request: `download()`
  passed `--no-thumbnail` and `--no-subs` to yt-dlp, both REMOVED
  in newer yt-dlp (the pinned range `>=2026.7.4` installs the
  latest; 2026.11.23 has only `--no-write-thumbnail` /
  `--no-write-subs`). yt-dlp exited with "no such option:
  --no-thumbnail" on every tap, video and audio, while search
  (which never passed those flags) worked. Reproduced in the VM.
- Bug 2 — even with the flags fixed, the player/format step hits
  YouTube's bot-check on a datacenter IP. Fix: Android player
  client (`--extractor-args youtube:player_client=android`, the
  same bypass that worked for the training downloads) on
  `download()` and `resolve_query()`; format selectors now fall
  back to `best` (Android serves only format 18 + storyboards,
  no audio-only format) and the audio path uses
  `bestaudio[ext=m4a]/bestaudio/best` with ffmpeg extraction.
  Verified end-to-end in the VM (video 5.07 MB, audio mp3 3.40 MB)
  — Cloady has no MITM proxy so odds there are better, but ONLY
  Seif's live test can confirm. If it still fails, the fallback is
  a cookies file from a THROWAWAY Google/YouTube account (never
  Seif's own — his cookies file stays off the host; see
  docs/YOUTUBE_COOKIES.md). The code path (`YT_COOKIES_FILE`) is
  built; no cookies file is on the host, no account was created,
  Seif has not approved either cookies route.
- Bug 3 — the failure path hid the cause: `_run_yt_dlp` returned
  the first 300 chars of stderr (usually SSL/progress warnings).
  Now `_pick_error_detail()` prefers the last ERROR line, the
  callback logs the real error, and the OWNER gets a short
  classified hint (bot-check / too large / no format / unavailable
  / bad settings / timeout).
- Bug 4 — bare "هات مروان موسي" asked a confused question: the
  "هات" guard sent a non-media remainder to the classifier and a
  bare artist name is non-media → just_chat. Now a short bare
  artist name (≤3 words, no question, no non-media noun) after
  "هات"/"هاتلي" goes to YouTube; "هات ملخص" still falls through.
- Hardening, NOT a live bug (video worker's correction) —
  opinion challenge: the brief's "restated the theory" quote was
  the SEARCH answer's opening, mixed up with the opinion reply.
  The actual opinion reply (6:06 PM) was sharp and in-character:
  "رأيك في إيه يا غبي؟ النظرية دي مؤامرات فارغة، وأنت لسه فاكرها
  حقيقة؟ روح ركز في حياتك بدل ما تضيع". The prompt had NO stance
  instruction, so that sharpness was luck, not a guarantee — the
  machinery below makes it reliable: `looks_like_opinion_ask()` +
  a stance line in SYSTEM_BASE + an 8th few-shot pair + a
  user-role stance note in the handler; PROMPT_VERSION 6.3.
- Bug 6 — "قول نكته" (6:09 PM) and "قول اهلا في فويس نوت"
  (6:10 PM) never produced a voice note. THREE holes: (a)
  `_try_send_voice` had a single synthesis attempt — any failure
  fell back to text with only a log line; now retried once (2
  attempts) with per-attempt logging; (b) a FAILED attempt still
  recorded the 5-minute voice cooldown — the cooldown is now
  recorded ONLY on success; (c) the "قول" prefix itself was
  vetoed by the voice-words guard ("فويس" in the remainder made
  `detect_prefix_mode` return None, so `voice_only` was False and
  the turn sent text first + trailing voice) — the "قول" branch
  now runs before that guard, which stays for "دور"/"هات" only;
  (d) the unknown-retry search fired on voice turns, so the
  6:10 PM request came back as `_SEARCH_EMPTY` text — voice
  intents are now excluded from both unknown-retry branches.
  A "قول" that still doesn't go out as voice is now VISIBLE: the
  text fallback carries "الصوت مش راضي يطلع دلوقتي" (failed) or
  "الصوت استنى شوية" (cooldown), short replies only.
- Correction — the pick-list "duplicate": the frames show NO
  EL 3NWAN double. "النظام" (3:40) and "EL 3NWAN" (2:58) are
  different songs; the apparent double was EL 3NWAN at different
  positions in two separate renderings of the الخلاصه list (6:07
  vs 6:08 PM). The REAL duplicate was in the فرعون list: the same
  song twice under different uploads ("Marwan Moussa - Fr3on
  (Official Audio)" vs "MARWAN MOUSSA - FR3ON | ...", both 3:47)
  — video ids cannot catch that, so `search_query()` now also
  drops a later entry when its title tokens are a subset of an
  earlier entry's (or vice versa) with equal duration (≥3-token
  floor; video-id dedupe stays as the first pass).
- Observation, no fix — the LLM path is mildly rude to the owner
  by name in heated exchanges: the 6:06 PM opinion reply opened
  "رأيك في إيه يا غبي؟" and the 6:10 PM text joke ended "دمك
  تقيل يا سيف". The owner-never-insulted rule as implemented
  covers targeted insults and bank lines (the bank never serves
  the owner an insult/challenge line); spontaneous mild rudeness
  toward the owner in an LLM exchange is not blocked. Seif asked
  for a disrespectful bot, so this is his call, not a fix.

**Persona (Part B):** research in docs/research-persona-methods.md
(27 sources; ranked: reply bank first, Style RAG second, structured
prompt third, post-generation voice check fourth — fine-tuning
blocked on free tier, logit bias unsupported by Groq/Gemini).
New `persona/bahgat/reply_bank.yaml`: 36 lines from Bahgat's OWN
transcripts (8 videos, 4,562 segments), 22 verbatim / 11 cleaned /
3 approximate, source video marked per line; family insults
deliberately dropped (only person-only insults banked). New
`brain/reply_bank.py` fast-path (insulted > joke > opinion >
challenge > greeting; owner never served an insult/challenge line;
insult comebacks only when the insult targets the bot; opinion
lines topic-gated; rotation never repeats within 5) checked BEFORE
the LLM, no quota/LLM/bubble. Prompt rewritten (PROMPT_VERSION
6.3, 872 chars): behaviour-as-verbs, agenda, challenge line,
anti-softening, lazma as calibration not quota. New
`brain/verify.py::voice_check()` + one regeneration for replies
that come out polite/Fusha/apologetic/restating. Full dynamic
Style RAG is deferred to v1.2.

**What changed:** `brain/intent.py` (bare artist, opinion
detection, قول prefix order), `brain/prompt.py` (6.3, stance, 8
examples), `brain/reply_bank.py` (new), `brain/verify.py`
(voice_check), `tools/youtube.py` (dedupe, download repair,
cookies path, error detail), `tg/handlers.py` (bank fast-path,
opinion note, voice retry/cooldown/notes, voice-check regen,
download error hints), `persona/bahgat/examples.md` (8th pair),
`persona/bahgat/reply_bank.yaml` (new),
`docs/research-persona-methods.md` (new),
`docs/YOUTUBE_COOKIES.md` (new), `.env.example`
(`YT_COOKIES_FILE`), `.gitignore` (cookies files),
`tests/test_v11_fixes.py` (new, 27 tests).

**Tests:** 342 passed (315 baseline + 27 new), py_compile + ruff
clean, secret audit clean, no training data staged. Commit local
only — NOT pushed (no token in context).

## 2026-11-26 — v1.0 router rework: fast chat, bubble only for slow work, prefix modes

Seif's request (phone video 07:32–07:35 EET): "انا حاسس ان الموضوع معقد
عليه في التفرقه بين التدوير علي الانترنت و التدوير علي اليوتيوب و الكلام
العادي… عايزين مود ل البحث عن الانترنت و مود ل فيديوهات و صوت اليوتيوب
و مود الكلام العادي يكون اسرع شويه" — plus his own design idea (07:51
EET): start a sentence with **"دور"** → internet search, **"هات"** →
YouTube, **"قول"** → voice note. **The modes question, answered in one
line: no modes UI and no slash commands — the router does it.** The
three prefixes are deterministic tier-1 routing (hybrid routing:
rules first, classifier for the ambiguous tail — see
docs/research-intent-routing.md §§1, 6); normal chat is unchanged, and
anything that implies a mode without the prefix word still routes to
that mode.

**Root causes (all from the code, confirmed against the video):**
- Bug 1 — "شكرا يا بهجت" ran a full LLM turn behind a "بفكر يا عم،
  استنى…" bubble: `_run_llm_turn` (tg/handlers.py) started the status
  bubble unconditionally for ALL intents, and there was no fast path
  for trivial chat — every "شكرا"/"تمام"/"اهلا" paid a model call.
- Bug 2 — "دورلي علي اغنية مروان موسي الخلاصه" got no pick-list:
  `detect_intent` (brain/intent.py) classified it as `search`, not
  `youtube` — "دورلي" was in `_SEARCH_WORDS` and "اغنيه" alone was not
  a YouTube trigger — so the song ran a web search instead of YouTube.
- Latent bug, same class as v0.9: `_has()` matched *raw* keyword
  strings against normalised text, so list entries written with ى/ة
  (e.g. "دور على", "على النت") could never match — verified:
  `_has("دور علي", ["دور على"])` was False. And the YouTube search
  itself got the raw message ("دورلي علي اغنية مروان موسي الخلاصه
  @Bahgoti_bot") as its ytsearch query, request words and all.

**What changed:**
- `brain/intent.py` — `_has()` normalises the keywords too (the
  duplicate spellings are gone); new media-noun + request-verb rule
  ("دورلي علي اغنية" → youtube, "دورلي علي حادثة" → search; bare
  "اغنية"/"تراك"/"فيديو" + short message → youtube, a question about
  a song is not); "هاتلي"/"جبلي"/"نزل" are no longer standalone
  YouTube triggers (they are request verbs — "هاتلي ملخص" is a summary,
  "نزل سعر الدولار" is a price question; they only fire with a media
  noun). New `detect_fast_reply()` — instant Bahgat-voiced canned
  replies for greetings/thanks/acks/laughter/bare "بهجت" (≤3 words,
  no question, no insult, no apology, mood < 70). New
  `detect_prefix_mode()` — "دور" → search, "هات" → YouTube,
  "قول"/"قولي" → voice, checked first in `detect_intent()`, with
  guards: empty remainder, question remainder ("دور مين؟" is "whose
  turn?", not a search), media noun after "دور" (a song request),
  non-media remainder after "هات" ("هات ملخص" is a summary), and voice
  still outranks every prefix ("هات فيديو بصوتك" → voice).
- `tg/handlers.py` — fast path at the top of `_run_llm_turn`: no quota
  consumed, no LLM call, no bubble, no search; mood + history still
  updated. The status bubble is created always but `start()`ed only
  for search/youtube intents (new lazy `ensure_started()` for the
  unknown-retry search); plain chat LLM turns get the typing indicator
  only. YouTube query smoothing (`_yt_query` strips request words,
  trigger, @mention, media nouns; `_yt_query_retry` retries once with
  query + "اغنية" on 0 results); the pick-list header and stored state
  use the winning query. A "دور" prefix query is self-contained — it
  never gets the follow-up topic inheritance. "قول" prefix: the reply
  goes out as a voice note *instead of* text (new `_try_send_voice`
  helper), with the text as fallback if synthesis/send fails. Voice is
  the current Edge TTS voice — RVC is NOT wired yet.
- Tests: new `tests/test_router_v10.py` (exact video phrases + prefix
  phrases + normalisation + smoothing + handler-level fast-path and
  voice-only tests); `tests/test_status_ux_v08.py` error test updated
  to the new bubble contract (plain-chat error = normal message, no
  bubble); `tests/test_cache_quota_v06.py` quota tests switched from
  greeting probes to real questions (greetings take the fast path now).
  Full suite: 315 tests pass, py_compile + ruff clean.
- Docs: `docs/research-intent-routing.md` (§§1–5: layered/cascade
  routing, fast paths, Arabic normalisation, YouTube robustness,
  status indicators; §6: the prefix layer + hybrid-routing verdict).

**Untouched:** v0.9 one-turn search, edit-in-place status, no deletes,
quota/pacing/persona/insult rules, voice training files.


Seif's exact request (video, test group 03:24–03:27 EET): "عايز لما اقوله
يدور علي النت و يقولي استني بفكر النتيجه تطلع في نفس الرساله بتاعت
استني بفكر مش اقوله ايه الحصل عشان النتيجه تطلع" — plus "اغلب الحجات
مش شغاله صح" and, in the follow-up, "مش بيجيب فيديو اليوتيوب لا صوت
ولا فيديو صوره بس".

**Root causes (all from the code, confirmed against the video frames):**
- Search: "سيرش على النت على حادثة الوراق" matched NO `_SEARCH_WORDS`
  entry (no "سيرش", no "على النت", no "حادثه" — and the normaliser does
  NOT map على -> علي, so "دور على" missed "دور علي" too), so it fell to
  just_chat and no search ran before the first LLM call.
- The prompt TAUGHT the stall: the few-shot pair in
  `persona/bahgat/examples.md` (and the fallback copy in
  `brain/prompt.py`) answered a news question with "يا عم أنا مش جوجل،
  بس هدورلك واجيبلك الخلاصة", and the deflection line in
  `build_system_prompt` called that dodge "correct". The LLM imitated
  it, `looks_unknown` did not catch it, and the handler shipped it as
  the final reply.
- The old `_UNKNOWN_DEFLECTION` was sent AFTER a search had already run
  in every path that used it — a promise of a search no later turn
  delivers. The follow-up "ايه الحصل" then got an LLM "لسه بدور… لما
  اجيبلك الخلاصه" stall (history contained the promise), also uncaught.
- Download: v0.8's pick flow sends the choice view as a PHOTO, but the
  `yt:video`/`yt:audio` callback calls `edit_message_text` on it — the
  Bot API rejects that on a media message, the callback died before the
  download even started, and the tap went silent with the picture just
  sitting there (buttons already removed). The download-failure branch
  had the same crash, so failures were silent too.
- Clutter: the status bubble was deleted on every turn and the list
  message deleted on every pick — a "Deleted message" tombstone each
  time (visible all over the chat in the video).

**What changed:**
- `brain/intent.py`: `_SEARCH_WORDS` gains "سيرش", "على النت"/"علي
  النت", "دور على", "حادثه", "خبر", "عايز اعرف"/"عاوز اعرف"; new
  `looks_stalling()` ("لسه بدور", "لسه قالك", "اجيبلك/هجيبلك الخلاصه",
  "استنير") and "مش جوجل"/"بس هدورلك" added to the unknown markers.
- `brain/prompt.py` + `persona/bahgat/examples.md`: the news-question
  example now answers from the search ("دورت في الأخبار ومفيش حاجة
  كبيرة… [1]"); the deflection line is replaced by a ban on promising
  a search ("ممنوع تقول إنك هتدور أو لسه بتدور…"). PROMPT_VERSION
  6.0 -> 6.1 (dynamic part still < 300 tokens).
- `tg/handlers.py` — search endgame: an unanswered reply (unknown or
  stalling) after a search ran gets ONE firm retry from the grounding;
  if it still will not answer, the reply is built from the passages
  directly (`_search_fallback_reply`, extractive) or says plainly that
  the search found nothing (`_SEARCH_EMPTY`). The old deflection is
  retired. Fallback replies are never cached. A search question now
  always ends with an answer in the same turn.
- `tg/handlers.py` — edit-in-place: `_StatusMessage.finalize()`
  replaces `delete()`; the final reply, the pick-list, the choice view
  and the error line all EDIT the bubble. New `_send_final()` (first
  chunk edits the bubble, the rest go as plain messages; falls back to
  a normal message when the bubble never went up). Cache hits and quota
  denials still skip the bubble entirely. Typing indicator unchanged.
- `tg/handlers.py` — no deletes: a pick EDITS the list message into
  the text choice view (same message id, same state key). Trade-off,
  documented: the photo choice view is gone — a text message can never
  be edited into a photo, and the photo was the reason the list had to
  be deleted. The thumbnail is dropped.
- `tg/handlers.py` — download callback: new `_edit_choice_message()`
  (caption for photo choice views, text otherwise) for the progress /
  failure / done edits, plus an outer safety net so any failure edits
  the choice message into an in-character error instead of going
  silent. A tap now always produces the file or an error line.
- Tests: `tests/test_search_one_turn_v09.py` (10 new: grounding parse
  + extractive/empty fallback, one-turn answer in the bubble, empty
  search, stall-twice fallback, photo-caption download, download
  failure answers in chat, text-choice edit); `test_status_ux_v08.py`
  (finalize + error-edit, no delete), `test_youtube_list_v08.py`
  (pick edits in place, no photo, no delete),
  `test_cache_quota_v06.py` (search-ran turns retry once now),
  `test_intent.py` (سيرش keywords + stall detection).
- 295 tests pass (285 + 10 new), py_compile + ruff clean on the bot
  code (the 21 ruff hits in `training/colab/*.ipynb` are pre-existing,
  not touched here).
- NOT verified live in this VM: the yt-dlp download itself from Cloady
  (the callback died before `download()` was ever called, so the
  format/cookies question is still open — the search calls prove
  yt-dlp reaches YouTube from Cloady, the download is the untested
  part). First live test after deploy: song → pick → tap فيديو (video
  arrives) and tap صوت (audio arrives). If the download fails live,
  the next step is a cookies file on the host — Seif already supplied
  one for the voice downloads; do NOT reuse it without asking him.

## 2026-11-26 — v0.8 live status + YouTube pick-list (deploy target: Cloady, no card)
- **Live status message (`tg/handlers.py`, `_StatusMessage`).** Long turns
  now show ONE editable status bubble (OpenClaw-style progress draft —
  research in `docs/research-bot-ux.md`): sent with
  `disable_notification` so the group isn't pinged, edited in place as
  the stage changes, a braille spinner (⠋⠙⠹…) cycling every 1.5 s
  while a stage runs long, and deleted when the final reply lands — and
  in a `finally` block on errors — so no stale bubble is ever left
  behind. Never raises: if the bubble can't be sent, the turn continues
  without it. Skipped entirely for instant paths (cache hits, quota
  denials). The existing `_typing_loop` chat action is kept alongside
  it. Stage lines are Bahgat-voiced Egyptian dialect: "بفكر يا عم،
  استنى…" (thinking) → "بدورلك على النت، يا عم…" (searching) →
  "بجيبلك من يوتيوب، استنى…" (YouTube) → "بنزلها لك دلوقتي، استنى
  شوية…" (downloading).
- **YouTube pick-list (MIRAL-style).** `tools/youtube.py` gains
  `search_query(query, limit=5)` (yt-dlp `ytsearchN:` + `--flat-playlist`,
  same URL/option validation as `resolve_query`). Text queries now
  return up to 5 results shown as "• نتائج البحث ← <query>" with
  numbered full titles and one inline button per result (button text
  truncated to 40 chars). New callback `yt:pick:<index>` (index only —
  `callback_data` is 1–64 BYTES, values resolve server-side) renders
  the وعد-style choice view: the video's thumbnail as a photo message
  with title + duration caption and the two buttons "🎬 فيديو" /
  "🎵 ملف صوتي" (falls back to editing the list in place if the
  thumbnail can't be sent — a text message can't be edited into a photo
  via editMessageMedia). Same requester-only guard, 10-min TTL and
  callback dedup as the existing YouTube callbacks. One result skips
  the list and goes straight to the choice view; a pasted YouTube URL
  does the same; zero results answers in character ("دورت يا عم ومفيش
  حاجة بالاسم ده، جرب اسم تاني.").
- Tests: `tests/test_status_ux_v08.py` (5 tests: stage lines, bubble
  lifecycle + idempotent delete, send-failure never raises, spinner
  cycling, bubble deleted when the LLM turn raises) and
  `tests/test_youtube_list_v08.py` (10 tests: duration/button helpers,
  list text + keyboard + 64-byte callback cap, pick parsing,
  search_query parsing + validation, pick photo view + state re-keying,
  requester-only guard, expiry, thumbnail-failure fallback).
- 285 tests pass (270 + 15 new), py_compile + ruff clean.
- Not verified live in this VM: yt-dlp is not installed here, so the
  real `ytsearch5:` call was exercised only with a mocked runner; the
  Cloady Docker image installs it from requirements.txt
  (yt-dlp>=2026.7.4). First live test after deploy: ask for a song and
  tap through list → photo choice → download.

## 2026-11-26 — v0.7e Cloady deploy + search follow-up fix (deploy target: Cloady, no card)
- **Deploy moved Render → Cloady.** Render's "Add Card" modal blocked the
  free deploy on Seif's brand-new account (account-level anti-fraud check;
  Render's docs say no card, but the check fires anyway and no config
  bypasses it). Cloady free workspace (0.5 vCPU / 1 GB RAM / 5 GB SSD,
  Germany EU1, no card, no expiry) now hosts the bot; deploy went LIVE
  2026-11-26 02:03 EET and the bot replied in the test group 02:10 EET.
- `docker-compose.yml`: bind mount `./data:/app/data` rejected by Cloady
  ("volumes must mount a declared named volume") — now a declared named
  volume `bahgat-data:/app/data` (also the persistence layer: memory
  survives redeploys, unlike Render free). `env_file: .env` dropped (the
  platform injects env vars; a missing .env would fail the parse),
  `cpus: 1.0` → `0.5` to stay inside the free tier. `ALLOWED_CHAT_IDS`
  deliberately left unset in Cloady per Seif's call — the bot answers in
  any group it is added to.
- **Search follow-up fix (`tg/handlers.py`, `_search_query`).** Live bug:
  Seif asked about the Waraq incident, then "ايه الحصل" — the bot
  searched the literal follow-up and answered with song lyrics about
  "عمره ما غنى ولا عرف الهوى". Short follow-ups (<= 4 words) now inherit
  the most recent substantive user turn from history, so the query keeps
  the topic. Both search call sites (search intent + unknown-retry loop)
  use it. Tests: `tests/test_search_followup_v07e.py` (5 tests).
- **Intent keywords (`brain/intent.py`).** Two more live misses from the
  same session: "ايه الحصل" (without اللي) did not match `_SEARCH_WORDS`
  (only "ايه اللي حصل" was there), so follow-ups fell to just_chat and
  only got searched via the unknown loop; "عايز اغنيه" did not match
  `_YOUTUBE_WORDS`, so a song request never offered the video/audio
  choice. Added "ايه الحصل"/"ايه حصل" to search words and
  "عايز اغنيه"/"عاوز اغنيه"/"عايز فيديو"/"عاوز فيديو" to YouTube words.
  Tests in `tests/test_intent.py`.
- Test fix: `test_gemini_skipped_when_daily_requests_at_cap` seeded usage
  by UTC date while the router keys Gemini by Pacific date — it passed at
  23:44 UTC and failed at 00:18 UTC the same night. Now seeds by Pacific
  date, like the router.
- 268 tests pass (263 + 5 new), py_compile + ruff clean.

## 2026-11-25 — v0.7d Render free web service conversion (deploy target: Render, no card)
- `render.yaml` converted from Background Worker to **free Web Service**:
  `type: web`, `plan: free`, `numInstances: 1`, `env: docker` (Dockerfile
  runtime — the image carries ffmpeg, which the native Python env lacks),
  `region: frankfurt`, `dockerfilePath: ./Dockerfile`,
  `healthCheckPath: /healthz`. Render Free does NOT cover workers
  (docs.render.com/free), so the old worker config could never deploy free.
- `DROP_PENDING_UPDATES=false` is now a literal env var in `render.yaml`
  (messages sent while the bot slept are delivered on wake — Telegram
  holds updates 24h — instead of discarded). Secrets stay out of the file:
  `TELEGRAM_BOT_TOKEN` / `GEMINI_API_KEY` / `GROQ_API_KEY` /
  `NVIDIA_API_KEY` are declared with `sync: false`, so Render asks for them
  in the dashboard; `OWNER_ID=1415214630`,
  `ALLOWED_CHAT_IDS=-1005812444791`, `LOG_LEVEL=INFO` are literal values.
- Verified the $PORT path end to end: `main.py` starts the v0.7c health
  server (tg/health.py) BEFORE `run_polling`, so the Docker CMD
  `["python", "main.py"]` binds `0.0.0.0:$PORT` at boot; the heartbeat file
  is first written in `post_init`, so `/healthz` turns 200 within seconds
  of startup (brief 503 in the first seconds is normal — documented in
  DEPLOY.md). `resolve_port()` reads Render-injected `$PORT`, default 8080.
  No code change was needed for the port; only a `main.py` comment now
  names Render free alongside Northflank.
- `docs/DEPLOY.md` rewritten as a complete Render deploy checklist in
  Egyptian Arabic: free-tier trade-offs stated plainly (sleeps after 15 min
  idle; SQLite wiped on every redeploy/restart — memory loss is EXPECTED on
  this first deploy; 750 free hours/month = exactly one service 24/7),
  prerequisites, exact env-var table, dashboard steps (New → Web Service →
  Docker → Free → 1 instance), verification (logs + GET /healthz),
  cron-job.org pinger setup (every 10 min, free, 1-min granularity — better
  than UptimeRobot's 5-min GET-only), live-test messages for the test group
  (-1005812444791), and the next step flagged, NOT built: Turso/R2
  persistence (docs/research-deploy-state-persistence.md).
- Tests: **263 pass in .venv, py_compile clean, ruff clean.** Smoke tests:
  health server binds `$PORT` in a subprocess (`/healthz` 200 fresh,
  `/health` alias 200, 503 stale); `import main` + `build_application()`
  builds 6 handlers; `DROP_PENDING_UPDATES=false` parses to False.
  Docker image build NOT verified — docker is not installed in this VM.
- Open blockers (not done here): (1) no GitHub repo exists yet — Render
  builds from a GitHub repo on branch main; (2) no Render account yet
  (free, no card); (3) Seif must paste his 4 keys into the Render
  dashboard himself (Vault keys are not available to Render). Nothing was
  deployed; no account created; no credentials touched.

## 2026-11-25 — v0.1 scaffold
- Modular scaffold: config-driven persona/providers/rules, plugins, multi-LLM router stub, SQLite memory schema, Docker.
- Training video lists compiled (voice vs style). Audio cleanliness NOT verified yet.
- Waiting: Telegram bot token (secure link sent), owner ID, test group.

## 2026-11-25 — v0.2 core + tools (no token yet, untested live)
- Brain router: Gemini -> Groq -> OpenRouter, OpenAI-compatible, auto-fallback on error.
- Memory: SQLite per-member (mood, grudge, notes), recent 12 messages context.
- Mood: insult +40, praise -20, voice when asked / mood>=90 / random 12%.
- Intent from normal talk (no slash commands): search / youtube / voice / just_chat.
- Tools: DuckDuckGo search + page fetch, yt-dlp 480p / mp3 with 50 MB limit, Edge TTS ar-EG-ShakirNeural -> ogg voice note.
- Handlers: reply only on mention / "بهجت" / reply-to-bot, owner-only control phrases for Seif.
- Tests: insult rules + mood + intent pass locally (pytest not installed, run via python -c).
- Still blocked: Telegram token, owner ID, test group, Gemini/Groq keys — needed for live test + deploy.

## 2026-11-25 — Telegram connected, bot verified
- Token submitted via secure link and verified with getMe: @Bahgoti_bot, id 9106462211, first name بهجت.
- Connector doc + helper at ~/workspace/custom-connectors/custom.telegram/ (getMe / getUpdates / sendMessage).
- getUpdates empty — bot not in any group yet.
- Known: can_read_all_group_messages is false, so bot must be admin in test group (or privacy disabled in BotFather) to see plain "بهجت" messages.
- Still waiting: owner ID, test group link, Gemini/Groq keys.

## 2026-11-25 — Gemini connected and verified
- Gemini key submitted, models list works via OpenAI-compatible endpoint.
- gemini-3-flash-preview generates replies (verified). Primary model updated to it.
- gemini-2.5-flash/pro retired (404), gemini-3.1-pro-preview free-tier quota 0 (429).
- Still waiting: Groq key, adding @Bahgoti_bot as admin to test group.

## 2026-11-25 — Groq connected and verified
- Groq key submitted, models list works, openai/gpt-oss-120b generates Egyptian Arabic replies.
- Groq needs a browser User-Agent header, otherwise Cloudflare returns 403 error 1010.
- Brain is now complete: Gemini (gemini-3-flash-preview) primary, Groq (gpt-oss-120b) fallback.
- Still waiting: adding @Bahgoti_bot as admin to the test group, then live test + deploy.

## 2026-11-25 — v0.3 code review + brain hardening (P0, from professional research)
- Router v3: classified retries (only 408/429/5xx), exponential backoff + full jitter, honour Retry-After, circuit breaker (3 failures -> OPEN 60s), SQLite quota table (skip exhausted provider until midnight UTC), token counting, simple->Groq first / hard->Gemini first, temperature per intent (search 0.25, chat 0.85).
- Prompt v3: dynamic system prompt assembly (role, objective, constraints early, memory/mood/search/style, few-shot escape hatch), user text wrapped in <user_message> tags, guardrails in code not prompt.
- Verification in code: family-insult enforcement for members, banned AI phrases, HTML escaping, 4096-char split on sentence boundaries.
- Telegram reliability: dedup on update_id (INSERT OR IGNORE first), per-chat rate limit (1 msg/s, 20/min/group), YouTube video/audio inline buttons (yt:video / yt:audio) instead of pretending to download, callback answers.
- Memory schema: processed_updates, provider_usage, pinned_facts, outbox tables.
- Added .gitignore (.env, data/, *.db), tenacity in requirements (documented, hand-rolled retry kept for now).
- Tests: verify, prompt, router circuit breaker — all pass locally.
- Still open (from research, P1/P2, not yet built): LLM tool-calling replacing keyword intent, structured BotPlan, LLM-as-judge for search answers only, RAG over Bahgat transcripts for style, rolling summarisation, /stats owner command, CI with ruff/mypy.

## 2026-11-25 — v0.4 code review fixes (C1-C11, M1-M12)
- Router v4: max_completion_tokens=4000, reasoning_effort=low (Groq), thinking low (Gemini), temp 0.7 chat / 0.25 search, one client per provider + close() on shutdown, no raw exception leak to group (log only).
- Search: resolve DDG uddg redirects, raise_for_status, content-type check, Lite fallback, realistic UA.
- Search-when-unknown loop: if reply says "مش عارف" and no search ran, search once and retry with results.
- YouTube: inline video/audio buttons now actually download in to_thread, per-request UUID folder, --no-playlist --max-filesize 50M, capture real filepath, delete after send.
- Insult enforcement: post-filter in code, plus owner commands normalised and checked before trigger gate, mute/clear-memory owner commands.
- Memory/mood: history fetched BEFORE inserting current message, assistant stored with bot id, mood time-decay -10/hour, prune messages to last 200/chat, index on messages(chat_id,id).
- Blocking work: yt-dlp in to_thread, voice split at sentence boundaries, file handles closed, files deleted.
- Config: persona.yaml + examples.md now loaded at startup, OpenRouter removed (no key, never ran), providers.yaml honoured, render.yaml (Background Worker) + docs/DEPLOY.md + .dockerignore added.
- Tests: 17 tests pass in .venv (verify, prompt, router, intent, insult rules). System pip install fails (PEP 668) — use .venv, documented in DEPLOY.md.
- Still open (P1/P2, not built yet): LLM tool-calling replacing keyword intent, structured BotPlan, LLM-as-judge for search only, RAG over Bahgat transcripts, rolling summarisation, /stats owner command, CI ruff/mypy.

## 2026-11-25 — v0.4b search fix (live verified)
- Search rewritten from httpx to urllib: httpx mis-parses NO_PROXY in this VM and fails SSL through the egress proxy. Live test now returns 5 results with real URLs (not DDG redirects) and fetches pages.
- Split-message hard-split fix: long single sentences now split at 4000 chars (test was failing).

## 2026-11-25 — v0.5 review rounds 2–6 (five independent reviews, deduplicated)
Five independent review rounds were run against v0.4 and their overlapping findings
deduplicated; v0.5 implements the highest-priority fixes. **127 tests pass in .venv
(pytest tests/ -q), py_compile clean, ruff check passes. `import main` + `build_application()`
verified (6 handlers).**

### Fixed — security (round 2)
- SSRF in search: `validate_url()` — https only, hostname resolved and rejected if
  private/loopback/link-local (169.254/10/172.16/192.168/::1/fc00), redirects re-validated
  (max 3), body capped ~1 MB. Note: `ipaddress.is_private` is NOT used — in this VM the
  egress proxy returns 198.18.0.0/15 for ordinary public hosts, which it flags.
- yt-dlp argument injection: host allowlist {youtube.com, www.youtube.com, youtu.be,
  music.youtube.com}, leading `-` rejected, `--` inserted before the URL, yt-dlp pinned
  `>=2026.7.4`. Plain text is resolved via code-built `ytsearch1:` first, never passed raw.
- Prompt injection layers: sandwich guardrail after the user message, search results
  labelled untrusted data with `[n]` citations required, grudge/notes never in the system
  prompt (moved to a user-role `[MEMORY]` block, instruction patterns stripped at write
  time), output filter for system-prompt/owner-id/key leakage in `verify.py`.
- Group allowlist `ALLOWED_CHAT_IDS` (env, comma-separated; empty = allow all + startup
  warning, because the test group's numeric chat id is not known yet — only the invite
  link is). Checked before any LLM/search/voice call.
- Real insult-target resolution via `get_chat_member` + `insult_level()` wired into prompt
  AND verify; target == owner (1415214630) is never insulted.

### Fixed — quotas / cost (rounds 2, 5, 6)
- Durable SQLite per-user-per-group daily budget: 30/user/day, 150/group/day, checked
  before LLM/search/voice.
- Groq TPM-429 (ban for Retry-After only) vs TPD-429 (ban to midnight UTC) distinguished;
  Groq-first routing for everything with Gemini reserved (hard cap 15 Gemini req/day,
  stopped before 429); `openai/gpt-oss-20b` added for simple chat.
- Per-chat in-flight lock (one LLM call per chat); typing renewed every 4s; output cap
  400–600 tokens for chat (600 search), Groq `max_completion_tokens` 1500–2000, Gemini 4000,
  `include_reasoning=False` for Groq, `reasoning_effort="low"` both providers.
- Token estimate fixed to `len//2` (len//3 undercounted Arabic ~2x).

### Fixed — brain (round 3)
- Arabic normalisation in intent (diacritics stripped, أ/إ/آ→ا, ة→ه, ى→ي); verb patterns
  (مين كسب/كسب مين/كام/امتى/فين/بكام, هاتلي/هاتيلي/جبلي/شغلي) and insult patterns
  (انت حمار/غبي/كلب/عبيط); `looks_like_praise` implemented (was hardcoded False).
- Real few-shot examples: `persona/bahgat/examples.md` now has 7 real User/Bahgat exchange
  pairs (person-only insult, correct deflection, search answer with [1] citation, praise,
  song request); `persona.yaml` is now wired into `build_system_prompt` (was dead config).
- Grounding v2: top 3 results fetched in parallel, youtube/tiktok skipped for facts, best 2
  kept with URLs, `[n]` citations required, unknown markers widened, in-character
  deflection when still ungrounded.
- Speaker-tagged history (`[name]: text`); single mood-decay mechanism (time-based on read,
  persisted — per-message −5 removed); one canonical `FAMILY_WORDS` list shared by
  `core/rules.py` and `brain/verify.py` with hamza normalisation; `check_reply` rewrites
  silently instead of appending meta-commentary naming the owner/rule.

### Fixed — YouTube / voice (rounds 2, 5, 6)
- Callback state keyed (chat_id, message_id, requester_id), TTL 10 min, non-requester clicks
  rejected, buttons disabled after first click, callback ids deduped, Semaphore(1) per group,
  non-URL query resolved via `ytsearch1:` with title/duration/size shown before download,
  `youtube_files` file_id cache so repeats re-send by file_id.
- Voice: random 12% → 5% only if reply <200 chars, never forced on mood>=90, cap 1/user/5min,
  ffmpeg via `asyncio.to_thread`, Edge TTS timeout 15s, text sent before voice.

### Fixed — reliability / ops (rounds 2, 4, 5, 6)
- `run_polling(timeout=30, allowed_updates=["message","callback_query","chat_member",
  "my_chat_member"], drop_pending_updates=True, bootstrap_retries=-1)`.
- Schema created once at startup (`init_db()`), `processed_updates` pruned >48h, startup disk
  sweeper for `data/downloads` + `data/voice` >1h.
- Telegram `RetryAfter` caught explicitly (sleep `retry_after`, retry once, never send a
  generic fallback on rate limit); structured JSON log line per LLM call (provider, model,
  latency, tokens in/out, reasoning, finish_reason, retries, status); owner-only `/stats`
  (provider usage today, remaining estimates, per-user counts).
- `setMyDescription`/`setMyShortDescription` parody text at startup from `rules.yaml`;
  `my_chat_member` handler (parody+privacy note on add, purge chat data on remove);
  owner-only `/reload` for persona/examples/rules (provider changes still need restart —
  `router.reload_config()` does not exist).
- `.gitignore` now ignores `.venv/`; `requirements-dev.txt` split out (pytest, pytest-asyncio,
  ruff); yt-dlp pinned; unused tenacity/google-genai/httpx removed; `providers.yaml`
  timeout/retries/log_level honoured (or the fields documented); Dockerfile non-root `USER app`
  + HEALTHCHECK (heartbeat file) + `PYTHONUNBUFFERED=1`; `render.yaml` `numInstances: 1`.
- Docs drift fixed: README OpenRouter line, status, and `/reload`/member-list claims now true;
  ARCHITECTURE.md rewritten short and true (plugins marked aspirational/stub, pinned_facts/
  outbox marked dead tables); DEPLOY.md gains ALLOWED_CHAT_IDS, Render Free SQLite-wipe
  warning, single-instance warning, webhook-secret note; `.env.example` cleaned
  (OPENROUTER_API_KEY / RENDER_EXTERNAL_URL removed, ALLOWED_CHAT_IDS added).
- **Pre-existing blocker found and fixed during v0.5:** the local `telegram/` package
  shadowed the installed python-telegram-bot library, so v0.4 could never have run as-is
  (`ImportError: cannot import name 'InlineKeyboardButton'`). Local package renamed to
  `tg/`; `from telegram import …` now always means the installed library.

### Deferred (explicitly NOT built in v0.5, with reason)
- Full RAG over Bahgat transcripts — needs audio download + Whisper transcription + manual
  cleanup (~1 day); keyword/prompt/grounding fixes were worth more first; do after live test.
- Voice-clone training (RVC/GPT-SoVITS) — needs Seif's explicit go/no-go on deepfake risk
  (impersonation/right-of-publicity); flagged, NOT trained.
- LLM-as-judge for search answers — useful but second-order once citations + grounding v2 exist.
- Structured BotPlan via LLM classifier — keyword intent + the v0.5 fixes are sufficient for v1;
  revisit if intent misses persist in live testing.
- Postgres migration — Render Free wipes SQLite on redeploy/restart; documented in DEPLOY.md
  (Neon free Postgres / Oracle Always Free VPS path + startup DB backup note) instead of
  migrating now, before the first live test proves the bot works.
- Full plugin-system rewrite — plugins/ stays a stub; service-layer extraction likewise deferred.
- PTB v22 upgrade — evaluated only: the venv already has PTB 22.8 and tests pass with it
  (`filters.ChatType.GROUPS` works on 21.x and 22.x); requirements still pin 21.11.1, upgrade
  is a one-line decision for deploy time.
- CI workflow — DONE after all: `.github/workflows/ci.yml` (ruff + pytest) was added in v0.5.

### Still blocks the live group test
- Seif must add @Bahgoti_bot as admin to the test group
  (https://t.me/+RN2Fksh8-KU3NWI0) so plain "بهجت" messages are delivered
  (can_read_all_group_messages is false).
- Seif must confirm the test group's numeric chat id so `ALLOWED_CHAT_IDS` can be set
  (currently empty = allow all, with a startup warning).
- Seif must paste the same three keys (Telegram token, Gemini, Groq) into Render env vars
  himself — Muse's Secure Vault keys are NOT available to Render.
- Unverified in this VM: real yt-dlp download/resolve (yt-dlp not installed here — only
  mocked), real Edge TTS + ffmpeg voice (edge_tts not installed here), live LLM calls
  against the new caps, `get_chat_member` with a username string, heartbeat/HEALTHCHECK
  observed live. The VM's `NO_PROXY` env breaks httpx (bracketed IPv6 entries) — smoke
  tests need a clean env; does not affect Render.

## 2026-11-25 — v0.7 fair-share quota core (brain/memory.py only)
Dynamic quota: the fixed caps are gone (100/user/day, 1500/group/day,
owner exemption — all retired, with `USER_DAILY_LIMIT` /
`GROUP_DAILY_LIMIT`, `group_pool_remaining()`, and the "user daily
limit reached" reason). Capacity C is now computed live from provider
budgets (`compute_pool_remaining`: per entry replies = min(RPD left,
TPD left / avg tokens per reply), pool = sum x 0.8 planning haircut)
and divided among the ACTIVE users by weighted max-min fair sharing
(docs/research-quota-fairshare.md, docs/research-quota-capacity.md).

### The scheme
- Config (`config/providers.yaml`, `quota:` section; mirrored as
  `QUOTA_*` module defaults in `brain/memory.py`): owner_weight 1.25,
  member_weight 1.0, active_window_days 7, saturation_threshold 0.50,
  borrow_multiple 2.0, floor_replies 20, planning_haircut 0.20.
- Active set: `last_triggered` table — a user is active if they
  triggered the bot within the rolling 7 days (returning users are
  instantly active; empty set counts as just the triggering user).
- Per-request decision (`check_and_consume_quota`, recomputed every
  turn): share = C x w / sum(w); ceiling = 2x share. Group hard
  ceiling first (used_group >= C -> "group daily limit reached"), then
  the floor (used_user < 20 -> always allow), then the binding limit:
  share when saturated (group used >= 50% of C), else the 2x ceiling
  ("fair share reached"). Already-consumed replies are never clawed
  back. `fair_share_info()` exposes the same numbers without consuming
  (for /stats). The owner is NO LONGER EXEMPT — he gets the 1.25
  weight instead (an exemption would break sum-to-C and let one user
  drain the pool). Capacity unknown (None) fails OPEN with a logged
  warning — a chat bot must not go silent over a missing number.
- Tokens/reply: `token_stats` table, EWMA lambda 0.15 per intent
  (chat/search, anything else bucketed as chat), cold-start blend
  avg = (30x1050 + total) / (30 + n), clamped >= 50. Only successful
  replies are recorded — cache hits and failed calls must never call
  `record_reply_tokens()`.
- Capacity rules: NVIDIA NIM is EXCLUDED from the planning pool
  entirely (trial terms: testing/evaluation only); disabled /
  exhausted entries contribute 0; OpenRouter entries share ONE
  account-wide 50 RPD cap (smallest cap among them, summed usage,
  counted once). Empty entries -> pool 0.0 (fail-closed; no fixed
  fallback number exists in the quota path).
- Degrade mode (`update_degrade_mode` / `get_degrade_mode`, persisted
  in `bot_state`): enter "cheap" when pool/full < 20%, exit only when
  > 30% (dead band), 15-min dwell once a mode is entered.

### NVIDIA NIM model corrected (live verification 2026-11-25)
Seif submitted the NVIDIA NIM key; verified live (models list returns 30
models, key works). BUT the v0.6-configured model
`nvidia/nemotron-3-super-120b-a12b` is RETIRED — it returns HTTP 410 Gone
and is not in the models list. The NIM entry in `config/providers.yaml`
now uses the verified working replacement
`nvidia/nemotron-3.5-super-vl-120b-a12b` (tested: replied in Egyptian
Arabic, 215 total tokens). Also verified NOT to use: `google/gemma-3-12b-it`
(404 on chat despite being listed) and
`nvidia/nemotron-3.5-lightning-30b-a3b` (returns None content —
reasoning-only with default params). Connector doc
`~/workspace/custom-connectors/custom.nvidia-nim/CONNECTOR.md`, helper
`bin/nim.py`. The key lives in the Secure Vault; at deploy time Seif
still pastes it into Render env vars himself (Vault keys are not
available to Render).

### Worked examples (C = 1,500)
| Active | Owner share | Member share | Borrow ceilings (owner / member) |
|---|---|---|---|
| owner + 2 (W=3.25) | 577 | 462 | 1,154 / 924 |
| owner + 14 (W=15.25) | 123 | 98 | 246 / 197 |

### Gemini timezone trap
Gemini RPD resets at midnight Pacific (08:00 UTC), NOT midnight UTC
like Groq/OpenRouter. The router workstream keys Gemini usage rows by
Pacific date; `memory.py` itself stays date-agnostic (it consumes the
entries snapshot it is handed).

### Router + handler integration (landed same day)
- Router: `_date_for(family)` keys Gemini usage rows by Pacific date
  (see trap above), all other families UTC; `pool_snapshot()` /
  `pool_remaining_replies()` expose the live pool; `chat(cheap_only,
  intent)` filters to cheap tiers {groq-20b, cerebras-120b,
  gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-gemma} — never
  gemini-3-flash-preview or nvidia-nemotron as primary; successful
  replies record EWMA tokens exactly once (`record_reply_tokens`).
  Provider order, 10s pacing, insult rules, persona untouched.
- Handlers: triggers recorded after the trigger gate (cache-hit turns
  count as activity); quota computed once per turn from live pool +
  active set + `quota:` config; hysteresis degrade replaces the old
  single 20% low-pool threshold (notice only on transition into cheap,
  ≤ once/hour/chat); `/stats` rewritten on live data — pool remaining
  in replies, per-user fair share used/limit, active users, avg
  tokens/reply (chat/search), per-provider remaining, cache hit rate,
  degrade mode + dwell hold. No more hardcoded "150k Groq" / "15 Gemini".
- Known follow-up (not fixed in v0.7): `_classify_429`'s TPD ban still
  computes seconds-until-midnight-UTC, so a Gemini TPD ban lasts until
  UTC midnight, not Pacific midnight.

### Tests
New `tests/test_fairshare_v07.py` (capacity formula, EWMA, active
set, fair-share math, hysteresis, retired surface) + new
`tests/test_router_handlers_v07.py` (Pacific-date keying, pool
snapshot, cheap-only filtering, EWMA-once-per-success, trigger
recording, hysteresis wiring, /stats) + the old fixed-cap tests in
`tests/test_cache_quota_v06.py` / `tests/test_memory_v5.py` /
`tests/test_pacing_v06b.py` replaced with fair-share equivalents.
**255 tests pass in .venv** (was 192), py_compile clean, ruff clean.

## 2026-11-25 — v0.6b: no hourly cap, 10s per-user reply pacing (Seif's call)
- **20/hour burst cap REMOVED** (`brain/memory.py`: `check_and_consume_quota`
  no longer takes `limit_hourly`, no hourly enforcement). Quota is now only
  100/user/day + 1,500/group/day, owner exempt. `hourly_usage` is still
  written (per-hour counts for /stats) but never blocks.
- **Anti-spam is now pacing, not dropping** (`tg/handlers.py`):
  `USER_REPLY_PACE_SECONDS = 10.0` — one reply per user per 10s in a chat.
  A second message is QUEUED: the handler waits until 10s have passed
  since that user's last reply was sent, then runs the turn. The timestamp
  is recorded when the reply is SENT (finally block), not when the message
  arrived, so replies stay >= 10s apart even when the LLM turn takes
  seconds. Replaces the old 3s drop-cooldown ("استنى ثانية" + drop).
  Pacing is per (chat, user); other users are unaffected.
- Tests: 192 pass in .venv (was 187), py_compile clean, ruff clean. New
  tests/test_pacing_v06b.py (pace math, per-user isolation, quota signature
  has no hourly parameter); burst-cap tests rewritten to assert 25 calls
  in one hour are all allowed.

## 2026-11-25 — v0.6 quota expansion (100 replies/user/day, FREE only, within ToS)
Two parallel workstreams (router/providers + prompt/cache/quota), integrated and
verified by the coordinator. **187 tests pass in .venv (pytest tests/ -q, ~15s),
py_compile clean, ruff check passes. `import main` + `build_application()` verified
(6 handlers).** No provider accounts or keys were created; nothing was deployed.

### The hard constraint (from research, non-negotiable)
Multi-account / multi-project rotation to multiply ONE provider's quota is an
explicit ToS violation (Groq AUP bars registering multiple accounts or
orchestrating usage between organisations; Google APIs ToS §2(d) bars
circumventing API limitations; OpenRouter governs capacity globally, so extra
accounts gain literally zero). The bot pools DIFFERENT providers only, one key
per provider, each inside its own published limits. No custom model was built:
no free hosted model has an unlimited quota, and a fine-tune does not raise
limits (limits are GPU-hours, not model quality).

### Fixed — the v0.5 Groq bug (efficiency research)
- `provider_usage` was keyed by provider name ("groq"), so the 150k daily token
  cap was counted COMBINED across gpt-oss-120b + gpt-oss-20b. Groq limits are
  PER MODEL (200k TPD each). Usage is now keyed per (provider, model, date):
  runtime migration in `brain/router.py` (`provider_usage_v2`, old rows preserved
  with `model=''` and counted conservatively toward every entry of that family).
  Caps are now 180k tokens/day per Groq model (safety margin under the real 200k).

### New providers (all OpenAI-compatible, base-URL swap; all OPTIONAL)
- Groq: added `qwen/qwen3.8-27b` as a third Groq tier (strongest Arabic of the
  three Groq models).
- Cerebras: `gpt-oss-120b`, base `https://api.cerebras.ai/v1`, env
  `CEREBRAS_API_KEY`, cap 1M tokens/day. Free-tier status CONFLICTS across
  sources (permanent 1M/day vs card-gated $5/30-day trial since Oct 2026) — on
  401/403/404 the entry is disabled in-memory with a server-side log only, and
  the router continues. Do NOT count its ~950 replies/day until console
  verification.
- NVIDIA NIM: `nvidia/nemotron-3-super-120b-a12b`, base
  `https://integrate.api.nvidia.com/v1`, env `NVIDIA_API_KEY`, cap 10,000
  req/day. FLAG: NIM trial terms say testing/evaluation only, NOT production —
  it is an overflow tier, never the primary (comment in code + providers.yaml).
- OpenRouter :free: env `OPENROUTER_API_KEY`, cap 50 req/day unfunded, models
  `google/gemma-4-31b-it:free` / `nvidia/nemotron-3-super:free`, with required
  `HTTP-Referer` + `X-Title` headers. Emergency spare only (last in every order).
- Gemini (same `GEMINI_API_KEY`, no new key): added `gemini-3.5-flash-lite` and
  `gemini-3.1-flash-lite` (500 RPD each) and `gemma-4-31b-it` (14,400 RPD,
  TPM-managed: in-router rpm guard ~9s between calls, ~7 calls/min sustained).
  `gemini-3-flash-preview` demoted to LAST resort, cap 20 RPD.
- Routing: Tier 1 simple chat Groq-20b → Qwen → Cerebras → NIM → Flash-Lite;
  Tier 2 hard/search Groq-120b → Qwen → Cerebras → Flash-Lite → Gemma →
  Gemini-Flash last; OpenRouter last everywhere. Least-used provider first
  within a tier (most remaining daily budget wins); Retry-After honoured per
  entry; exhausted providers skipped. Missing key = entry skipped silently
  (startup log lists enabled/disabled entries); `NO_KEYS_MSG` only when no
  provider has any key.

### Prompt compression + Groq prefix caching
- `PROMPT_VERSION = "6.0"`. Static prefix is now byte-identical across calls:
  `SYSTEM_BASE` (634 → 448 chars, −29%, all hard rules kept) + hard rules +
  `[STYLE EXAMPLES]` (ALL 7 few-shot pairs — they are static text, so they
  belong in the prefix). Dynamic blocks ([PERSONA CONFIG], [MEMBER], [MOOD],
  [INSULT RULE], [SEARCH RESULTS], deflection line) come AFTER, hard rules
  repeated at the very end. Verified: static prefix 1,444 chars / 722 tokens
  (len//2), identical for two different members/moods/search texts.
- Measured: full system prompt no-search 1,853 chars / 926 tokens (len//2);
  first call ~1,600 tokens, repeat calls pay only the dynamic part (~900 tokens
  incl. history/memory) once the 722-token prefix is a Groq cache hit
  (cached tokens do not count toward Groq rate limits).
- History 8 → 6 messages in the LLM turn; search excerpt stays capped at 800
  chars.

### Exact-match response cache
- New `response_cache` table (normalised_text, intent, mood_bucket, reply,
  created_at; TTL 1h; pruned to last 500 rows). Normalisation reuses
  `core.rules.normalize_arabic`. Mood bucket calm <70 / angry ≥70.
- Greetings/small-talk only — NEVER for search / YouTube / voice / insults /
  grudge replies / replies with citations. Cache is checked BEFORE quota:
  hits cost 0 tokens and 0 quota, are logged (`cache_hit=true`), and counted
  in `get_cache_stats()` (hits/misses/hit_rate, persisted in `bot_state`).

### Kill the wasteful double call + new quota scheme
- Factual questions (intent == search) already searched BEFORE the first LLM
  call; the unknown-retry second call now runs ONLY when no search ran. If
  search ran and the reply is still unknown, the in-character deflection is
  sent directly. Retry rate is logged (`record_unknown_retry` /
  `get_unknown_stats()` in `bot_state`).
- Quota (config-driven defaults in `brain/memory.py`: `USER_DAILY_LIMIT=100`,
  `GROUP_DAILY_LIMIT=1500`, `USER_HOURLY_LIMIT=20`): per-user 100 replies/day
  hard cap + 20/hour burst cap + per-group 1,500 replies/day shared pool (the
  real ceiling). Cached replies do not count; search/YouTube/voice DO count;
  owner (1415214630) is exempt (still counted for /stats). Group exhaustion
  gets its own reply ("يا عم الجروب خلص حصته النهاردة، بكرا نكمل").
- Graceful degrade: when the group pool drops below 20%, cheap tiers only
  (router), cached replies keep working, at most ONE in-character "battery
  low" notice per hour per chat — never a silent dead bot.

### Output caps + /stats
- Chat 600 tokens, search synthesis 600, Groq `max_completion_tokens` 1500
  (was 1500–2000), Gemini 4000 unchanged, Cerebras/NIM/OpenRouter 1500.
- `/stats` (owner-only) now lists ALL providers in `provider_usage` with
  requests/tokens today + remaining-replies estimate at current average,
  per-user top counts, cache hit rate, group-pool remaining %, unknown-retry
  rate.

### Capacity math (at ~1,050 tokens/reply after compression)
| Pool | Budget | Replies/day |
|---|---|---|
| Groq 3 models × 180k tok | 540k tok | ~514 (571 at real 200k) |
| Gemini Flash-Lite ×2 | 500 RPD each | 1,000 |
| Gemini Gemma 4 | 14,400 RPD, 15k TPM, ~7/min | ~9,600 (TPM-bound in practice) |
| Gemini Flash-preview (last) | 20 RPD | 20 |
| OpenRouter :free | 50 RPD shared | 50 |
| **Standing pool (no Cerebras, no NIM)** | | **~11,184/day** |
| + Cerebras (if free tier exists) | 1M tok/day | +~950 |
| + NVIDIA NIM (trial terms only) | 10,000 RPD | +10,000 |
Target is 1,500/day. Even WITHOUT Gemma the standing pool is ~1,584/day —
just above target; with Gemma ~7× headroom. Apply the research's ~50% haircut
for free-tier churn (models deprecated, limits moved without notice):
**~5,500/day expected-pessimistic, ~11,000/day expected** — comfortably above
1,500 either way, PROVIDED Gemma/Flash-Lite numbers hold in Seif's own AI
Studio project. The real binding constraint in practice is TPM/RPM bursts
(Groq 8k TPM window, Gemma 15k TPM), not daily totals — the router spreads
load across providers and the per-user 20/hour burst cap absorbs spikes.
Without Cerebras AND without Gemma the pool is ~1,584/day, i.e. exactly at
target with no headroom — Gemma is the load-bearing addition after Groq.

### Keys needed from Seif (new providers only — code + config ready, no key = entry skipped)
- `CEREBRAS_API_KEY` — console.cerebras.ai (or cerebras.ai dashboard → API Keys).
  Adds ~950 replies/day IF the permanent free tier still exists (verify in the
  console: 1M tokens/day; if it asks for a card / $5 trial, the tier is the
  30-day trial, not permanent — the bot still works, it just disables itself
  after the trial ends).
- `NVIDIA_API_KEY` — build.nvidia.com (NVIDIA Developer Program, phone
  verification; API key under the NIM model page). Adds up to 10,000 req/day
  as an OVERFLOW tier only (trial terms: testing/evaluation, not production).
- `OPENROUTER_API_KEY` — openrouter.ai/keys (free, no card). Adds 50 req/day
  unfunded as an emergency spare. (One-time $10 credit purchase would raise
  this to 1,000 RPD — a paid option, NOT built or required.)
Existing keys (Telegram, Gemini, Groq) unchanged. All three new keys are
optional — the bot starts and runs fine without any of them.

### Deferred (explicitly NOT built in v0.6, with reason + design note)
- Self-hosting (Modal $30 credits / Oracle Always Free VPS + Ollama small
  model): the only truly unlimited path, but it is a hosting project (VPS
  provisioning, hardening, model serving, restarts), not a router change; and
  the pooled free-API capacity above already covers 1,500/day with headroom.
  Design if ever needed: llama-server + Qwen3-8B Q4 (Modal T4, ~6s/reply,
  ~1,000/day within free credits) as Tier 1 bulk chat, Nile-Chat-4B on Oracle
  CPU as always-on fallback; Groq/Gemini keep hard/search. Revisit only if
  live traffic proves the API pool insufficient.
- Semantic cache (local sentence-transformers + FAISS, similarity ≥0.90):
  exact-match cache first (built now); semantic cache adds 20–30% on free-form
  banter per literature but risks stale/wrong-context roasts and needs an
  embeddings model in the image. Revisit after measuring real exact-cache hit
  rate in live traffic.
- Mistral La Plateforme: free-tier status CONFLICTS across sources (one says
  ~1B tokens/month Experiment tier, another says the free API was removed
  Nov 2026 and API needs billing). NOT added as a provider; re-check the
  console before ever adding it — if the Experiment tier exists it would be a
  large simple-chat overflow tier (2 RPM binds, so ~1,000–2,000/day max).
- LLM-as-judge for search, structured BotPlan classifier, Postgres migration,
  plugin rewrite, PTB v22 upgrade — still deferred as in v0.5 (see v0.5 entry).

### Still unverified live (flag in every report, not just here)
- Cerebras free-tier status (conflict above); NIM trial terms (production-use
  clause); Gemma 4 / Flash-Lite live RPD in Seif's own AI Studio project
  (Google publishes no per-model table; limits vary per project, "not
  guaranteed"); real Groq prefix-cache hit rates and actual token savings;
  real yt-dlp download, real Edge TTS/ffmpeg voice, live LLM calls against the
  new caps. No live LLM calls were made in v0.6 — all new-provider
  verification is adapter construction + mocked-error tests only.
- Still blocks the live group test: deploy (Render — Seif pastes his own keys
  in the Render dashboard; Vault keys are NOT available to Render), then live
  test in the group. The test group id is now known (-1005812444791) and the
  bot is already admin there (verified 2026-11-25 22:30 EET).

## 2026-11-25 — v0.7c Northflank deploy prep (health endpoint + BAHGAT_DATA_DIR)
- Health endpoint: new stdlib-only module tg/health.py — ThreadingHTTPServer
  in a daemon thread started from main.py next to run_polling, binds
  0.0.0.0:$PORT (default 8080). GET /healthz (alias /health) returns 200
  {"status":"ok","last_poll_age_seconds":N} when data/heartbeat.json is
  <300s old, else 503; other paths 404. Shuts down cleanly on SIGTERM via
  finally in main(). No new dependency, no secrets in logs (access logs
  silenced). Dockerfile HEALTHCHECK unchanged (still reads the heartbeat
  file); only its comment now mentions /healthz.
- BAHGAT_DATA_DIR env var (core/config.py data_dir()): the data dir was
  hardcoded in 4 places (brain/memory.py, tg/handlers.py, brain/router.py,
  tg/app.py) — now all four resolve from the env var, default
  <project root>/data. Set BAHGAT_DATA_DIR=/data on Northflank so bahgat.db
  lives on the persistent volume; without it the volume is useless.
- DROP_PENDING_UPDATES env var (core/config.py Settings, default true):
  drop_pending_updates was hardcoded True in main.py; set false on the
  deployed instance so messages sent while the bot was down are delivered
  on wake (Telegram holds updates 24h) instead of discarded.
- .env.example documents BAHGAT_DATA_DIR / DROP_PENDING_UPDATES / PORT.
- Deploy guide: docs/DEPLOY-NORTHFLANK.md (Egyptian Arabic) — Combined
  service, Dockerfile build from GitHub main, 1 instance, nf-compute-50
  (0.5 vCPU / 1 GB, $12/mo inside the $20 Sandbox credit), 1 GB volume at
  /data, HTTP port 8080, health check /healthz, all env vars to paste.
- Tests: 8 new in tests/test_health.py (200 fresh / 503 stale / 503 missing /
  /health alias / 404 / $PORT binding / data_dir() override / subprocess
  end-to-end proving all four modules resolve under BAHGAT_DATA_DIR).
  **263 tests pass in .venv, py_compile clean, ruff clean.**
- Verified: import main + build_application() builds 6 handlers;
  DROP_PENDING_UPDATES=false parses to False, default True preserved.
- Pre-existing VM quirk (NOT caused by this change): httpx.Client() raises
  InvalidURL on this VM's NO_PROXY value (bracketed IPv6 literals like
  [::1]); build_application() needs NO_PROXY unset in this VM. Deploy
  target is unaffected.
- Open blockers (not done here): (1) no GitHub repo exists yet for the bot —
  must be created + code pushed to branch main before Northflank can build;
  (2) Northflank requires a payment method for verification even on free
  Sandbox (billing docs, verified); Seif has no international Visa —
  options researched in docs/research-payment-cards-egypt.md (EverTry ~$4
  best, RedotPay, Pyypl, QNB/CIB USD debit; fake/generated cards cannot
  pass Stripe auth). No-card fallback: Render free web service.
