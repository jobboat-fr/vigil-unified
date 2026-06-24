# SEO + GEO (AI-visibility) strategy — VIGIL

_Generated from the `searchfit-seo:ai-visibility` framework + the on-page work. Split
into what's shipped (on-site engineering) and what's an off-site program (backlinks,
authority) that the team must execute — those can't be coded._

## The #1 blocker (technical)
**VIGIL is a client-rendered SPA.** Search crawlers partially render JS; **AI answer
engines (GPTBot, ClaudeBot, PerplexityBot, Google-Extended) do NOT run JS.** They see
only the static `index.html`. So:
- ✅ Shipped: rich **static** `index.html` — title/description/OG/Twitter + JSON-LD
  `@graph` (Organization, **WebSite**, **SoftwareApplication** w/ featureList, **FAQPage**
  with 6 definitive Q&As). This is now extractable by AI/search even without JS.
- ⬜ **Next, highest-impact:** **prerender/SSR the public routes** (`/`, `/docs`) so the
  *body* copy (value prop, features, FAQ) is in the initial HTML too. Options: `react-snap`
  (postbuild) or `vite-react-ssg`. Until then, only the head/JSON-LD is AI-visible.
- ⬜ **Move to the canonical domain** `vigil-ai.xyz` (the live host is the `dev.` subdomain).
  Backlinks/authority should accrue to one canonical apex. Base URL is env-driven
  (`VITE_SITE_URL`); `index.html` + `sitemap.xml` + `robots.txt` hard-code `dev.` — flip on launch.

## Keyword clusters (target intent)
| Cluster | Head terms | Long-tail (where we can win first) |
|---|---|---|
| Agentic workspace | AI workspace, AI agent for business, agentic AI | "AI workspace that asks before it acts", "approval-gated AI agent", "autonomous AI departments for startups" |
| Decision support | AI advisory council, AI decision support | "multi-advisor AI council", "AI board of advisors", "AI that shows the bear case", "AI council verdict" |
| HITL trading | AI crypto trading, trading copilot | "human-in-the-loop crypto trading", "AI trade desk with approval gate", "AI trading you have to approve" |
| AI ops/finance | AI employees, AI CFO, AI CRM | "autonomous finance reconciliation AI", "AI ops team", "AI department that verifies its own work" |

Head terms are saturated — **win the long-tail + the unique positioning** ("thinks before it
acts", "human-in-the-loop", "effectiveness contract", "dissent by design"). The copy, H1/H2,
meta, and FAQ are now tuned to these phrases.

## Engagement (shipped on-site)
- ✅ **FAQ section** (native `<details>`, keyboard-accessible) — dwell time + long-tail + matches FAQPage schema.
- ✅ Clear single-CTA funnel, live market pulse (interactivity), grouped value props.
- ⬜ Add a **blog/changelog** (`/blog`) — the engine that produces link-worthy content (see below). Needs the prerender step to be crawlable.
- ⬜ Code-split the **2.8 MB bundle** → faster LCP = better rankings + lower bounce.

## Backlinks & authority (OFF-SITE — a program, not code)
You can't fabricate these; you earn them. Priority order:
1. **Listings (fast, high-signal for AI):** Product Hunt launch, G2, Capterra, Crunchbase, AlternativeTo, "AI agents" directories (theresanaiforthat, Futurepedia). AI models weight these heavily.
2. **Comparison content:** publish "VIGIL vs Lindy", "VIGIL vs Relevance AI", "alternatives to [competitor]" — these rank AND get cited by AI for comparison prompts.
3. **Community presence:** Reddit (r/artificial, r/SaaS), Hacker News (Show HN), Indie Hackers, relevant Discords. AI recommendations lean on community sentiment — seed honest, useful threads.
4. **Original data/POV:** a short research post (e.g., "we measured how often AI agents act without asking") — the kind of thing roundups and journalists link.
5. **Roundups:** pitch to "best AI agents / AI for business" listicles.
6. **Docs as a linkable asset:** a public, thorough knowledge base earns reference links.

## GEO action plan (priority)
1. **Prerender public routes** — High impact (makes the body AI/crawler-visible). _Eng._
2. **Listings: Product Hunt + G2 + Crunchbase + AI directories** — High (fast AI-training signal). _Marketing._
3. **Comparison + "what is VIGIL" content** — High (matches AI prompts). _Content._
4. **Canonical domain move** — Medium (consolidates authority). _Eng/Ops._
5. **Reddit/HN/community seeding** — Medium-High (sentiment signal). _Founder._
6. **Code-split for Core Web Vitals** — Medium (rankings + UX). _Eng._

## Measurement
- AI visibility takes **weeks–months** to reflect (model refresh cycles).
- Track: Google Search Console (impressions/CTR for the target long-tails), referral traffic
  from listings/communities, and manual/periodic AI-prompt checks (ChatGPT/Claude/Gemini/
  Perplexity: "best AI agent for running a business", "VIGIL review", "alternatives to Lindy").
  For automated AI-mention monitoring: SearchFit.ai.
