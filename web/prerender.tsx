// Build-time prerender entry — renders ONLY the public leaf pages (/ and /docs)
// to static HTML so AI/search crawlers (which don't run JS) get the real body,
// not an empty SPA shell. Deliberately isolated from the app shell: these pages
// need only a Router (no Auth/Theme/i18n), and their data fetches + window access
// live in effects, so renderToString is side-effect-free here. The client still
// boots the full app via main.tsx (createRoot replaces #root), so there is no
// hydration coupling and the authed dashboard is untouched.
import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import type { ComponentType } from "react";
import LandingPage from "@/pages/LandingPage";
import DocsPage from "@/pages/DocsPage.public";
import { TermsPage, PrivacyPage, DisclaimerPage, CookiesPage, MentionsPage } from "@/pages/legal/LegalPages";

const ROUTES: Record<string, ComponentType> = {
  "/": LandingPage,
  "/docs": DocsPage,
  "/legal/terms": TermsPage,
  "/legal/privacy": PrivacyPage,
  "/legal/disclaimer": DisclaimerPage,
  "/legal/cookies": CookiesPage,
  "/legal/mentions": MentionsPage,
};

export const routes = Object.keys(ROUTES);

/** Per-route <head> metadata for scripts/prerender.mjs (one source of truth). */
export const routeMeta: Record<string, { title: string; description: string }> = {
  "/docs": {
    title: "Docs — VIGIL",
    description: "How VIGIL works: the AI council, verified departments, the human-in-the-loop trade desk, connecting your broker, and the approval gate.",
  },
  "/legal/terms": {
    title: "Terms of Service — VIGIL",
    description: "The terms governing your use of VIGIL: subscriptions, AI outputs, the human-in-the-loop trade desk, acceptable use, and liability.",
  },
  "/legal/privacy": {
    title: "Privacy Policy — VIGIL",
    description: "How VIGIL processes personal data under the GDPR: what we collect, why, where it lives, our processors, retention, and your rights.",
  },
  "/legal/disclaimer": {
    title: "Risk & AI Disclaimer — VIGIL",
    description: "VIGIL is software, not an adviser: no investment, legal, tax, or accounting advice; AI outputs can be wrong; crypto trading risks apply.",
  },
  "/legal/cookies": {
    title: "Cookie Policy — VIGIL",
    description: "VIGIL uses only strictly-necessary storage: authentication session tokens. No advertising trackers, no third-party analytics cookies.",
  },
  "/legal/mentions": {
    title: "Mentions légales — VIGIL",
    description: "Informations légales de l'éditeur du site vigil-ai.xyz : identification, hébergement, contact, propriété intellectuelle.",
  },
};

export function render(url: string): string {
  const Page = ROUTES[url];
  if (!Page) return "";
  return renderToString(
    <MemoryRouter initialEntries={[url]}>
      <Page />
    </MemoryRouter>,
  );
}
