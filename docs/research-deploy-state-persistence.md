# Research: free ways to keep a Telegram bot's STATE alive and the bot AWAKE (2026-11-25)

11 web searches. Read-only. Context: Python Telegram bot, local SQLite file (`data/bahgat.db`, a few MB, ~15 users) holding per-member memory, moods, grudges, daily quotas, response cache. Free hosts wipe the disk on redeploy/restart (Render free) or sleep after 15 min idle (Render free web service). Everything must be $0 forever.

## 1. Free persistent databases (instead of local SQLite)
### Turso (libSQL) — best fit for THIS bot
- Free tier (turso.tech/pricing, re-read 2026-10-26): 100 databases, **5 GB storage**, **500M rows read/month**, **10M rows written/month**, 3 GB syncs/month, 1-day point-in-time restore, no credit card. Older articles quote 9 GB / 500 DBs — those are the paid Developer numbers; Free is 5 GB / 100 DBs.
- Migration effort — smallest of all options. libSQL is a SQLite-compatible fork; the Python client (`libsql-experimental` / `pyturso`, sqlite3-style API) speaks the same SQL dialect, so the bot's existing `schema.sql` and queries transfer almost as-is. Headline feature is **embedded replicas**: the app keeps a local SQLite file that syncs with the cloud primary — reads hit the local file at disk speed, writes go to the primary and come back. That is exactly this bot's current architecture with a cloud backup built in.
- Catch: free databases are **archived after 10 days of inactivity** (unarchive via CLI or Platform API; the archive is not a deletion, data survives). The bot writes daily, so in normal use this never triggers — but a quiet spell over 10 days would make the bot fail on its next message until something unarchives it. Mitigation: a boot-time unarchive call via the Turso Platform API.
- Volume check: at ~1,500 replies/day with a few dozen row operations per reply, the bot is orders of magnitude under 500M reads / 10M writes per month.
- Sources: https://toolfreebie.com/turso-free-sqlite-database/ , https://github.com/sagargupta16/deploy-guide/blob/HEAD/guides/turso.md , https://botmonster.com/web-dev/turso-libsql-sqlite-edge-embedded-replicas/ , https://fshy.ajam.dev/p/turso/

### Neon (Postgres) — best Postgres, second overall
- Free tier (neon.com/pricing, checked 20 Nov 2026): **no time limit, no credit card**; 100 projects, **1 GB storage per project** (20 GB account total), **100 CU-hours compute per project per month**, autoscale to 2 CU (~8 GB RAM), **scales to zero after 5 min idle**, wakes in a few hundred ms on next query, 10 branches, 5 GB egress, 6-hour restore window. Hitting the CU-hour or egress limit **suspends compute until next month — it does not delete data**.
- Migration effort — moderate (~1 day). sqlite3 → psycopg: placeholders `?` → `%s`, autoincrement/serial differences, `ON CONFLICT` syntax mostly compatible, JSON handling differs, `PRAGMA`/WAL-isms go away.
- Binding constraint: 100 CU-hours at the smallest 0.25 CU = 400 compute-hours/month ≈ 13h/day of compute-on time. Each query wakes compute for at least the 5-minute idle window, so a bot chatted with in bursts all day can plausibly burn through it; a quiet bot stays far under.
- Sources: https://neon.com/faqs/managed-postgres-databases-free-tier , https://fastero.com/blog/neon-pricing , https://encore.dev/articles/neon-serverless-postgres

### Supabase (Postgres) — worse than Neon for this bot
- Free tier (checked Sep–Nov 2026): 500 MB database per project, **2 active projects**, 5 GB egress, 1 GB file storage, 50,000 MAU, shared CPU / 500 MB RAM, no card. **Free projects auto-pause after 1 week of inactivity** and must be manually resumed from the dashboard (restorable up to 1 year after pausing); no automatic backups on Free.
- Migration effort: same Postgres port as Neon. Less storage than Neon (500 MB vs 1 GB), and the pause is manual-resume — strictly worse for an unattended bot.
- Sources: https://makerkit.dev/blog/saas/supabase-pricing , https://dev.to/nayankyada/supabase-pricing-2026-free-tier-limits-compute-costs-when-to-upgrade-52af , https://fastero.com/blog/free-postgres-database

