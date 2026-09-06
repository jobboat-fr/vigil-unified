import { useEffect, useState } from "react";
// Supabase client for the VIGIL × WinnyWoo product layer.
//
// The WinnyWoo gateway authenticates with a Supabase JWT (gateway.auth
// .get_current_user), so the product pages (Signals, Positions, Orders, Audit,
// Vault, Trade Desk) need a Supabase session to talk to it. This mirrors the
// VIGIL frontend's client (same `vigil-auth` storage key so a session created
// there is reused here). Distinct from the Hermes dashboard's own session-token
// auth in `@/lib/api`.
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

// Null when env isn't configured (e.g. pure-Hermes dashboard build) — callers
// treat a missing client as "not signed in to VIGIL" and render an empty state
// rather than crashing.
export const supabase: SupabaseClient | null =
  url && anon
    ? createClient(url, anon, {
        auth: {
          autoRefreshToken: true,
          detectSessionInUrl: true,
          persistSession: true,
          flowType: "pkce",
          storageKey: "vigil-auth",
        },
      })
    : null;

export async function getAccessToken(): Promise<string | null> {
  if (!supabase) return null;
  try {
    const { data } = await supabase.auth.getSession();
    return data?.session?.access_token ?? null;
  } catch {
    return null;
  }
}

/**
 * The caller's LEARN role, or null when signed out / not yet loaded.
 *
 * Read from `app_metadata`, never `user_metadata`: the latter is writable by the account's
 * own owner, so a role taken from it would let anyone promote themselves. The API applies
 * the same rule server-side, which is what actually enforces it — this exists only so the
 * navigation can hide what a caller cannot use.
 */
export function useLearnRole(): string | null {
  const [role, setRole] = useState<string | null>(null);
  useEffect(() => {
    if (!supabase) return;
    let alive = true;
    const read = (s: { user?: { app_metadata?: Record<string, unknown> } } | null) => {
      if (!alive) return;
      const meta = (s?.user?.app_metadata ?? {}) as Record<string, unknown>;
      setRole((meta.learn_role as string | undefined) ?? null);
    };
    supabase.auth.getSession().then(({ data }) => read(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => read(s));
    return () => {
      alive = false;
      sub.subscription.unsubscribe();
    };
  }, []);
  return role;
}
