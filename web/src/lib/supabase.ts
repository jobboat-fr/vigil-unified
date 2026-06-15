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
