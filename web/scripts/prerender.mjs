// Postbuild prerender for the public routes (/ and /docs). Uses Vite's own SSR
// module loader — no headless browser, no extra runtime deps, React-19-safe.
// Injects the rendered page markup into the built dist/index.html's #root (the
// client's createRoot replaces it for JS users; AI/search crawlers read it
// statically). /docs is emitted as dist/docs/index.html with its own <head>.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(root, "dist");
const DOCS_TITLE = "Docs — VIGIL";

const vite = await createServer({
  root,
  server: { middlewareMode: true },
  appType: "custom",
  logLevel: "warn",
});

try {
  const { render, routes } = await vite.ssrLoadModule("/prerender.tsx");
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
      // Per-route <head> for /docs (mirrors what useSeo sets at runtime).
      html = html
        .replace(/<title>[^<]*<\/title>/, `<title>${DOCS_TITLE}</title>`)
        .replace(/(<link rel="canonical" href="https:\/\/dev\.vigil-ai\.xyz)\/(")/, "$1/docs$2")
        .replace(/(<meta property="og:url" content="https:\/\/dev\.vigil-ai\.xyz)\/(")/, "$1/docs$2")
        .replace(/(<meta property="og:title" content=")[^"]*(")/, `$1${DOCS_TITLE}$2`)
        .replace(/(<meta name="twitter:title" content=")[^"]*(")/, `$1${DOCS_TITLE}$2`);
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
