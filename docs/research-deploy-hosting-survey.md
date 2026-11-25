# Free hosting survey for the Bahgat bot — every $0 option in 2026 (2026-11-25)

Independent web research (16 searches, figures checked against vendor pricing/docs and roundups dated Oct–Nov 2026). Deciding constraints: long-polling (outbound-only), Python 3.12 + Docker image, SQLite file must survive restarts, yt-dlp + ffmpeg must run (video/audio ≤50 MB, MP3→Opus voice), one always-on process, ~15 users, owner in Egypt. Anything serverless/webhook-only or without a real disk or without ffmpeg is disqualified on architecture, not price.

## The three that actually work
### 1. Northflank Sandbox — dark horse, best "deploy today"
- Free forever: Sandbox plan, up to **$20/month of resources**, "always on, no sleeping", 2 services + 2 jobs + 1 database. No expiry stated.
- Specs: one small service fits: `nf-compute-50` (0.5 vCPU, 1 GB RAM) costs $12/month inside the $20 credit; volumes and a database addon included.
- Always-on: yes — the **only free PaaS found that does not sleep**. Runs Docker images, ffmpeg + yt-dlp unchanged, volumes mean SQLite survives restarts.
- Card: CONFLICT — pricing page says "no card needed", but billing docs say a payment method is required to create resources on any plan. Unresolved — test at signup.
- Catches: docs say Sandbox is "not for production"; $20 credit is a hard ceiling; no SLA; small platform, less battle-tested.
- Verdict: best deploy-today choice — zero rewrite, always on, persistent disk. Only question is the card at signup.
- Sources: https://xcloud.host/best-free-docker-hosting/ · https://aifree.dev/offer/northflank-developer-sandbox · https://outplane.com/blog/docker-hosting

### 2. Oracle Cloud Always Free VPS — most powerful $0 option, best "forever home"
- Free forever: Always Free, "for the life of the account". No expiry.
- Specs (cut in half June 2026): Ampere A1 ARM **2 OCPUs / 12 GB RAM** (was 4/24), 200 GB block storage, **10 TB/month egress**, plus 2 tiny AMD micro VMs. Real Linux server — Docker, systemd, ffmpeg, yt-dlp, SQLite on a real disk, all as-is.
- Always-on: yes, never sleeps. No hourly cap. Card required for verification.
- Catches: (a) **capacity lottery** — "Out of host capacity" is common; home region is permanent, pick well (Frankfurt is close to Egypt and usually provisions); retry smaller shape (1 OCPU/6 GB) or another availability domain. (b) **Idle reclaim** — Oracle may reclaim an instance if over 7 days its 95th-percentile CPU *and* network *and* (A1) memory are all under 20%. A quiet polling bot is mostly idle, so this risk is real; mitigation is a small periodic load or accepting the risk. (c) You are the sysadmin: OS updates, firewall, SSH hardening, backups.
- Verdict: best long-term home — only option with serious hardware, a real disk and no sleep, at $0 forever. Costs a day of Linux setup + card + capacity luck.
- Sources: https://www.computerandmobile.com/oracle-cloud-free-tier-vps/ · https://terminalbytes.com/oracle-cloud-free-tier-changes-2026/ · https://askgpu.com/free-vps-tiers-oracle-aws-google-azure/ · https://dev.to/travenwest/what-you-can-self-host-on-oracle-cloud-free-tier-2026-3gfd

### 3. Render free web service — easy fallback (with two known flaws)
- Free forever: 750 instance-hours/month per workspace (744-hour month = one service 24/7, nothing else).
- Specs: 512 MB RAM, ~0.1 CPU, 100 GB bandwidth, 500 build minutes/month. No card required per Render docs (some third-party reports say a card is asked at deploy — minor conflict).
- Always-on: no — **sleeps after 15 min idle**, ~1 min wake. Needs health endpoint + external pinger every ~10 min (the pinger burns the same 750-hour budget).
- Critical: free tier covers **web services only — background workers are NOT free**. The bot's `render.yaml` as a worker cannot deploy free; must become a web service binding `$PORT`.
- SQLite: NO — ephemeral filesystem: **wiped on every redeploy, restart or spin-down**. Free Postgres expires after 30 days. Mitigation: nightly backup to R2, or Neon free Postgres.
- Verdict: works today with zero code rewrite except a health endpoint, but the bot sleeps and forgets everything on every restart. Acceptable for testing, bad as a permanent home.
- Sources: https://docs.render.com/free (verified directly in prior research) · https://flaviocopes.com/hosting-free-tiers/ · https://bex.co/blog/2026/09/20/free-tier-dead-2026-zero-to-free-side-project-paas

