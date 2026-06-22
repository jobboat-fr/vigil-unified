import { Routes, Route, Navigate, Link } from "react-router-dom";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import { useAuth } from "@/context/AuthContext";
import LandingPage from "@/pages/LandingPage";
import DocsPage from "@/pages/DocsPage.public";
import AuthPage from "@/pages/AuthPage";
import GuestMeetingPage from "@/pages/GuestMeetingPage";

/**
 * The unauthenticated experience: a public marketing site + docs, with the auth
 * flow reachable at /login and /signup. Rendered by AuthGate whenever there is
 * no Supabase session. Once a session exists, AuthGate swaps this for the app.
 */
export default function PublicSite() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/docs" element={<DocsPage />} />
      {/* External guests join a live meeting via a share link — no account. */}
      <Route path="/join/:shareToken" element={<GuestMeetingPage />} />
      <Route path="/login" element={<AuthPage initialMode="signin" />} />
      <Route path="/signup" element={<AuthPage initialMode="signup" />} />
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
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center" style={{ background: "#07080d", color: "#e7e9f3" }}>
        <p className="text-sm" style={{ color: "#fb7185" }}>{authError}</p>
        <Link to="/login" className="text-sm underline">Back to sign in</Link>
      </div>
    );
  }
  return (
    <div className="flex min-h-dvh items-center justify-center" style={{ background: "#07080d" }}>
      <Spinner />
    </div>
  );
}
