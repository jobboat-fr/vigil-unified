import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { BRAND } from "@/lib/brand";

type Mode = "signin" | "reset";

/**
 * L'écran d'entrée. Rien d'autre n'est accessible sans passer par ici : `AuthGate` échoue
 * fermé et rend cette page pour toute session absente ou expirée.
 *
 * Le logo sert de fond, agrandi. C'est demandé, et c'est piégeux : la marque ne couvre que
 * ~3 % de la surface, donc à opacité naïve elle disparaît. Elle est donc
 * posé en `background-size: cover` à une opacité assumée, avec un voile dégradé par-dessus
 * — dense au centre, sous la carte, transparent sur les bords. Le motif reste visible sans
 * qu'aucune couleur ne passe sous le texte.
 *
 * Les fournisseurs OAuth (Google/Apple/GitHub/Railway) hérités de Hermes ont été retirés :
 * aucun n'est configuré sur ce projet Supabase, et un bouton qui renvoie la page d'erreur
 * du fournisseur est pire que pas de bouton. L'identifiant reste e-mail + mot de passe,
 * qui est ce que la plateforme provisionne pour chaque rôle.
 */
export default function AuthPage({ initialMode = "signin" }: { initialMode?: Mode }) {
  const { signIn, resetPassword, authError } = useAuth();
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");
  const [err, setErr] = useState<string>("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(""); setMsg("");
    try {
      if (mode === "signin") {
        const { error } = await signIn(email.trim(), password);
        if (error) setErr(traduire(error.message));
      } else {
        const { error } = await resetPassword(email.trim());
        if (error) setErr(traduire(error.message));
        else setMsg("Lien de réinitialisation envoyé — consultez votre messagerie.");
      }
    } catch (e2) {
      setErr(traduire((e2 as Error).message));
    } finally {
      setBusy(false);
    }
  }

  const heading = mode === "signin" ? "Accéder à votre espace" : "Réinitialiser le mot de passe";
  const cta = mode === "signin" ? "Se connecter" : "Envoyer le lien";
  const label = {
    fontFamily: BRAND.mono,
    fontSize: 10,
    letterSpacing: ".12em",
    textTransform: "uppercase" as const,
    color: `${BRAND.ink}99`,
  };

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden p-4"
         style={{ background: BRAND.bg, color: BRAND.ink }}>
      <style>{`
        @keyframes ap-in{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
        .ap-in{animation:ap-in .6s cubic-bezier(.2,.7,.2,1) both}
        .ap-mark{background-image:url("/logo-mark.png");background-repeat:no-repeat;background-position:center;background-size:contain;opacity:.07}
        .ap-veil{background:radial-gradient(52% 44% at 50% 50%, ${BRAND.bg}f2 0%, ${BRAND.bg}d9 45%, ${BRAND.bg}66 78%, transparent 100%)}
        .ap-card{background:rgba(255,255,255,.62);backdrop-filter:blur(14px) saturate(1.1);-webkit-backdrop-filter:blur(14px) saturate(1.1)}
        .ap-field{width:100%;border-radius:.5rem;border:1px solid ${BRAND.line};background:rgba(255,255,255,.9);padding:.6rem .75rem;font-size:.875rem;color:${BRAND.ink};outline:none;transition:border-color .15s,box-shadow .15s}
        .ap-field::placeholder{color:${BRAND.ink}55}
        .ap-field:focus{border-color:${BRAND.gold};box-shadow:0 0 0 3px ${BRAND.gold}22}
        .ap-field:focus-visible,button:focus-visible{outline:2px solid ${BRAND.gold};outline-offset:2px}
        @media (prefers-reduced-motion: reduce){.ap-in{animation:none!important}}
      `}</style>
      <div aria-hidden className="ap-mark pointer-events-none absolute inset-0" />
      <div aria-hidden className="ap-veil pointer-events-none absolute inset-0" />

      <div className="ap-in relative flex w-full max-w-sm flex-col gap-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <Link to="/" className="flex flex-col items-center gap-3 hover:opacity-90">
            <img src="/logo-lockup.png" alt="VTLVS" style={{ height: 72, width: "auto" }} />
            <h1 className="text-3xl font-bold" style={{ fontFamily: BRAND.display, letterSpacing: ".02em" }}>VTLVS</h1>
          </Link>
          <p style={{ ...label, fontSize: 11, letterSpacing: ".18em" }}>{heading}</p>
        </div>

        <form onSubmit={submit} className="ap-card flex flex-col gap-3 rounded-xl p-6"
              style={{ border: `1px solid ${BRAND.line}`, boxShadow: "0 18px 48px -24px rgba(11,34,57,.45)" }}>
          <label className="flex flex-col gap-1.5">
            <span style={label}>Adresse e-mail</span>
            <input className="ap-field" type="email" autoComplete="email" required
                   value={email} onChange={(e) => setEmail(e.target.value)}
                   placeholder="prenom.nom@organisme.fr" />
          </label>

          {mode === "signin" && (
            <label className="flex flex-col gap-1.5">
              <span style={label}>Mot de passe</span>
              <input className="ap-field" type="password" autoComplete="current-password" required minLength={6}
                     value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
            </label>
          )}

          {(err || authError) && <p role="alert" className="text-xs" style={{ color: BRAND.rose }}>{err || authError}</p>}
          {msg && <p role="status" className="text-xs" style={{ color: BRAND.emer }}>{msg}</p>}

          <button type="submit" disabled={busy}
                  className="mt-1 w-full rounded-md py-2.5 text-sm font-bold uppercase tracking-widest disabled:opacity-60"
                  style={{ background: BRAND.gold, color: "#ffffff", fontFamily: BRAND.mono }}>
            {busy ? "…" : cta}
          </button>

          <div className="flex items-center justify-between pt-1 text-xs" style={{ color: `${BRAND.ink}99` }}>
            {mode === "signin" ? (
              <button type="button" className="hover:underline"
                      onClick={() => { setMode("reset"); setErr(""); setMsg(""); }}>
                Mot de passe oublié ?
              </button>
            ) : (
              <button type="button" className="hover:underline"
                      onClick={() => { setMode("signin"); setErr(""); setMsg(""); }}>
                ← Retour à la connexion
              </button>
            )}
          </div>
        </form>

        {/* Les comptes sont créés par l'organisme, jamais en libre-service : un compte sans
            rôle ni organisme ne verrait rien, et le parcours d'entrée public passe par le
            test de positionnement du site vitrine. */}
        <p className="text-center text-xs leading-relaxed" style={{ color: `${BRAND.ink}88` }}>
          Pas encore de compte ? Les accès sont délivrés par votre organisme de formation.{" "}
          <a href="https://hbs-formation.fr/preinscription" className="underline hover:opacity-80">
            Demander une préinscription
          </a>
        </p>
      </div>
    </div>
  );
}

/** Les messages GoTrue arrivent en anglais ; les trois que voit réellement un utilisateur. */
function traduire(m: string): string {
  const s = m.toLowerCase();
  if (s.includes("invalid login credentials")) return "Adresse e-mail ou mot de passe incorrect.";
  if (s.includes("email not confirmed")) return "Adresse e-mail non confirmée — consultez votre messagerie.";
  if (s.includes("rate limit") || s.includes("too many")) return "Trop de tentatives. Réessayez dans quelques minutes.";
  return m;
}
