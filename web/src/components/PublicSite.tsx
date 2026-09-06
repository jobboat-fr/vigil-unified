import { useEffect } from "react";
import { Routes, Route, Navigate, Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import LandingPage from "@/pages/LandingPage";
import DocsPage from "@/pages/DocsPage.public";
import AuthPage from "@/pages/AuthPage";
import GuestMeetingPage from "@/pages/GuestMeetingPage";
import { TermsPage, PrivacyPage, DisclaimerPage, CookiesPage, MentionsPage } from "@/pages/legal/LegalPages";
import { BrandLoader } from "@/components/BrandLoader";
import { BRAND } from "@/lib/brand";

/**
 * The unauthenticated experience: a public marketing site + docs, with the auth
 * flow reachable at /login and /signup. Rendered by AuthGate whenever there is
 * no Supabase session. Once a session exists, AuthGate swaps this for the app.
 */
export default function PublicSite() {
  // Let the document scroll on the public surface (long landing/docs pages). The
  // class is removed on unmount so the authed dashboard keeps its fixed shell.
  useEffect(() => {
    const el = document.documentElement;
    el.classList.add("vigil-public-scroll");
    return () => el.classList.remove("vigil-public-scroll");
  }, []);

  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/docs" element={<DocsPage />} />
      {/* Compliance pages — public + prerendered; Play Store requires a live privacy URL. */}
      <Route path="/legal/terms" element={<TermsPage />} />
      <Route path="/legal/privacy" element={<PrivacyPage />} />
      <Route path="/legal/disclaimer" element={<DisclaimerPage />} />
      <Route path="/legal/cookies" element={<CookiesPage />} />
      <Route path="/legal/mentions" element={<MentionsPage />} />
      {/* External guests join a live meeting via a share link — no account. */}
      <Route path="/join/:shareToken" element={<GuestMeetingPage />} />
      <Route path="/login" element={<AuthPage initialMode="signin" />} />
      {/* Pas d’inscription en libre-service : les accès sont délivrés par l’organisme. */}
      <Route path="/signup" element={<Navigate to="/login" replace />} />
      {/* OAuth / magic-link callback lands here; AuthProvider exchanges the code. */}
      <Route path="/auth" element={<AuthCallback />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AuthCallback() {
  const { authError, loading } = useAuth();
  // No pending code exchange and the gate has settled with no session → don't
  // sit on the spinner; send the user to the sign-in form.
  if (!authError && !loading && !window.location.search.includes("code=")) {
    return <Navigate to="/login" replace />;
  }
  if (authError) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center" style={{ background: BRAND.bg, color: BRAND.ink }}>
        <p className="text-sm" style={{ color: BRAND.rose }}>{authError}</p>
        <Link to="/login" className="text-sm underline">Back to sign in</Link>
      </div>
    );
  }
  return <BrandLoader label="Signing you in" />;
}
