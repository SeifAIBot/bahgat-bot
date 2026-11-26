# Research: intent routing without slash commands (v1.0)

Seif's question (2026-11-26, after the v0.9 live test): routing between
internet search / YouTube / normal chat feels too hard for the bot, and
trivial chat ("شكرا يا بهجت") triggers a full "thinking" turn. He asked
for three modes (search / YouTube / fast normal chat), and whether
professionals use modes or whether slash commands are unavoidable.

**Short answer: neither modes nor slash commands are needed.** The
professional answer is a layered router with a cheap fast path: rules
first (<1 ms), a small classifier only where rules are ambiguous, and the
LLM only for genuinely open-ended turns. This document is the evidence
for that call. Implemented in v1.0 (see CHANGELOG).

## 1. The layered router is the production standard

- **Cascade routing** (TechByteByByte, "The Routing Pattern"):
  rule-based routing (<1 ms) → classifier-based (50–100 ms) →
  LLM-based routing (most flexible, most expensive, reserved for
  genuinely ambiguous cases). "Most teams send everything to GPT-4o
  because it is the safe default. That is like hiring a neurosurgeon
  to take your temperature."
  https://www.techbytebybyte.com/tutorials/agent-design-patterns/03-routing-pattern/
- **Multi-stage routing** (Xupeng Wang, "Agent Intent Recognition",
  Medium, Oct 2026): rules → embedding retrieval → LLM reranking →
  clarification when confidence is low. The hard part is
  disambiguation (a word with several senses, blurred intent
  boundaries), not the routing itself.
  https://medium.com/@marvelous_catawba_otter_200/agent-intent-recognition-the-problems-that-never-went-away-from-the-rasa-era-to-the-llm-era-271943c823dd
- **Google Assistant and Siri do not use a generative LLM for command
  routing** (Hark NLU architecture doc): both use specialized NLU
  models (BERT-based intent classifier + BiLSTM-CRF slot tagger).
  "Generative models do not appear in the command-routing hot path of
  any major voice assistant." The right model type for routing is an
  encoder (classifier), not a decoder.
  https://github.com/christhekey/hark/blob/HEAD/docs/nlu-architecture.md

**What this means for Bahgat:** 4 intents (voice / youtube / search /
just_chat) is a tiny routing problem. A keyword layer with proper
normalization plus a media-noun + verb rule covers it; an ML
classifier would be over-engineering (training data, a model to host,
and it still needs the same normalization). The LLM router is what we
already have as the *fallback* (the unknown-retry loop) — it must not
be the first hop, because every turn would pay a full model call
before doing any work. Slash commands are a UX crutch for bots whose
router cannot disambiguate; they are not required by any of the above.

## 2. Fast path for small talk: canned replies, no model call

- **Pilot's conversational bot** (Slack/Telegram): every message is
  classified, then routed to a fast path (greetings/chat, ~1–2 s) or a
  slow executor (15–30 s). Routing is a small Haiku classifier, but
  "a regex layer only fast-paths `/`-commands and **obvious
  greetings**" — i.e. even a system built around a classifier keeps a
  regex fast path for the trivial cases.
  https://github.com/qf-studio/pilot/blob/HEAD/docs/content/features/conversational-bot.mdx
- **Telegram autoresponder practice**: "Three to ten triggers cover
  most routine questions" (keyword triggers + saved replies);
  templates are for predictable messages, and "if you typed the same
  answer three times in one week, make it a template" — but replies
  to complaints/apologies must stay personal, not templated.
  https://www.telegramchannels.io/articles/telegram-auto-reply-bot
  https://telegram.mycrm.sh/en/blog/telegram-quick-replies-templates

**What this means for Bahgat:** greetings / thanks / acks / laughter /
bare "بهجت" get an instant local reply from a small Bahgat-voiced set
— no LLM call, no quota, no status bubble. Guard rails (from the
same sources): only genuinely trivial turns (short, no question, no
insult, no apology, calm mood); anything with content still goes to
the LLM. An apology ("خلاص انا اسف") is explicitly NOT fast-pathed:
the forgiveness flow is a real conversation, not a template.

