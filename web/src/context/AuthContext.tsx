// VIGIL × WinnyWoo auth — Supabase session provider.
//
// Ported from the VIGIL frontend (frntendv2 src/context/AuthContext.jsx) onto
// the shared `@/lib/supabase` client (storage key `vigil-auth`, same Supabase
// project the gateway validates against). Gates the whole app; the product
// pages (Signals/Trade Desk/Vault/Council…) get their session from here.
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import type { Provider, Session, User } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";
import { clearHermesSession } from "@/lib/api";

interface AuthValue {
  user: User | null;
  session: Session | null;
  loading: boolean;
  authError: string;
  configured: boolean;
  signIn: (email: string, password: string) => Promise<{ error: { message: string } | null }>;
  signUp: (email: string, password: string) => Promise<{ data: { session: Session | null } | null; error: { message: string } | null }>;
  signOut: () => Promise<void>;
  resetPassword: (email: string) => Promise<{ error: { message: string } | null }>;
  signInWithGoogle: () => Promise<void>;
  signInWithApple: () => Promise<void>;
  signInWithGithub: () => Promise<void>;
  signInWithRailway: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

const noop = async () => ({ error: null });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState("");

  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return;
    }
    let mounted = true;
    const cleanUrl = () => {
      if (window.location.search || window.location.hash) {
        window.history.replaceState(null, "", window.location.pathname);
      }
    };

    async function init() {
      // `finally` ALWAYS clears loading, so a rejected/hung auth call can never
      // leave the gate stuck on its spinner.
      try {
        const params = new URLSearchParams(window.location.search);
        const cbErr = params.get("error_description") || params.get("error");
        const code = params.get("code");

        if (cbErr) {
          if (mounted) { setAuthError(cbErr); cleanUrl(); }
          return;
        }
        if (code) {
          const { data, error } = await supabase!.auth.exchangeCodeForSession(code);
          if (!mounted) return;
          if (error) setAuthError(error.message || "OAuth callback failed");
          else { setSession(data?.session ?? null); setUser(data?.session?.user ?? null); setAuthError(""); }
          cleanUrl();
          return;
        }
        // `getSession()` can hang on the Navigator LockManager (a known
        // supabase-js deadlock). Race it against a timeout so the gate never
        // freezes — if the call was merely slow, `onAuthStateChange` recovers
        // the session a moment later and swaps the public site for the app.
        const restored = await Promise.race([
          supabase!.auth.getSession().then((r) => r.data.session ?? null),
          new Promise<Session | null>((resolve) => setTimeout(() => resolve(null), 4000)),
        ]);
        if (!mounted) return;
        setSession(restored);
        setUser(restored?.user ?? null);
      } catch (e) {
        if (mounted) setAuthError((e as Error)?.message || "Could not restore session");
      } finally {
        if (mounted) setLoading(false);
      }
    }
    void init();

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, s) => {
      setSession(s);
      const next = s?.user ?? null;
      // Keep the same user-object reference when identity is unchanged so
      // `[user]` effects don't churn on every token refresh / tab focus.
      setUser((prev) => (prev && next && prev.id === next.id ? prev : next));
      if (s) setAuthError("");
      if (event === "SIGNED_IN") cleanUrl();
    });
    return () => { mounted = false; subscription.unsubscribe(); };
  }, []);

  const redirect = () => `${window.location.origin}/auth`;

  const value: AuthValue = supabase
    ? {
        user, session, loading, authError, configured: true,
        signIn: (email, password) => supabase!.auth.signInWithPassword({ email, password }).then((r) => ({ error: r.error })),
        signUp: (email, password) => supabase!.auth.signUp({ email, password }).then((r) => ({ data: { session: r.data?.session ?? null }, error: r.error })),
        // Full logout: tear down the embedded operator-console session first
        // (drops the injected token + hermes.* storage + gated cookie), then
        // revoke the Supabase product session (server-side refresh-token revoke
        // + clears the local `vigil-auth` store). Caller navigates to /login.
        signOut: async () => {
          await clearHermesSession();
          await supabase!.auth.signOut();
        },
        resetPassword: (email) => supabase!.auth.resetPasswordForEmail(email, { redirectTo: redirect() }).then((r) => ({ error: r.error })),
        signInWithGoogle: () => supabase!.auth.signInWithOAuth({ provider: "google", options: { redirectTo: redirect() } }).then(() => undefined),
        signInWithApple: () => supabase!.auth.signInWithOAuth({ provider: "apple", options: { redirectTo: redirect() } }).then(() => undefined),
        signInWithGithub: () => supabase!.auth.signInWithOAuth({ provider: "github", options: { redirectTo: redirect() } }).then(() => undefined),
        // Railway is a Supabase custom OIDC provider (configured as "railwayoauth").
        signInWithRailway: () => supabase!.auth.signInWithOAuth({ provider: "custom:railwayoauth" as Provider, options: { redirectTo: redirect() } }).then(() => undefined),
      }
    : {
        user: null, session: null, loading, authError: "", configured: false,
        signIn: noop, signUp: async () => ({ data: null, error: null }), signOut: async () => {},
        resetPassword: noop, signInWithGoogle: async () => {}, signInWithApple: async () => {}, signInWithGithub: async () => {}, signInWithRailway: async () => {},
      };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
