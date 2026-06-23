import { useEffect } from "react";

/**
 * Per-route <head> management without a dependency. Keeps title, description,
 * canonical and OG/Twitter tags accurate as the SPA navigates — so Google's
 * rendered crawl indexes each public route distinctly. The static index.html
 * still carries strong defaults for the homepage + non-JS social crawlers.
 *
 * Base URL is overridable at build time via VITE_SITE_URL.
 */
const SITE_URL = (import.meta.env.VITE_SITE_URL as string | undefined)?.replace(/\/$/, "")
  || "https://dev.vigil-ai.xyz";

function upsertMeta(selector: string, attr: "name" | "property", key: string, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(selector);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

function upsertLink(rel: string, href: string) {
  let el = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", rel);
    document.head.appendChild(el);
  }
  el.setAttribute("href", href);
}

export interface SeoOptions {
  title: string;
  description: string;
  /** Route path, e.g. "/docs". Defaults to the current pathname. */
  path?: string;
}

export function useSeo({ title, description, path }: SeoOptions): void {
  useEffect(() => {
    const url = SITE_URL + (path ?? window.location.pathname);
    document.title = title;
    upsertMeta('meta[name="description"]', "name", "description", description);
    upsertLink("canonical", url);
    upsertMeta('meta[property="og:title"]', "property", "og:title", title);
    upsertMeta('meta[property="og:description"]', "property", "og:description", description);
    upsertMeta('meta[property="og:url"]', "property", "og:url", url);
    upsertMeta('meta[name="twitter:title"]', "name", "twitter:title", title);
    upsertMeta('meta[name="twitter:description"]', "name", "twitter:description", description);
  }, [title, description, path]);
}