## 3. Arabic normalization: normalize BOTH sides

- **Larkey, Ballesteros & Connell (SIGIR 2002)**, Arabic retrieval on
  TREC-2001: normalizing (strip diacritics, unify alef forms, map
  word-final ى and ة) raised average precision from .194 to .238
  (+22.7%) for keyword search. Cited in BroadRouter's Arabic
  normalization guide.
  https://broadrouter.com/blog/arabic-text-normalization-search/
- **Standard rule set** (BroadRouter, LexSense, SahlNLP): Unicode
  NFKC → strip tashkeel and tatweel → unify أ/إ/آ → ا → ى → ي →
  ة → ه → collapse whitespace. Apply the *same* steps to the stored
  copy and to every query; keep the original text for display and
  for the LLM.
  https://broadrouter.com/blog/arabic-text-normalization-search/
  https://lexsense.net/article/arabic-orthographic-normalisation/
  https://pypi.org/project/sahlnlp/1.2.0/
- **Known merge cost** (all three sources): ى → ي merges على ("on")
  with علي ("Ali"). For intent matching that merge is a *feature*,
  not a bug: "دور على" and "دور علي" are the same request.
- **The v0.9 latent bug this explains:** the bot normalized the
  *message* but matched it against *raw* keyword lists, so any list
  entry written with ى/ة could never match ("دور على" in
  _SEARCH_WORDS was dead — the text normalizes to "دور علي").
  The fix is to normalize the keyword lists too (normalize at match
  time), not to list both spellings.
- **Dialect verb forms** ("دورلي" vs "دور لي", "هاتلي" vs "هات لي"):
  handled by listing both forms; a space-collapse in the normalizer
  was considered and rejected (too easy to merge real words).
- **Franco-Arabic** (Latin-letter Arabic, e.g. "ehalt Marwan pablo"
  in the 03:24 video): evaluated and **deferred** — it needs a
  transliteration map and a much larger false-positive surface, and
  Seif types Arabic. YouTube itself still matched the Franco query
  in the earlier test; the router just needs the Arabic forms.

## 4. YouTube search robustness: strip, then retry

- **Cross-service matching hierarchy** (SongMirror / TuneLink /
  MusicBrainz practice): hard identifier → search → fuzzy score
  (RapidFuzz `token_set_ratio`, order- and subset-tolerant, over
  raw + romanized title/artist, anchored by duration). Unconfident
  matches are reported, not guessed.
  https://github.com/ahnafnafee/songmirror/commit/512eaad01644830d9604ffa874e966e0a29f41e7
- **Rhapsod (music bot)**: "Query parsing strips leading articles
  ..., fuzzy matching ..., **shortened-query retry**, and duration-
  based candidate selection" — i.e. when the first query misses,
  retry with a shorter query instead of failing.
  https://github.com/juanzaan/rhapsod/blob/HEAD/CHANGELOG.md
- **music-sync**: normalized titles strip noise
  ("(Official Video)", "(Remaster)", "(feat. …)") before scoring;
  free-text search is tier 2, triggered only on tier-1 miss.
  https://github.com/mantreejoe/music-sync/blob/HEAD/CLAUDE.md

