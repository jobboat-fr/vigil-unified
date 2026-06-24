import type { ReactNode } from "react";
import { useAuth } from "@/context/AuthContext";
import PublicSite from "@/components/PublicSite";
import { BrandLoader } from "@/components/BrandLoader";

/**
 * Gates the whole app behind the VIGIL Supabase session. When there's no
 * session, the logged-out experience is the public marketing site + docs +
 * auth (PublicSite). When Supabase isn't configured (no env — e.g. a
 * pure-Hermes/local dashboard build) the gate is a no-op so the dashboard
 * still loads.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { configured, loading, session } = useAuth();
  if (!configured) return <>{children}</>;
  if (loading) return <BrandLoader />;
  if (!session) return <PublicSite />;
  return <>{children}</>;
}
