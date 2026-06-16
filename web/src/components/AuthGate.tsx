import type { ReactNode } from "react";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { useAuth } from "@/context/AuthContext";
import AuthPage from "@/pages/AuthPage";

/**
 * Gates the whole app behind the VIGIL Supabase session. When Supabase isn't
 * configured (no env — e.g. a pure-Hermes/local dashboard build) the gate is a
 * no-op so the dashboard still loads.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { configured, loading, session } = useAuth();
  if (!configured) return <>{children}</>;
  if (loading) {
    return (
      <div className="min-h-dvh flex items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (!session) return <AuthPage />;
  return <>{children}</>;
}