### Cloudflare D1 (SQLite) — right engine, wrong host
- Free tier (developers.cloudflare.com/d1/platform/pricing, checked 6 Nov 2026): **5M rows read/day, 100K rows written/day, 5 GB total storage, 10 databases, 500 MB per database**, no card, no expiry; limits reset 00:00 UTC. **Since 1 Sep 2026, free-plan queries fail once the daily quota is hit.** Time Travel restore 7 days on Free.
- Migration effort — high and awkward from Render. D1 is designed to be queried from inside a Worker via a binding, not as a remote database for a Python process elsewhere. From Render the only path is the D1 REST API (account-wide 1,200 requests/5 min) — rewriting every `sqlite3` call into HTTPS round-trips with a Cloudflare API token. Volume fits the quotas easily; the cost is the rewrite and the latency. Only makes sense if the bot itself moves to Workers — which kills yt-dlp/ffmpeg.
- Sources: http://developers.cloudflare.com/d1/platform/pricing/ , https://dev.to/signops/cloudflare-d1-free-tier-limits-what-counts-as-a-row-written-d6e , https://botnet.com/resources/tools-d1-vs-postgres-what-changed

### MongoDB Atlas M0 — wrong tool, big rewrite
- Free tier (checked Oct 2026): **free forever, 512 MB storage**, shared RAM/vCPU, **100 operations/sec**, 500 connections, 32 MB sort memory, **no backups**, one free cluster per project, **paused after 30 days with zero connections**.
- Migration effort — large. Document model: the bot's relational schema would be remodelled into collections; every query rewritten for pymongo. No benefit over Turso/Neon for a few MB of relational state.
- Sources: https://actualdatabase.com/mongodb-atlas-free-tier-limits/ , https://www.prisma.io/dataguide/mongodb/mongodb-atlas-setup.md , https://stackwrite.com/blog/free-tier-databases-2026/

### Upstash Redis — wrong tool as primary store
- Free tier (re-checked 7 Nov 2026): **250 MB data**, **500K commands/month** (~16,000/day), 10 GB bandwidth, 1 database, 10 MB max request, 100 MB max record, 10,000 commands/sec ceiling. **Free databases are archived after a minimum of 30 days of inactivity** (warning emails first; data backed up, restorable into a new database). The old "10,000 requests/day" figure is pre-March-2025; the current quota is 500K/month.
- Migration effort — large, and the meter binds. Redis is key-value, not SQL: the whole schema becomes hand-rolled keys. Worse, the command meter is the wrong shape: a single reply does ~20–50 small reads/writes, so 1,500 replies/day ≈ 30k–75k commands/day ≈ 0.9M–2.25M/month — **over the 500K free allowance**. Fine as an optional cache layer; wrong as the primary store.
- Sources: https://stackwrite.com/blog/upstash-free-tier-limits-2026/ , https://www.hivebook.wiki/wiki/upstash-redis-free-tier , https://actualdatabase.com/upstash-redis-pricing/

### Verdict table (for THIS bot)
| Option | Free limits | Expiry / sleep | Migration effort | Verdict |
|---|---|---|---|---|
| **Turso** | 5 GB, 500M reads/mo, 10M writes/mo | Archived after 10 days idle (data survives, unarchive via API) | Minimal (SQLite-compatible) | **Best fit** |
| **Neon** | 1 GB/project, 100 CU-hours/mo | Scales to zero, wakes in ms; suspends (not deletes) if CU-hours run out | ~1 day (Postgres port) | Best Postgres; CU-hours are the risk |
| Supabase | 500 MB, 2 projects | Paused after 1 week idle, manual resume | ~1 day (Postgres port) | Worse than Neon |
| Cloudflare D1 | 5M reads/day, 100K writes/day, 5 GB | No expiry; queries fail at daily cap | High (REST API rewrite) | Only if bot moves to Workers |
| MongoDB Atlas M0 | 512 MB, 100 ops/sec | Paused after 30 days idle | Large (document remodel) | Wrong tool |
| Upstash Redis | 250 MB, 500K commands/mo | Archived after 30 days idle | Large (KV remodel) + meter binds | Wrong tool as primary store |

