# VIGIL — App Store Listing & ASO (Android first)

_Prepared 2026-07-08. Package: `xyz.vigilai.app` (Capacitor shell → https://vigil-ai.xyz)._

## Google Play listing

**App name (30 chars max):**
`VIGIL — AI Workspace`

**Short description (80 chars max):**
`The AI workspace that thinks before it acts. Council, departments, trade desk.`

**Full description (Play allows 4000 chars — keyword-relevant, no keyword stuffing):**

> **VIGIL is the AI workspace that thinks before it acts.**
>
> Run your business with AI that deliberates, verifies, and waits for your approval — never a black box.
>
> **🏛 AI Council & Meeting Room** — CFO, CTO, Legal and Product advisor lenses debate your decision, score it, and a chairman synthesizes a defensible verdict. Bring the council into a live meeting or send it to Google Meet.
>
> **🏢 Autonomous AI departments** — support triage, finance reconciliation, revenue follow-ups, lead scouting, legal review. Every task passes a deterministic effectiveness check before it counts as done: verified output, not vibes.
>
> **📈 Human-in-the-loop trade desk** — data-grounded crypto signals and forecasts propose trades; YOU approve every order through a single-use verification gate. Connect your own exchange — VIGIL never holds your funds.
>
> **📚 Your whole back office** — finance, CRM, mail, document vault and studio, protected by row-level tenant isolation and a tamper-evident audit log.
>
> **Why VIGIL over a chatbot?** Chatbots answer. VIGIL plans, debates, verifies its work, and asks before anything with real consequence happens — a trade, an email, a payment.
>
> Free plan available. Starter €19/mo · Pro €49/mo · Team €149/mo.
>
> VIGIL is software, not an adviser. Crypto trading involves substantial risk of loss. Not investment advice — see vigil-ai.xyz/legal/disclaimer.

**Category:** Business (secondary candidate: Finance — avoid: Finance category triggers extra Play policy review for crypto features; Business is accurate and lower-friction)

**Tags/keywords to target (ASO):** ai workspace, ai agent, business ai, ai council, crypto portfolio, human in the loop, ai crm, ai finance assistant

**Required URLs (all live):**
- Privacy policy: `https://vigil-ai.xyz/legal/privacy` ← Play REQUIRES this field
- Terms: `https://vigil-ai.xyz/legal/terms`
- Support email: `legal@vigil-ai.xyz`
- Website: `https://vigil-ai.xyz`

## Play Data-safety form (answers)

| Question | Answer |
|---|---|
| Collects personal data? | Yes — email, name (account); user content (documents, messages) |
| Shares data with third parties? | Processors only (Stripe, Supabase, model providers) — not "sharing" in Play's sense (no ads/marketing) |
| Data encrypted in transit? | Yes (TLS everywhere) |
| Deletion mechanism? | Yes — in-app GDPR deletion + export |
| Ads / ad SDKs? | None |
| Location, contacts, device IDs? | Not collected |

## Content-rating questionnaire pointers
- No user-generated public content, no gambling (trading ≠ gambling in IARC, but declare "simulated gambling: no; real-money: users can spend money via subscription")
- Declare **in-app purchases: subscriptions €19–149/mo** (billed via Stripe on the web — note: if Play requires Google Play Billing for digital subscriptions sold IN-APP, keep purchase flow web-only and the app free with login; the current shell does exactly this, like Netflix/Spotify "reader" pattern)

## Crypto policy note (IMPORTANT for review)
Google Play restricts *custodial* crypto wallets/exchanges. VIGIL is **non-custodial software**: users connect their own exchange API keys, every order is human-approved, VIGIL never holds funds. State this in the review notes verbatim. The Risk disclaimer page backs it up.

## Technical ASO already shipped
- `/.well-known/assetlinks.json` with the app's SHA256 (debug cert for now — **replace with the release-key fingerprint before Play submission**) → enables Android App Links (https://vigil-ai.xyz opens in the app)
- JSON-LD `MobileApplication` + priced `Offer`s on the site (Google surfaces app+price in search)
- `llms.txt` for AI-assistant answer engines (AEO)
- Prerendered marketing + legal pages (store reviewers see full content without JS)

## Before first Play submission (checklist)
1. Generate a **release keystore**, add its SHA256 to assetlinks.json (keep debug one too)
2. `versionCode`/`versionName` in `web/android/app/build.gradle`
3. App icon + splash (currently Capacitor defaults — replace with the VIGIL mark: `npx @capacitor/assets generate`)
4. 512×512 icon, 1024×500 feature graphic, ≥4 phone screenshots (shoot /meeting-room, /trade-desk, /ops-team, /billing)
5. `./gradlew bundleRelease` → upload the `.aab`, not the APK

## iOS (later — needs a Mac)
`npx cap add ios`; App Store equivalents of everything above; Apple is stricter on the "web wrapper" rule (4.2 minimum functionality) — plan to add native touches (push notifications via @capacitor/push-notifications, biometric unlock) before submission.
