import type { CapacitorConfig } from "@capacitor/cli";

/**
 * VIGIL mobile shell — Capacitor wrapping THIS web codebase.
 *
 * v1 runs in REMOTE mode: the native shell loads https://vigil-ai.xyz directly,
 * so the app is always the latest deploy and — critically — the Vercel-hosted
 * serverless proxy routes keep working (`/api/ops`, `/api/plugins/*` are
 * relative fetches that only exist on the Vercel origin; a bundled webview
 * origin like capacitor://localhost would 404 them). Supabase auth, CSP and
 * CORS also behave exactly like the browser because the origin IS the site.
 *
 * To ship a store-friendly BUNDLED build later:
 *   1. delete `server.url` below (keep androidScheme),
 *   2. make the ops-proxy fetches absolute (prefix https://vigil-ai.xyz) when
 *      `Capacitor.isNativePlatform()`, and add CORS for the app origin on
 *      web/api/ops.js,
 *   3. add a deep-link scheme for the Supabase OAuth redirect,
 *   4. `npm run build && npx cap sync`.
 *
 * Override the URL per-build with CAP_SERVER_URL (e.g. point a debug build at
 * a preview deploy).
 */
const config: CapacitorConfig = {
  appId: "xyz.vigilai.app",
  appName: "VIGIL",
  webDir: "dist",
  server: {
    url: process.env.CAP_SERVER_URL || "https://vigil-ai.xyz",
    androidScheme: "https",
  },
  android: {
    allowMixedContent: false,
  },
};

export default config;
