import { useState } from "react";
import { Link } from "react-router-dom";
import { Button } from "@nous-research/ui/ui/components/button";
import { useAuth } from "@/context/AuthContext";

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

  const inputCls =
    "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50";

  return (
    <div className="min-h-dvh flex items-center justify-center p-4">
      <div className="w-full max-w-sm flex flex-col gap-6">
        <div className="flex flex-col items-center gap-2">
          <Link to="/" className="flex flex-col items-center gap-2 hover:opacity-80">
            <img src="/vigil-mark.svg" alt="VIGIL" width={48} height={48} />
            <h1 className="text-lg font-bold tracking-[0.05em]">VIGIL × WinnyWoo</h1>
          </Link>
          <p className="text-xs text-text-secondary">
            {mode === "signin" ? "Sign in to your workspace" : mode === "signup" ? "Create your account" : "Reset your password"}
          </p>
        </div>

        <form onSubmit={submit} className="ww-glass flex flex-col gap-3 rounded-lg p-5">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wide text-text-secondary">Email</span>
            <input className={inputCls} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" />
          </label>

          {mode !== "reset" && (
            <label className="flex flex-col gap-1">
              <span className="text-[11px] uppercase tracking-wide text-text-secondary">Password</span>
              <input className={inputCls} type="password" autoComplete={mode === "signup" ? "new-password" : "current-password"} required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
            </label>
          )}

          {err && <p className="text-xs" style={{ color: "#ff3366" }}>{err || authError}</p>}
          {msg && <p className="text-xs" style={{ color: "#00ff88" }}>{msg}</p>}

          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "…" : mode === "signin" ? "Sign in" : mode === "signup" ? "Create account" : "Send reset link"}
          </Button>
        </form>

        {mode !== "reset" && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-[10px] uppercase tracking-wide text-text-secondary">
              <span className="h-px flex-1 bg-current/15" /> or <span className="h-px flex-1 bg-current/15" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Button ghost className="w-full" onClick={() => void signInWithGoogle()}>Google</Button>
              <Button ghost className="w-full" onClick={() => void signInWithApple()}>Apple</Button>
              <Button ghost className="w-full" onClick={() => void signInWithGithub()}>GitHub</Button>
              <Button ghost className="w-full" onClick={() => void signInWithRailway()}>Railway</Button>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-text-secondary">
          {mode === "signin" ? (
            <>
              <button type="button" className="hover:text-foreground" onClick={() => setMode("signup")}>Create account</button>
              <button type="button" className="hover:text-foreground" onClick={() => setMode("reset")}>Forgot password?</button>
            </>
          ) : (
            <button type="button" className="hover:text-foreground" onClick={() => setMode("signin")}>← Back to sign in</button>
          )}
        </div>
      </div>
    </div>
  );
}