## 2. Backup-to-object-storage pattern (nightly SQLite backup + restore on boot)
- **The stores:** Cloudflare R2 free = **10 GB-month, 1M Class A (writes/lists) and 10M Class B (reads) ops/month, zero egress fees** — restore costs nothing. Backblaze B2 free = **first 10 GB storage always free**, uploads free, egress free up to **3× average stored data/month**, then $0.01/GB; no card at signup. For a few-MB database, both are effectively infinite; R2 wins on zero egress and the bigger free op allowance.
- **The correct snapshot method:** SQLite's built-in **`.backup` command (or `sqlite3.Connection.backup()` API)** produces a consistent copy from a live database without stopping the process — a raw `cp` of a live WAL-mode database can corrupt the copy. Guides for SQLite-backed services (Vaultwarden, DocuSeal) all use `.backup` first, then tar/encrypt, then push via rclone or boto3 (S3 API), then prune old copies; R2 lifecycle rules expire objects past N days.
- **How people automate it:** three patterns — (a) **in-container cron** (a sidecar or a scheduler thread inside the bot process, e.g. APScheduler/asyncio task, uploading every N hours via boto3); (b) **host cron on a VPS** (03:00 snapshot → tar → encrypt → rclone to R2, prune local copies older than 14 days); (c) **external scheduler hitting an endpoint** (cron-job.org → `/backup` URL) — possible but it exposes a privileged endpoint to the internet, so it needs a secret token header. For a Render-hosted bot, (a) is the only self-contained option: Render's disk is not reachable from outside, so no external job can pull the file — the bot must push it.
- **Data loss on a wipe:** exactly the backup interval. Nightly = up to 24h of moods, grudges, quota counters and new members lost; hourly = up to 1h. The file is a few MB and R2's free op allowance is 1M writes/month, so **hourly backups cost the same $0 as nightly** — there is no reason to accept a 24h window. Add a restore-on-boot step (if local `bahgat.db` is missing/empty, download the latest backup before `init_db()` runs) and the worst case becomes "lose at most the last hour, only when a wipe happens".
- **Is it enough for a bot whose personality is its memory?** Honestly: **no, not as the only mechanism.** It bounds the loss instead of eliminating it, and it does nothing about the bot being unable to *write* durably between backups. It is a safety net, not persistence. The professional shape is: real cloud database as the primary store (Turso or Neon) **plus** object-storage backups as disaster recovery — the backup then protects against "the cloud DB itself dies or the account is suspended", not against Render wiping the disk.
- Sources: https://techloverhd.com/2026/10/vaultwarden-docker-restic-cloudflare-r2-backup/ , https://create.borecraft.com/docuseal-setup/ , https://vibecoderslife.com/post/free-database-storage-vibe-coding-2026 , https://www.cloudhim.com/cloudflare/cloudflare-free-plan-what-you-get , https://upstash.com/blog/backblaze-b2-pricing-explained-2026

