# Research: payment cards for Northflank verification — Egypt options (2026-11-25)

Two independent research tracks. Context: Seif has NO international Visa card. Northflank requires a payment method to create resources even on the free Sandbox (Stripe; Visa/Mastercard/Amex; card is only verified, not charged while inside the $20 free resources).

## Fake cards do NOT work
- Stripe places a real authorization ($0 account verification, sometimes ~$1, refunded) against the issuer. A generated number has no account, no balance, no CVV/AVS/3D Secure behind it — the hold fails instantly. It only passes the Luhn format check.
- Merchants can enable Stripe's `block_if_prepaid`, which rejects prepaid-class BINs before the charge reaches a bank.
- Submitting fabricated payment details is the exact abuse the check is designed to catch; repeated fake attempts risk an account ban and Stripe card-testing flags.
- Sources: Northflank pricing FAQ https://northflank.com/pricing ; "Add a card" doc https://northflank.com/docs/v1/application/billing/add-a-card.md ; https://evertry.co/blog/best-virtual-card-for-developers-in-africa/

## Northflank payment facts
- Payments via Stripe; accepted Visa, Mastercard, American Express. No PayPal. Invoice billing only for larger/enterprise accounts.
- No published Egypt restriction; no official statement on prepaid/virtual cards. Positive signal: virtual-card provider Card-Y lists Northflank among accepted platforms (https://docs.card-y.com/en/articles/10121078-virtual-card-accepted-platforms).
- No published hold amount; Stripe verification "may use a $0, $1, or similar authorization."
- Failed verification: no published policy; account can exist but no resources can be created; multiple cards supported, can retry with another card. Stripe blocks after 3–5 failed attempts with the same card for 1–24h.
- New accounts start with a $50 billing threshold — auto-invoice when usage hits it; services suspended if threshold invoices cannot be paid.

## Ranked legitimate options for Egypt
1. **EverTry** — best overall. Virtual USD Visa/Mastercard, FinCEN-registered MSB. KYC ~2–3 min (national ID/passport). Cost: ~$3–$4 one-time card creation, $0/mo. Funding: **EGP via InstaPay or bank transfer**, no crypto. Credit-class BIN (not prepaid) — best odds of passing Stripe prepaid blocks; reports of Google Ads/Google Cloud authorizations approved from Egypt (Google Cloud explicitly rejects prepaid). ~$10 total (~550 EGP) covers issuance + hold buffer. Sources: https://evertry.co/blog/how-to-create-a-virtual-card-in-africa-with-evertry/ , https://grey.co/blog/best-virtual-mastercards-for-online-payments-in-egypt
2. **RedotPay** — best tested Stripe record (~95% Stripe success in a 3-month Cairo test, Oct 2026). $10 one-time virtual Visa ($8 with promo PAY8U), $0/mo. Egypt not on its restriction lists; KYC with national ID/passport + selfie. BUT crypto-funded only (USDT/USDC via Binance P2P + InstaPay/Vodafone Cash) — crypto's legal status in Egypt is restricted/uncertain. Sources: https://www.remogrid.com/blog/fintech/redotpay-virtual-crypto-card-in-egypt-full-guide , https://kkinvesting.io/en/posts/redotpay-card-tutorial-egypt/
3. **Pyypl** — officially supports Egypt (on its supported-countries list). No issuance fee, ~$10 min top-up, fund via local wallets / Visa debit / stablecoins. ~80% Stripe success; prepaid-class BIN, so a merchant with block_if_prepaid on would decline. Sources: https://www.pyypl.com/support/is-pyypl-available-in-my-country , https://www.remogrid.com/blog/ai-tools/how-to-pay-for-midjourney-in-egypt-virtual-card-guide
4. **QNB Alahli / CIB USD debit card** — real debit BIN, near-certain to pass. Requires opening a USD account at a branch: $100–200 minimum deposit, proof of income / stricter KYC. Only worth it if he already wants a USD account.
5. **Telda / Klivvr** — free, but almost certainly WILL NOT work: EGP prepaid Mastercards; Banque du Caire states "International transactions are disabled as per Central Bank of Egypt instructions till further notice." A USD verification hold is an international transaction. Source: https://www.bdc.com.eg/bdcwebsite/personal/cards/prepaid-cards.html

## What does NOT work
- Wise card: not available to Egypt residents. Revolut: Egypt not supported. Egyptian debit cards in general: CBE banned debit cards for foreign-currency transactions (Oct 2023). No-KYC "virtual card" sellers (Telegram/WhatsApp sellers, Vizovcc/Halocard): grey-market, scam/freeze risk, expensive — not recommended.

## No-card fallback
- **Render free tier needs NO card at all** (Render's own 2026 article: "No credit card is required" to deploy a free web service). Trade-offs already documented: sleeps after 15 min idle, SQLite wiped on restart — needs a pinger + Turso/R2 backup. Source: https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026

## Recommendation
For Northflank verification only: EverTry is the cheapest and simplest path — fund ~$10 (~550 EGP), create the ~$4 card, keep a few dollars on it for the hold. No option is 100% guaranteed; if EverTry is declined, RedotPay is the next try; if he wants zero card hassle, deploy on Render instead.
