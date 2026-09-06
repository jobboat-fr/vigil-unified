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
 * Le rôle LEARN de l'appelant, et le fait qu'on le connaisse.
 *
 * Lu dans `app_metadata`, jamais dans `user_metadata` : ce dernier est modifiable par le
 * titulaire du compte, donc un rôle qui en viendrait laisserait chacun se promouvoir. La
 * règle est appliquée côté serveur, qui est ce qui la tient réellement ; ceci n'existe que
 * pour que la navigation cache ce qu'un appelant ne peut pas utiliser.
 *
 * `resolu` compte autant que `role`, et son absence était un vrai défaut : pendant le
 * temps de lecture de la session, `role` valait `null`, indiscernable de « aucun rôle ».
 * Les gardes de route en concluaient « hors liste » et redirigeaient — si bien qu'un
 * super_admin qui ouvrait /noyau directement se retrouvait renvoyé au tableau de bord
 * avant même que son rôle ne soit connu.
 */
export function useLearnRole(): { role: string | null; resolu: boolean } {
  const [state, setState] = useState<{ role: string | null; resolu: boolean }>({
    role: null,
    // Sans Supabase configuré il n'y a rien à attendre : autant le dire tout de suite.
    resolu: !supabase,
  });
  useEffect(() => {
    if (!supabase) return;
    let alive = true;
    const read = (s: { user?: { app_metadata?: Record<string, unknown> } } | null) => {
      if (!alive) return;
      const meta = (s?.user?.app_metadata ?? {}) as Record<string, unknown>;
      setState({ role: (meta.learn_role as string | undefined) ?? null, resolu: true });
    };
    supabase.auth.getSession().then(({ data }) => read(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => read(s));
    return () => {
      alive = false;
      sub.subscription.unsubscribe();
    };
  }, []);
  return state;
}