## 3. Free uptime monitors / pingers (keep a free web service awake)
- **The mechanism:** a free web service spins down after **15 minutes without inbound traffic**, and spins back up on the next request (~30–60s). An inbound HTTP request resets the idle timer — that is why pinging works. It is a **workaround, not officially supported**: Render's community/docs note there is no officially supported way to keep a free service running continuously, and the recommended fix is a paid instance. In practice the ping workaround is widely used and works, but treat it as "usually reliable", not guaranteed.
- **The hours math:** Render grants **750 free instance hours/month**; spun-down services don't consume hours, but a service kept awake 24/7 consumes ~720–744h — **the whole allowance for one service**. A second free Render service used as the pinger would burn the budget; the pinger must be external and free.
- **UptimeRobot (free):** **50 monitors, 5-minute minimum interval**, email alerts, no card. GET requests only — no custom headers, no POST, no auth. A 5-minute ping against a lightweight `/healthz` endpoint is the standard recipe in dozens of Render keep-alive guides; 5 min is well inside the 15-min sleep window.
- **cron-job.org (free):** **entirely free, donation-funded, no paid tier, no card**; **unlimited jobs** (fair use), **1-minute minimum interval**, custom HTTP method/headers/body, failure/recovery email alerts, status pages, REST API. Limits: **30-second execution timeout**, only the first 64 KB of response read, last 50 executions viewable, history kept 2 days, jobs failing 25 times in a row are auto-disabled, no SLA. For a keep-alive ping it is strictly more flexible than UptimeRobot (custom headers let you ping an authenticated endpoint; 1-min granularity lets you use a 10-min interval with margin). A 10-minute interval is the usual choice: inside the 15-min window with 5 minutes of slack for a missed ping.
- **Alternatives:** GitHub Actions scheduled workflow (`*/14 * * * *` curl) — free tier includes 2,000 Actions minutes/month for free accounts, but scheduled runs are unreliable (delays, and GitHub disables scheduled workflows after 60 days of repo inactivity). Better Stack free tier exists but its free plan is monitoring-oriented with fewer monitors than UptimeRobot. Google Cloud Monitoring free tier can do uptime checks but needs a GCP project and is overkill for one URL.
- **What pinging does NOT fix:** it keeps the process awake, but it does not make the disk persistent — a redeploy or a Render-initiated restart still wipes SQLite. Pinging and persistence are two separate problems; a pinger without a cloud DB/backup still loses memory on every deploy.
- Sources: https://github.com/mabelmoncy/transcriberappwithserver/blob/HEAD/backend/UPTIMEROBOT_SETUP.md , https://blog.samkiel.dev/your-render-free-tier-is-not-broken-its-just-cold , https://github.com/community/community/discussions/197645#discussioncomment-17145147 , https://watchcron.com/guides/keep-alive-free-tier-hosting , https://freetier.co/articles/free-tier-background-jobs-cron-2026 , https://merginit.com/blog/26062026-free-cron-job-scheduler-comparison

