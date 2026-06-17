import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import App from "./App";
import { SystemActionsProvider } from "./contexts/SystemActions";
import { I18nProvider } from "./i18n";
import { exposePluginSDK } from "./plugins";
import { ThemeProvider } from "./themes";
import { HERMES_BASE_PATH } from "./lib/api";
import { AuthProvider } from "./context/AuthContext";
import { AuthGate } from "./components/AuthGate";

// Expose the plugin SDK before rendering so plugins loaded via <script>
// can access React, components, etc. immediately.
exposePluginSDK();

// On Vercel the operator API is reached through the Supabase-gated proxy
// (web/api/[...path].js), not the dashboard's own loopback HTML — so there is
// no server-injected session token to refresh by reloading. Declaring the gate
// "engaged" makes api.ts treat a 401 as a session-expiry (full-page navigate to
// the proxy's login_url) instead of triggering the loopback token-reload loop.
// Respect an explicit value if the dashboard itself ever serves this build.
if (window.__HERMES_AUTH_REQUIRED__ === undefined) {
  window.__HERMES_AUTH_REQUIRED__ = true;
}

createRoot(document.getElementById("root")!).render(
  <BrowserRouter basename={HERMES_BASE_PATH || undefined}>
    <I18nProvider>
      <ThemeProvider>
        <AuthProvider>
          <SystemActionsProvider>
            <AuthGate>
              <App />
            </AuthGate>
          </SystemActionsProvider>
        </AuthProvider>
      </ThemeProvider>
    </I18nProvider>
  </BrowserRouter>,
);