**What this means for Bahgat:** strip the request words ("دورلي
علي", "عايز", "هاتلي", "ممكن") + the trigger + the @mention +
the media noun ("اغنية") before calling ytsearch, so the query is
bare artist + title; if 0 results, retry once with a variant
(query + "اغنية", which helps YouTube's music ranking). The pick-list
itself is the disambiguation UI (the user picks), so no fuzzy
re-ranking is needed on top of ytsearch's own ranking.

## 5. When to show "thinking": only for slow work

- **Telegram typing indicator lasts ~5 s** (or until the next
  message); for longer jobs re-send every 4–5 s
  (ConferBot glossary).
  https://www.conferbot.com/glossary/term/typing-indicator
- **Nielsen Norman Group** (via UX Shine): delay any indicator until
  ~1 s; indeterminate spinner for waits of a few seconds; labelled
  steps when tools are called and work takes several seconds.
  https://www.uxshine.com/blog/how-to-design-ai-chatbot-user-interface-2
- **"Never fake slowness on the first response"** (Vayt, 2026):
  artificial "thinking" delays on task queries are the one pattern
  the research unambiguously punishes; "if your answer is ready in
  800 milliseconds, send it in 800 milliseconds." Typing indicator
  beyond ~1 s; a brief text status only when processing passes
  ~5 s ("Searching for information...").
  https://www.vaytai.com/blog/chatbot-response-time-best-practices
  https://www.conferbot.com/blog/chatbot-ui-design-best-practices

**What this means for Bahgat:** the "بفكر يا عم، استنى…" bubble is
a *status message for slow operations* (search, YouTube, download —
work that takes seconds), not a generic "I'm thinking" for every
turn. Plain chat LLM turns get the typing indicator only (which is
what the indicator is for: 1–3 s of model time). The fast path gets
neither — the answer is already there.

## 6. The prefix layer: Seif's design IS the professional pattern (hybrid routing)

Seif's own idea (2026-11-26 ~07:51 EET, added to the v1.0 scope):
start a sentence with **"دور"** → internet search mode, **"هات"** →
YouTube mode, **"قول"** → voice-note mode. Normal chat stays as-is,
and if the bot understands from the talk that a mode is wanted it
runs it without needing the prefix word.

- **Hybrid routing is the consensus** (nullfeather, "LLM Intent
  Classification: Patterns That Actually Work", dev.to, 2025;
  dreaming.press, "The Hybrid Intent Classifier"; ai-engineering.
  academy; getreadyforagents.com): deterministic rules first for
  unambiguous triggers, an ML/LLM classifier for the ambiguous tail,
  with a confidence threshold deciding when to escalate. Rules are
  instant, free and deterministic; the classifier covers what rules
  cannot; the LLM is the last resort. Keyword-only routing caps at
  ~60% accuracy; an LLM classifier with a confidence threshold lifts
  it past 90% — which is why the prefix layer is tier 1 (instant,
  free, deterministic) and the implicit understanding (the keyword
  classifier + the LLM unknown-retry) is the essential fallback,
  not a bonus.
  https://dev.to/nullfeather/llm-intent-classification-patterns-that-actually-work-2mja
  https://dreaming.press/the-hybrid-intent-classifier/
  https://ai-engineering.academy/
  https://getreadyforagents.com/
- **The same shape already exists in production bots**: Telegram
  bots route on first-word triggers ("play", "search") before any
  model call, and voice assistants treat a leading verb ("play…",
  "search…", "tell me…") as the command — the user is doing the
  disambiguation the router would otherwise have to guess at, for
  free.
- **Guards, from the same logic** (a deterministic rule must not
  force a wrong mode):
  - "دور" also means "your turn/round" — "دور مين؟" must NOT
    search. Guard: the prefix needs a non-trivial, non-question
    remainder, else fall through to the classifier.
  - "هات" can request non-media — "هاتلي ملخص" is a summary, not a
    video. Guard: the "هات" prefix needs a media noun in the
    remainder; "هاتلي" (not the bare word "هات") is not a prefix at
    all — it goes to the classifier, where the media+verb rule
    decides ("هاتلي اغنية" → YouTube, "هاتلي ملخص" → search).
  - "قول" is voice output, not a different brain: the reply is
    generated as usual (joke, answer, insult — any content), then
    sent as a voice note *instead of* text, with the text as the
    fallback if synthesis fails. Voice is the current Edge TTS voice
    until RVC is wired — the prefix must not block on RVC.
  - Voice still outranks every prefix ("هات فيديو بصوتك" is a voice
    request), the same priority the classifier already had.

**What this means for Bahgat:** the three prefixes are implemented
as `detect_prefix_mode()` in `brain/intent.py`, checked first inside
`detect_intent()` (word-boundary, normalised, trigger word "بهجت"
stripped before the first word is read). The remainder after the
prefix word is the query — a prefix search is self-contained, so it
never gets the follow-up topic inheritance. Everything else is
unchanged: no modes UI, no slash commands.