## 4. Combined recommendation — the $0 stack
**Recommended: Render free web service + cron-job.org pinger + Turso (embedded replica) + hourly R2 backup.**
| Layer | Choice | Why | $0 forever? |
|---|---|---|---|
| Host | Render free **web service** (not worker — free tier doesn't cover workers) | Zero rewrite: Docker, polling, yt-dlp, ffmpeg all work | Yes — 750h/mo = exactly one service 24/7 |
| Awake | **cron-job.org**, GET `https://<app>.onrender.com/healthz` every 10 min | Free, unlimited jobs, 1-min granularity, custom headers; 10 min is inside the 15-min sleep window with slack | Yes |
| State (primary) | **Turso**, embedded-replica pattern (local file + cloud sync) | SQLite-compatible = smallest migration; 5 GB / 500M reads / 10M writes dwarfs this bot; no compute-hour meter | Yes — add boot-time unarchive check for the 10-day rule |
| Safety net | **In-process hourly backup** of the DB file to **Cloudflare R2** (10 GB free, zero egress) + restore-on-boot if local file missing | Bounds wipe loss to ≤1h; restore costs nothing; also protects against Turso account problems | Yes |
| Fallback if Turso ever becomes a problem | **Neon** Postgres (1 GB, 100 CU-hours, never expires) | Best permanent free Postgres; ~1 day port | Yes |
**Cheaper-to-build alternative (zero migration, slightly weaker):** Render + cron-job.org pinger + **hourly R2 backups only, no cloud DB**. Zero code changes beyond the backup thread and restore-on-boot. Loss window is ≤1 hour of memory on a wipe, and the bot cannot write durably between backups — acceptable for a fun group bot, not for anything where the memory is load-bearing. Upgrade to Turso later if wipes become frequent.
**Endgame (free forever, no wipes, no rewrites):** Oracle Always Free VPS (2 OCPU / 12 GB ARM, 200 GB disk, never sleeps) — the bot runs exactly as it runs locally, SQLite survives on a real disk. Costs a day of Linux setup + card verification, so it is a weekend migration, not today's deploy. Sequence: Render + pinger + Turso + R2 backup now → Oracle later if Render's sleep/restarts become annoying.
**What NOT to do:** don't use a second Render free service as the pinger (burns the 750h budget); don't rely on nightly-only backups (hourly is equally free); don't pick Supabase for an unattended bot (manual resume after a week idle); don't pick D1/Upstash/Mongo as the primary store for a Python polling bot on Render (wrong runtime, wrong data model, or a meter that binds).

## 5. Sources
- Neon free tier: https://neon.com/faqs/managed-postgres-databases-free-tier
- Neon pricing (checked 20 Nov 2026): https://fastero.com/blog/neon-pricing
- Neon serverless Postgres guide: https://encore.dev/articles/neon-serverless-postgres
- Free Postgres comparison (checked 12 Nov 2026): https://fastero.com/blog/free-postgres-database
- Turso free tier (pricing re-read 2026-10-26): https://toolfreebie.com/turso-free-sqlite-database/
- Turso Python + free tier: https://github.com/sagargupta16/deploy-guide/blob/HEAD/guides/turso.md
- Turso embedded replicas: https://botmonster.com/web-dev/turso-libsql-sqlite-edge-embedded-replicas/
- Turso 10-day archive rule: https://fshy.ajam.dev/p/turso/
- Supabase pricing 2026: https://makerkit.dev/blog/saas/supabase-pricing
- Supabase free-tier limits: https://dev.to/nayankyada/supabase-pricing-2026-free-tier-limits-compute-costs-when-to-upgrade-52af
- Cloudflare D1 pricing: http://developers.cloudflare.com/d1/platform/pricing/
- Cloudflare D1 free-tier limits: https://dev.to/signops/cloudflare-d1-free-tier-limits-what-counts-as-a-row-written-d6e
- D1 vs Postgres limits changes: https://botnet.com/resources/tools-d1-vs-postgres-what-changed
- MongoDB Atlas M0 free tier: https://actualdatabase.com/mongodb-atlas-free-tier-limits/
- MongoDB Atlas setup / free-cluster limits: https://www.prisma.io/dataguide/mongodb/mongodb-atlas-setup.md
- Free databases 2026 compared: https://stackwrite.com/blog/free-tier-databases-2026/
- Upstash Redis free tier: https://stackwrite.com/blog/upstash-free-tier-limits-2026/
- Upstash Redis free tier (verified 2026-10-03): https://www.hivebook.wiki/wiki/upstash-redis-free-tier
- Upstash Redis pricing: https://actualdatabase.com/upstash-redis-pricing/
- SQLite backup to R2 (Vaultwarden + restic): https://techloverhd.com/2026/10/vaultwarden-docker-restic-cloudflare-r2-backup/
- SQLite `.backup` + R2 + rclone pattern: https://create.borecraft.com/docuseal-setup/
- Free database + storage map (R2/B2): https://vibecoderslife.com/post/free-database-storage-vibe-coding-2026
- Cloudflare free plan (R2 10 GB, zero egress): https://www.cloudhim.com/cloudflare/cloudflare-free-plan-what-you-get
- Backblaze B2 pricing (first 10 GB free, 3× egress): https://upstash.com/blog/backblaze-b2-pricing-explained-2026
- UptimeRobot keep-alive for Render: https://github.com/mabelmoncy/transcriberappwithserver/blob/HEAD/backend/UPTIMEROBOT_SETUP.md
- Render free tier cold starts + UptimeRobot: https://blog.samkiel.dev/your-render-free-tier-is-not-broken-its-just-cold
- Render sleep workaround discussion: https://github.com/community/community/discussions/197645#discussioncomment-17145147
- Keep-alive with external cron (750h budget): https://watchcron.com/guides/keep-alive-free-tier-hosting
- Free background jobs / cron compared: https://freetier.co/articles/free-tier-background-jobs-cron-2026
- Free cron schedulers compared: https://merginit.com/blog/26062026-free-cron-job-scheduler-comparison