## Real VMs from the big clouds (12-month or tiny)
### 4. Google Cloud e2-micro — always free, with one clever catch avoided
- Always free: one e2-micro/month, **only in us-east1, us-west1, us-central1** (US regions; farther from Egypt). 0.25 shared vCPU, 1 GB RAM, 30 GB disk, 1 GB egress. $300/90-day trial credit is separate and expires. Card required.
- The catch that matters: a public IPv4 address costs ~$3.65/month (not free). **But a polling bot needs no public IP at all** — outbound-only. Run the VM without an external IP and it is genuinely $0. (Cloud Run free 2M requests/mo is irrelevant: scale-to-zero, no long-polling, no ffmpeg.)
- Verdict: truly $0 and always-on if you skip the external IP; but weak (0.25 CPU/1 GB — transcodes will be slow), US-only, heavy GCP setup.
- Sources: https://exodus.elim.io/blog/google-cloud-free-tier-for-a-small-app · https://theproofdesk.com/google-cloud-review · https://freetier.co/articles/cloud-provider-free-tiers-2026

### 5. AWS EC2 t2/t3.micro — good for exactly 12 months
- 750 hrs/month t2.micro or t3.micro (1 vCPU, 1 GB), 30 GB EBS, 1 GB egress — **12 months only**, then ~$8–10/month. Real server: Docker, ffmpeg, SQLite fine. Card required. (Lambda always-free 1M requests can't long-poll — 15-min max runtime — needs webhook rewrite.)
- Verdict: perfect for a year, then it bills. Use only if you accept migrating in 12 months.
- Sources: https://builder.aws.com/content/2r3mE7QWKmNmDYhp202NdXdmOMw/how-to-use-amazon-web-services-for-free · https://www.theawstrainer.com/blog/aws-free-tier-guide-2025

### 6. Azure B1s — also 12 months
- 750 hrs/month each of B1s, B2pts v2 (ARM), B2ats v2 (1 vCPU, 1 GB, burstable) for **12 months**, plus $200 credit for first 30 days. Must move to pay-as-you-go within 30 days. Card required. Azure for Students: $100/12 months, **no card**, needs a school email.
- Verdict: same story as AWS — a 12-month runway, not a home.
- Sources: https://learn.microsoft.com/en-us/AZURE/cost-management-billing/manage/create-free-services · https://askgpu.com/free-vps-tiers-oracle-aws-google-azure/

## PaaS options that don't make the cut
### 7. Koyeb — better sleep window, no disk, card hold
- One free instance: 512 MB, 0.1 vCPU, 2 GB SSD, Frankfurt or Washington. **Scales to zero after 1 hour idle** (4× Render's window), wakes in 1–5 s. **No volumes** — SQLite dies on restart. Card required since Feb 2026 with a **$29 pre-authorisation hold**. Acquired by Mistral AI Feb 2026. Free Postgres: 1 GB, 5 compute-hours/month.
- Verdict: better than Render on sleep, worse on disk, $29 hold stings. Not better than Northflank.
- Sources: https://snapdeploy.dev/blog/koyeb-vs-free-container-tier · https://freetier.wiki/services/koyeb/ · https://xcloud.host/best-free-docker-hosting/

### 8. Railway — $1/month can't run a bot
- Permanent Free plan: **$1 of usage credit/month**, 0.5 GB RAM, 1 vCPU, sleeps after 5–10 min idle. $1 buys ~5% of a month of always-on compute — bot dies in ~2 days. Trial is one-time $5 credit for 30 days. Hobby is $5/month. (Also: Oct 2026 env-var breach, ~100k workspaces affected.)
- Verdict: trial is fine for a month of testing; the free plan cannot keep a bot up.
- Sources: https://docs.railway.com/pricing/free-plan · https://outplane.com/blog/railway-pricing

### 9. Fly.io — no free tier (with one confusing exception)
- No free tier or monthly allowance for new orgs since Oct 2024; trial $1 credit / 7 days (or 2 VM-hours). Cheapest machine ~$2.19/month, card required. One source (flaviocopes, updated 23 Nov 2026) reports a **$5/month Free plan returned 23 Nov 2026** for personal orgs with a card — but crossing $5 flips the org to pay-as-you-go and bills the **whole month from $0**, a nasty cliff. Conflicting reports; do not plan on it.
- Verdict: not free. The $5 plan, if real, could run the bot but needs a card and has a billing cliff.
- Sources: https://theproofdesk.com/fly-io-review · https://flaviocopes.com/hosting-free-tiers/ · https://whichdevtool.com/tools/fly-io/

### 10. Hugging Face Spaces — paywalled in 2026
- 2026 change: creating Gradio or Docker Spaces now requires PRO ($9/month). Free accounts can only host up to 2 Gradio Spaces on ZeroGPU (5 min GPU/day) plus static pages. CPU Basic hardware exists but creation is paywalled; sleeps after ~48h idle; disk ephemeral.
- Verdict: dead for this bot — Docker route costs $9/month.
- Sources: https://toolfreebie.com/hugging-face-spaces-free-gpu/ · https://aifree.dev/learn/free-hosting-ai-apps

### 11. Replit — free plan closed to new sign-ups (Nov 2026)
- Starter closed Nov 2026; the one free published app **goes down after 30 days**; Always On withdrawn early 2024; 0 background tasks on free. Core is $20/month.
- Verdict: dead.
- Sources: https://www.engineerfoodie.in/blog/is-replit-free/ · https://tailkits.com/tools/replit/

### 12. Cloudflare Workers — wrong shape entirely
- 100k requests/day, 10 ms CPU per invocation, Python GA. But **no persistent process, no long-polling, no subprocesses, no ffmpeg, no local disk**. Bot would need a webhook rewrite + D1 migration (3–5 days) and would **lose YouTube downloads and voice notes** outright.
- Verdict: wrong architecture for this bot. (Useful only as a backup store — e.g. R2 for SQLite backups.)
- Sources: prior research in this project (docs/research-deploy-render-vs-cloudflare.md); https://developers.cloudflare.com/workers/platform/limits/

### 13. Back4app Containers / Miget — thin, small, lightly verified
- Back4app: 1 free container, reportedly no card. Miget: standing free tier 256 MiB / 0.1 vCPU / 1 GiB, sleeps after 15 min, native docker-compose support. 256 MB is tight for ffmpeg + 50 MB downloads.
- Verdict: possible backups to Render, not better than Northflank; Miget's RAM too small for media work.
- Sources: https://flywp.com/blog/9769/best-free-docker-hosting-platforms/ · https://miget.com/blog/best-free-docker-hosting

## Dead platforms (stop searching for these)
Heroku (free dynos removed Nov 2022). Glitch (hosting shut down 8 Jul 2025). Cyclic (shut down 31 May 2024). Deta Space (sunset 17 Oct 2024, data deleted). 000webhost (shut down Oct 2024). Vultr / Hostinger — no free tier at all (only time-limited promo credits).
- Sources: https://snapdeploy.dev/state-of-free-hosting · https://klymentiev.com/blog/free-hosting-list

## Do-not-do-this options
### 14. GitHub Actions as a host — works technically, violates ToS
- Free 2,000 min/month (public repos unlimited), 6-hour max job. People run bots as self-triggering cron workflows (~30-min chunks, state saved as artifacts). But GitHub's AUP **prohibits serverless hosting / running persistent applications** and bypassing limits; accounts get banned for it (documented cases). Polling would also have gaps between runs.
- Verdict: do not do it — ban risk to the GitHub account, bot deaf between runs.
- Sources: https://devactivity.com/posts/apps-tools/beyond-the-loophole-why-misusing-free-cloud-services-impacts-engineering-performance/

### 15. Raspberry Pi / old phone at home — $0 if the hardware already exists
- A Pi 4/5 (or old Android via Termux) runs the bot as-is: real disk, ffmpeg, Docker, polling needs no port forwarding (outbound-only). Pi 5 draws ~2.7 W idle, ~$4–5/year in electricity.
- Downsides: must already own the hardware (a Pi 5 kit is ~$50–80 to buy — Oracle beats that); home power/internet outages kill the bot; SD cards wear out under 24/7 writes (use an SSD); Android Termux is unreliable (OS battery optimisation kills background processes, needs wakelocks); you expose your home network if you ever open SSH.
- Verdict: best $0 option **if a Pi or spare device is already sitting in a drawer**; not worth buying hardware for when Oracle is free.
- Sources: https://dev.to/dmitry-koleev/host-telegram-bot-on-raspberry-pi-5-16ld · https://fast.io/resources/openclaw-raspberry-pi-telegram-bot-agent/ · https://github.com/famclaw/famclaw

## Recommendation
**Deploy today on Northflank Sandbox.** Only free option found that is simultaneously always-on (no sleep), persistent-disk (SQLite survives), Docker-native (ffmpeg + yt-dlp unchanged, zero rewrite), and free forever with no expiry — one 0.5 vCPU/1 GB service at $12/month fits inside the $20 credit. Only open question is whether signup demands a payment method (pricing page says no card; billing docs say yes) — a 5-minute signup test settles it. If it demands a card and that's a blocker, fall back to Render free web service for testing.
**Move to Oracle Always Free VPS as the permanent home.** Strongest $0 platform: 2 OCPU/12 GB, 200 GB disk, 10 TB egress, never sleeps, bot runs exactly as-is, SQLite safe. Budget a day for Linux setup, a card for verification, and a few tries at provisioning (capacity lottery); pick Frankfurt as home region (closest to Egypt). Watch the idle-reclaim rule.
**Sequence:** Northflank today (hours, not days) → Oracle when you have a free day (best forever home) → Render only as a quick test bed. Skip Cloudflare Workers, HF Spaces, Replit, Railway, Fly.io, Koyeb, GitHub Actions, and every dead platform above.
**One architectural note that applies everywhere:** because the bot long-polls (outbound-only), it never needs a public IP or an open port — that is what makes GCP's e2-micro genuinely $0 without an external IP, and what makes home hosting need no port forwarding.
