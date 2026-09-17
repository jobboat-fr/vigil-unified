import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import App from "./App";
import { SystemActionsProvider } from "./contexts/SystemActions";
import { I18nProvider } from "./i18n";
import { exposePluginSDK } from "./plugins";
import { ThemeProvider } from "./themes";
import { HERMES_BASE_PATH } from "./lib/api";
import { AuthProvider } from "./context/AuthContext";
import { AuthGate } from "./components/AuthGate";
import { initNativeShell } from "./lib/native";
import GuestMeetingPage from "./pages/GuestMeetingPage";
import PartageArtefactPage from "./pages/PartageArtefactPage";
import ActiverComptePage from "./pages/ActiverComptePage";
import DesinscriptionPage from "./pages/DesinscriptionPage";
import NouveauMotDePassePage from "./pages/NouveauMotDePassePage";

// Expose the plugin SDK before rendering so plugins loaded via <script>
// can access React, components, etc. immediately.
exposePluginSDK();

// Capacitor mobile shell (Android back button, status bar) — no-op in browsers.
void initNativeShell();

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
            <Routes>
              {/* Invitation à une réunion : la seule page ouverte sans compte. Le jeton de
                  partage est la preuve ; il expire et meurt avec la réunion (passerelle). */}
              <Route path="/join/:shareToken" element={<GuestMeetingPage />} />
              {/* Un document du studio partagé par lien : lecture seule, échéance, révocable. */}
              <Route path="/partage/:token" element={<PartageArtefactPage />} />
              {/* Pages à jeton, ouvertes depuis un e-mail : activation, désinscription, mot de passe. */}
              <Route path="/activer" element={<ActiverComptePage />} />
              <Route path="/desinscription" element={<DesinscriptionPage />} />
              <Route path="/nouveau-mot-de-passe" element={<NouveauMotDePassePage />} />
              <Route
                path="*"
                element={
                  <AuthGate>
                    <App />
                  </AuthGate>
                }
              />
            </Routes>
          </SystemActionsProvider>
        </AuthProvider>
      </ThemeProvider>
    </I18nProvider>
  </BrowserRouter>,
);

// PWA : installable sur mobile, et une coquille servie quand le réseau tombe en salle.
// Enregistré après le premier rendu pour ne pas disputer la bande passante au bundle, et
// silencieux en développement, où un worker persistant sert un build périmé.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js").catch(() => {
      /* Un enregistrement refusé (mode privé, contexte non sécurisé) n'empêche rien. */
    });
  });

  // Quand un nouveau worker prend la main, la page tourne encore sur l'ancien bundle : ses
  // modules sont déjà chargés. On recharge une fois — le garde-fou évite la boucle si le
  // navigateur émet l'évènement plusieurs fois.
  let rechargé = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (rechargé) return;
    rechargé = true;
    window.location.reload();
  });
}
