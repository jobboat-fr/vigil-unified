// Postbuild prerender for the public routes (/, /docs, /legal/*). Uses Vite's
// own SSR module loader — no headless browser, no extra runtime deps,
// React-19-safe. Injects the rendered page markup into the built
// dist/index.html's #root (the client's createRoot replaces it for JS users;
// AI/search crawlers and app-store reviewers read it statically). Non-root
// routes are emitted as dist/<route>/index.html with their own <head>
// (title/description/canonical/OG from prerender.tsx's routeMeta — one source
// of truth, so a domain change can't silently break the rewrite again).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const SITE_URL = (process.env.VITE_SITE_URL || "https://vigil-ai.xyz").replace(/\/$/, "");

const vite = await createServer({
  root,
  server: { middlewareMode: true },
  appType: "custom",
  logLevel: "warn",
});

try {
  const { render, routes, routeMeta } = await vite.ssrLoadModule("/prerender.tsx");
  const template = fs.readFileSync(path.join(dist, "index.html"), "utf-8");

  for (const url of routes) {
    const body = render(url);
    if (!body) {
      console.warn("prerender: empty render for", url, "— skipped");
      continue;
    }
    let html = template.replace('<div id="root"></div>', `<div id="root">${body}</div>`);
    let outPath;
    if (url === "/") {
      outPath = path.join(dist, "index.html");
    } else {
      const meta = routeMeta?.[url];
      if (meta) {
        const esc = (s) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
        const pageUrl = `${SITE_URL}${url}`;
        html = html
          .replace(/<title>[^<]*<\/title>/, `<title>${esc(meta.title)}</title>`)
          .replace(/(<meta name="description" content=")[^"]*(")/, `$1${esc(meta.description)}$2`)
          .replace(/(<link rel="canonical" href=")[^"]*(")/, `$1${pageUrl}$2`)
          .replace(/(<meta property="og:url" content=")[^"]*(")/, `$1${pageUrl}$2`)
          .replace(/(<meta property="og:title" content=")[^"]*(")/, `$1${esc(meta.title)}$2`)
          .replace(/(<meta property="og:description" content=")[^"]*(")/, `$1${esc(meta.description)}$2`)
          .replace(/(<meta name="twitter:title" content=")[^"]*(")/, `$1${esc(meta.title)}$2`)
          .replace(/(<meta name="twitter:description" content=")[^"]*(")/, `$1${esc(meta.description)}$2`);
      }
      const dir = path.join(dist, url.replace(/^\//, ""));
      fs.mkdirSync(dir, { recursive: true });
      outPath = path.join(dir, "index.html");
    }
    fs.writeFileSync(outPath, html);
    console.log(`prerendered ${url} -> ${path.relative(root, outPath)} (${body.length} chars)`);
  }
} finally {
  await vite.close();
}
