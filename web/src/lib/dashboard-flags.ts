declare global {
  interface Window {
    /**
     * Injected by the server as `true`. The embedded TUI Chat surface
     * (`/chat`, `/api/ws`, `/api/pty`) is always enabled, so this is
     * effectively a constant; kept on `window` for any consumer that reads
     * it directly and for parity with the server's bootstrap script.
     */
    __HERMES_DASHBOARD_EMBEDDED_CHAT__?: boolean;
  }
}

/**
 * Whether the dashboard's embedded TUI Chat surface is available.
 *
 * The embedded chat (`/chat` tab, `/api/ws` + `/api/pty` WebSockets) is now
 * an unconditional part of the dashboard — the desktop app and the in-browser
 * Chat tab both depend on it — so this always returns `true`. The function is
 * retained as a stable seam so call sites don't need to change if the surface
 * ever becomes conditional again.
 */
export function isDashboardEmbeddedChatEnabled(): boolean {
  // The embedded TUI chat needs a server that can hold the /api/pty WebSocket.
  // On the Vercel product that's impossible (serverless functions can't proxy
  // WebSockets), so the real Hermes dashboard injects this flag = true ONLY when
  // it serves the SPA itself. On the product build it's undefined → we fall back
  // to the gateway assistant (HTTP SSE) at /chat instead of a dead terminal.
  return typeof window !== "undefined" && window.__HERMES_DASHBOARD_EMBEDDED_CHAT__ === true;
}
