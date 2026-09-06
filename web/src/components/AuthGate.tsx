import type { ReactNode } from "react";
import { useAuth } from "@/context/AuthContext";
import AuthPage from "@/pages/AuthPage";
import { BrandLoader } from "@/components/BrandLoader";

/**
 * Nothing renders before a session exists.
 *
 * Two changes from the version this replaces, both of which were letting people in.
 *
 * **A signed-out visitor gets the sign-in screen, not a marketing site.** `app.vtlvs.com` is
 * the application; the marketing lives on the apex. Showing VIGIL's trading landing page
 * here advertised the wrong product to an organisme's staff.
 *
 * **An unconfigured build no longer opens the doors.** The old gate returned `children` when
 * Supabase env was absent, so a deployment that simply forgot `VITE_SUPABASE_URL` served the
 * entire dashboard to anyone with the URL — which is exactly what happened here. A missing
 * configuration is now a refusal, because the alternative failure mode is silent and total.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { configured, loading, session } = useAuth();

  if (!configured) {
    return (
      <div className="grid min-h-dvh place-items-center p-6">
        <div className="max-w-md rounded-xl border border-current/15 p-6 text-center">
          <h1 className="text-lg font-semibold">Connexion indisponible</h1>
          <p className="mt-2 text-sm opacity-70">
            Ce déploiement n&apos;a pas d&apos;authentification configurée
            (<code className="text-xs">VITE_SUPABASE_URL</code>). L&apos;accès est refusé
            plutôt qu&apos;ouvert : une configuration manquante ne doit pas se traduire par un
            tableau de bord public.
          </p>
        </div>
      </div>
    );
  }

  if (loading) return <BrandLoader />;
  if (!session) return <AuthPage />;
  return <>{children}</>;
}
