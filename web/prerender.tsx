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

const ROUTES: Record<string, ComponentType> = {
  "/": LandingPage,
  "/docs": DocsPage,
};

export const routes = Object.keys(ROUTES);

export function render(url: string): string {
  const Page = ROUTES[url];
  if (!Page) return "";
  return renderToString(
    <MemoryRouter initialEntries={[url]}>
      <Page />
    </MemoryRouter>,
  );
}
