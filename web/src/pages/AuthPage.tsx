import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { BRAND } from "@/lib/brand";

type Mode = "signin" | "signup" | "reset";

export default function AuthPage({ initialMode = "signin" }: { initialMode?: Mode }) {
  const { signIn, signUp, resetPassword, signInWithGoogle, signInWithApple, signInWithGithub, signInWithRailway, authError } = useAuth();
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
        if (error) setErr(error.message);
      } else if (mode === "signup") {
        const { data, error } = await signUp(email.trim(), password);
        if (error) setErr(error.message);
        else if (!data?.session) setMsg("Check your email to confirm your account, then sign in.");
      } else {
        const { error } = await resetPassword(email.trim());
        if (error) setErr(error.message);
        else setMsg("Password reset link sent — check your email.");
      }
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const heading = mode === "signin" ? "Sign in to your workspace"
    : mode === "signup" ? "Create your account" : "Reset your password";
  const cta = mode === "signin" ? "Sign in" : mode === "signup" ? "Create account" : "Send reset link";

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden p-4"
         style={{ background: BRAND.bg, color: BRAND.ink }}>
      <style>{`
        @keyframes ap-in{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
        .ap-in{animation:ap-in .6s cubic-bezier(.2,.7,.2,1) both}
        .ap-grid{background-image:linear-gradient(${BRAND.line} 1px,transparent 1px),linear-gradient(90deg,${BRAND.line} 1px,transparent 1px);background-size:46px 46px}
        .ap-field{width:100%;border-radius:.375rem;border:1px solid ${BRAND.line};background:rgba(255,230,203,.04);padding:.55rem .7rem;font-size:.875rem;color:${BRAND.ink};outline:none}
        .ap-field:focus{border-color:${BRAND.gold}88}
        .ap-oauth{border:1px solid ${BRAND.line};border-radius:.375rem;padding:.5rem;font-size:.8rem;color:${BRAND.ink};transition:background .15s,border-color .15s}
        .ap-oauth:hover{background:rgba(255,230,203,.05);border-color:${BRAND.gold}55}
      `}</style>
      <div aria-hidden className="ap-grid pointer-events-none absolute inset-0 opacity-50"
           style={{ maskImage: "radial-gradient(70% 55% at 50% 0%, #000 30%, transparent 75%)" }} />
      <div aria-hidden className="pointer-events-none absolute inset-0"
           style={{ background: `radial-gradient(55% 40% at 50% -5%, ${BRAND.gold}1f, transparent 70%)` }} />

      <div className="ap-in relative w-full max-w-sm flex flex-col gap-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <Link to="/" className="flex flex-col items-center gap-3 hover:opacity-90">
            <img src="/vigil-mark.svg" alt="VIGIL" width={44} height={44} />
            <h1 className="text-3xl font-bold" style={{ fontFamily: BRAND.display, letterSpacing: ".02em" }}>VIGIL</h1>
          </Link>
          <p style={{ fontFamily: BRAND.mono, fontSize: 11, letterSpacing: ".18em", textTransform: "uppercase", color: `${BRAND.ink}80` }}>
            {heading}
          </p>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-3 rounded-xl p-6"
              style={{ background: BRAND.panel, border: `1px solid ${BRAND.line}` }}>
          <label className="flex flex-col gap-1.5">
            <span style={{ fontFamily: BRAND.mono, fontSize: 10, letterSpacing: ".12em", textTransform: "uppercase", color: `${BRAND.ink}70` }}>Email</span>
            <input className="ap-field" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          </label>

          {mode !== "reset" && (
            <label className="flex flex-col gap-1.5">
              <span style={{ fontFamily: BRAND.mono, fontSize: 10, letterSpacing: ".12em", textTransform: "uppercase", color: `${BRAND.ink}70` }}>Password</span>
              <input className="ap-field" type="password" autoComplete={mode === "signup" ? "new-password" : "current-password"} required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
            </label>
          )}

          {(err || authError) && <p className="text-xs" style={{ color: BRAND.rose }}>{err || authError}</p>}
          {msg && <p className="text-xs" style={{ color: BRAND.emer }}>{msg}</p>}

          <button type="submit" disabled={busy} className="mt-1 w-full rounded-md py-2.5 text-sm font-bold uppercase tracking-widest disabled:opacity-60"
                  style={{ background: BRAND.gold, color: BRAND.bg, fontFamily: BRAND.mono }}>
            {busy ? "…" : cta}
          </button>
        </form>

        {mode !== "reset" && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2" style={{ fontFamily: BRAND.mono, fontSize: 10, letterSpacing: ".12em", textTransform: "uppercase", color: `${BRAND.ink}55` }}>
              <span className="h-px flex-1" style={{ background: BRAND.line }} /> or <span className="h-px flex-1" style={{ background: BRAND.line }} />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button type="button" className="ap-oauth" onClick={() => void signInWithGoogle()}>Google</button>
              <button type="button" className="ap-oauth" onClick={() => void signInWithApple()}>Apple</button>
              <button type="button" className="ap-oauth" onClick={() => void signInWithGithub()}>GitHub</button>
              <button type="button" className="ap-oauth" onClick={() => void signInWithRailway()}>Railway</button>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between text-xs" style={{ color: `${BRAND.ink}70` }}>
          {mode === "signin" ? (
            <>
              <button type="button" className="hover:underline" onClick={() => setMode("signup")}>Create account</button>
              <button type="button" className="hover:underline" onClick={() => setMode("reset")}>Forgot password?</button>
            </>
          ) : (
            <button type="button" className="hover:underline" onClick={() => setMode("signin")}>← Back to sign in</button>
          )}
        </div>
      </div>
    </div>
  );
}
