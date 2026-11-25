# Research: dynamic fair-share quotas for a multi-user group bot (2026-11-25)

Independent web research (read-only). Question: how do professionals divide a *variable* daily capacity among members when the per-user limit must NOT be a fixed number, unused capacity must not sit idle, and the owner gets a slightly larger share?

## Short answer
Weighted max-min fair sharing, computed per request from the *remaining* pool and the *active* user set, with a work-conserving borrowing rule (idle users' shares are lent to active users, reclaimed when demand returns). This pattern ships in LiteLLM's dynamic rate limiter, OmniRoute's quota-sharing engine, Linux HTB traffic shaping, and Mesos/YARN's DRF scheduler.

## 1. The standard algorithms
- **Max-min fair sharing**: give every user an equal share; if a user wants less, give them what they want and re-distribute the leftover evenly among users who still want more; repeat (water-filling). Splitting a shared quota evenly across four tenants can strand 45% of it unused when demand is skewed (demands [10,10,10,70] vs pool 100). Max-min drives stranded capacity to zero.
- **Weighted max-min / WFQ**: shares scaled by weight: `share(i) = remaining × w(i) / Σ w(j)`. Owner +25% is expressed this way. DRR (Deficit Round Robin) is the O(1) practical approximation used in NVIDIA Dynamo's LLM router; explicitly work-conserving across classes.
- **DRF** (Ghodsi et al., UC Berkeley 2011): weighted max-min for multiple resources; default in Mesos/YARN. For this bot one resource (replies/day) suffices; DRF matters only if metering tokens AND YouTube downloads.
- **Token bucket / HTB**: each class has `rate` (guaranteed minimum) and `ceil` (maximum when borrowing). A class may borrow unused bandwidth up to `ceil`; the moment a sibling needs its guarantee back, HTB reclaims it. Map: `rate` = fair share, `ceil` = borrow ceiling.
- **Work-conserving**: resource never idle while there is demand. VTC paper (arXiv 2401.00588) proves a fair LLM scheduler with 2× bound on service difference between backlogged clients, work-conserving. A 2026 ACM paper on multi-tenant inference ("token pools"): conventional rate limits "do not support work-conservation, so idle capacity cannot be borrowed by other tenants" — fixed with work-conserving backfill.
- **LiteLLM dynamic TPM/RPM allocation**: watches saturation; below a configurable threshold (default 50%) any key may use idle capacity ("generous mode"); above it, each priority level is held to its reserved share ("strict mode"). Explicit "borrow idle capacity" config.
- **OmniRoute quota-sharing engine**: work-conserving fair-share across keys; borrowing formula `maxAllowed = globalLimit − consumedByOtherKeys`; same 50% default saturation threshold; hard ceiling (`capValue`) always blocks.
- **Sliding-window / GCRA**: for short windows (seconds/minutes). For a daily quota a fixed window (UTC day counter) is fine. The bot already has the short-window layer (10s per-user pacing). No Redis needed at this scale: SQLite with one atomic transaction per decision is correct (HLD Handbook: Redis + Lua only for multiple instances).

## 2. Divide by ALL members or only ACTIVE members?
**Active members only — the single most important design decision, unanimous in the literature.**
OpenWebUI dynamic rate limiting write-up: "A static per-user limit (`user's requests this minute > G/N`, N being directory size) starves the budget whenever only a small fraction of seats are active… Both obvious limits use the wrong denominator. The right divisor is the number of active users." Formula: `rpm_user = clip(G / max(1, N_active), lo, hi)`. Upper clamp essential: "without it, a lone user inherits the whole budget."
- **Qualifying action**: user sent a message that *triggered the bot* (mention / "بهجت" / reply-to-bot). Not "sent any group message" — lurkers shouldn't dilute the denominator.
- **Window: rolling 7 days (WAU-style).** 24h too narrow (weekend-only friends swing in/out); 30 days too generous (one-time triers dilute shares for a month). Plus today's activity: anyone who triggers the bot today is active immediately.
- **Returning inactive member**: becomes active the moment they trigger the bot. Shares recomputed per request (never pre-reserved), so their share exists instantly — weighted fraction of the *remaining* pool, subject to the floor. No re-activation, no penalty.
- New user mid-day: denominator grows, others' future shares shrink slightly; already-consumed replies are never clawed back (check is forward-looking only).

## 3. Owner's extra share — clean formula
Weights: `w_owner = 1.25`, `w_member = 1.0`, `W = Σ w(j)` over active users, `share_i = C × w_i / W`. Always sums to C. The owner's share is 1.25× a member's at any capacity and any active count. Caveat: a weight only matters under contention — an idle owner doesn't "waste" 25%; his unused share flows to everyone else via borrowing.

## 4. Bursts: one spammer vs 15 normal users
Four controls in order: admission, fair dispatch, per-tenant execution budgets, downstream isolation. Daily-share layer needs:
1. **Saturation switch**: below 50% of daily pool used → generous mode (anyone over share may keep going while global remaining exists). Above 50% → strict mode (each user held to their share). LiteLLM `saturation_threshold = 0.50`, OmniRoute identical default.
2. **Borrow ceiling**: even in generous mode, one user must not inherit the whole pool. Recommended: up to **2× fair share**. With 3 active users at C=1,500, member share ~462, ceiling ~924. Global pool remains the absolute hard ceiling.
3. **Pacing bounds the rate of drain**: 10s pacing caps any user at 6 replies/min — pacing alone can't stop a daily drain (that's the share layer's job); the share layer alone can't stop a 60-message burst in 60s (that's pacing's job). Complementary layers.

## 5. Edge cases
- **Capacity changes mid-day**: never pre-assign fixed daily numbers at midnight. Compute share at decision time from current remaining pool and current active set. Provider dies → shares shrink; new key added → shares grow. Nobody's consumed replies are clawed back.
- **New member joins mid-day**: active on first trigger; denominator grows; floor guarantees first messages never rejected.
- **Member count unknown until first use**: denominator is the *observed* active set (7-day window + today), minimum 1. First user of the day gets share with N=1, split re-balances as others arrive. Correct behaviour: at 2am one chatting friend *should* be able to use the pool.
- **Cached / zero-cost replies**: don't count them. Fairness is defined on *cost*, not request count (VTC paper: fairness "based on a cost function that accounts for input and output tokens"). Groq excludes cached tokens from rate limits; Anthropic cache reads don't count toward ITPM. The bot's own SQLite cache makes zero provider calls — nothing to count. (Already implemented in v0.6.) Optional later refinement: meter weighted cost (search reply ~2,400 tok counts ~1.5× a chat reply ~1,550 tok) — keep replies for now; users understand replies.
- **Clock/timezone**: UTC days; rolling 7-day window for "active" (not calendar weeks) — no Monday cliff.

## 6. Recommended scheme (concrete)
Config (all dynamic, no fixed reply numbers):
```yaml
quota:
  owner_weight: 1.25
  member_weight: 1.0
  active_window_days: 7
  saturation_threshold: 0.50
  borrow_multiple: 2.0
  floor_replies: 20
  # capacity_today: computed live from provider budgets, NOT hardcoded
```
Per-request decision (recomputed every time):
```
share(user) = C × w(user) / Σ w(active users)
ceiling(user) = 2.0 × share(user)
```
Pseudo-code (cache hits return before this, as in v0.6):
```python
def check_and_consume(user_id, chat_id, capacity_today, active_members, owner_id):
    weights = {u: (1.25 if u == owner_id else 1.0) for u in active_members}
    total_w = sum(weights.values()) or 1.0
    w = 1.25 if user_id == owner_id else 1.0
    share = capacity_today * w / total_w
    ceiling = 2.0 * share
    used_user = daily_count(user_id, chat_id)
    used_group = daily_count(chat_id=chat_id)
    if used_group >= capacity_today:
        return False, "group daily limit reached"
    if used_user < FLOOR:
        return consume_and_allow()
    saturated = used_group >= 0.50 * capacity_today
    limit = share if saturated else ceiling
    if used_user >= limit:
        return False, "fair share reached"
    return consume_and_allow()
```
Notes: owner is NOT exempt from the formula — he has the bigger weight (exempting him entirely would break sum-to-C and let one user drain the pool; the v0.6 owner exemption should be replaced by the 1.25 weight). The floor is the only exception. State already exists in `daily_usage` + a `last_triggered_at` per (user, chat); active set is one query.

### Worked examples (owner weight 1.25, floor 20, borrow 2×)
| Scenario | Active | Total weight | Owner share | Member share | Borrow ceiling (owner / member) |
|---|---|---|---|---|---|
| C = 1,500; 3 active (owner + 2) | 3 | 3.25 | 577 | 462 | 1,154 / 924 |
| C = 1,500; 15 active (owner + 14) | 15 | 15.25 | 123 | 98 | 246 / 197 |
| C = 1,500; 1 active (owner alone, 2am) | 1 | 1.25 | 1,500 | — | 1,500 (pool is the ceiling) |
| C = 11,000; 15 active | 15 | 15.25 | 902 | 721 | 1,804 / 1,443 |
| C = 11,000; 3 active | 3 | 3.25 | 4,231 | 3,385 | 8,462 / 6,769 |

**Correction to the user's mental math:** "1,000 replies/day, 10 people, each gets 1,000" is not how division works — the *guarantee* is 1,000 ÷ 10 = 100 each. But that is the *floor of the guarantee, not the ceiling of what they can use*: with borrowing, a member chatting while the other 9 are idle can use up to 2× their share (200) in strict mode, and up to the whole remaining pool in generous mode. The number 100 is a *promise* ("you will always get at least this"), never a *cap*. If all 10 show up and all want 1,000, the pool is genuinely 1,000 and no algorithm can conjure more — max-min just guarantees the split is 100/100/… instead of first-come-first-served.

## 7. Sources
- Max-min fairness, water-fill: Duke CS 514 — https://courses.cs.duke.edu/fall18/cps214/slides/08FQandRED.pdf
- Max-min fairness, Jain index, token bucket: IIT Bombay CS224 — https://www.cse.iitb.ac.in/~mythili/teaching/cs224m_autumn2017/notes/lec18.txt
- Equal split stranding 45% of a shared quota; weighted max-min: Mallikarjun Reddy, *Quotas and Fair Sharing* — https://www.mallikarjunreddy.com/system-design/concepts/quotas-and-fair-sharing/
- Divide by *active* users; `clip(G / N_active, lo, hi)`; upper clamp: Adrián Jiménez, *Dynamic per-user rate limiting in OpenWebUI* — https://ajimenez.dev/blog/openwebui-dynamic-rate-limiting/
- Generous/strict saturation switch (default 50%), priority reservation, borrowing: LiteLLM, *Dynamic TPM/RPM Allocation* — https://litellm.vercel.app/docs/proxy/dynamic_rate_limit
- Work-conserving fair-share, saturation 0.5, `maxAllowed = globalLimit − consumedByOtherKeys`: OmniRoute, *Quota Sharing Engine* — https://omniroute.hagicode.com/en-US/routing/quota-share/
- Fair LLM serving, cost-function fairness, work-conserving, 2× bound (VTC): https://arxiv.org/html/2401.00588v2
- Token pools, work-conserving backfill: https://arxiv.org/html/2603.00356
- Token bucket vs sliding window vs GCRA; Stripe/GitHub/AWS: HLD Handbook — https://hld.handbook.academy/trade-offs/rate-limiting-algorithms/
- Token bucket default, Redis + Lua atomicity, rate limits vs quotas: HLD Handbook — https://hld.handbook.academy/curriculum/building-blocks/rate-limiting/
- DRR work-conserving scheduler: NVIDIA Dynamo docs — https://docs.nvidia.com/dynamo/knowledge-base/modular-components/router/deficit-round-robin
- WFQ/DRR, max-min: https://notes.elimelt.com/systems/scheduling/3-network-and-packet/fair-queueing-wfq-and-drr
- HTB `rate` vs `ceil`: https://ashimov.com/posts/linux-tc-traffic-control/
- HTB work-conserving: Oracle Acceleron — https://blogs.oracle.com/cloud-infrastructure/first-principles-networking-for-ai-scale
- DRF, Mesos/YARN, weights: Ghodsi et al. — https://courses.grainger.illinois.edu/cs425/fa2023/nsdi_drf.pdf
- DAU/WAU/MAU rolling windows: https://www.usedaymark.io/metrics/dau-wau-mau ; https://flowsery.com/blog/active-user-definition
- Cached tokens don't count (Anthropic/Groq): https://docs.tokenroute.io/docs/prompt-caching ; https://iadecider.com/articles/api-rate-limits-reference-2026 ; https://stochasticsandbox.com/posts/token-based-rate-limiting-for-llm-apis-2026-11-10/
- Four controls; DRR dispatch over active tenants: https://www.developers.dev/tech-talk/noisy-neighbors-in-multi-tenant-job-queues-a-tech-lead-s-design-for-fair-scheduling.html
- Admission vs dispatch; quotas vs rate limits: https://www.aibussin.com/books/advanced-agents-from-first-principles/21-chapter/
- One queue per tenant, round-robin dispatch: https://writeupcafe.com/one-customer-cannot-own-every-worker-fair-scheduling-for-llm-jobs
