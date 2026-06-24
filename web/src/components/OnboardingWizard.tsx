import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plug, Network, Video, Check, ArrowRight, X, Sparkles } from "lucide-react";
import { vigil } from "@/lib/vigil";
import { BRAND } from "@/lib/brand";

const DONE_KEY = "vigil.onboarding.done";

type StepState = { connected: boolean; ran: boolean; met: boolean };

interface Step {
  key: keyof StepState;
  icon: typeof Plug;
  title: string;
  body: string;
  cta: string;
  to: string;
}

const STEPS: Step[] = [
  { key: "connected", icon: Plug, title: "Connect a platform", to: "/connections", cta: "Open Connections",
    body: "Link your own GitHub, HubSpot, Stripe, Gmail or Notion. Your departments work YOUR live data — keys stay in your account." },
  { key: "ran", icon: Network, title: "Run a department", to: "/ops-team", cta: "Open Ops Team",
    body: "Your AI company has departments (Support, Finance, Revenue, Legal…). Run one — each only counts as working once it passes its effectiveness contract." },
  { key: "met", icon: Video, title: "Convene the council", to: "/meeting-room", cta: "Open Meeting Room",
    body: "Start a meeting and convene the multi-advisor council. Close it and VIGIL summarizes, then the departments review the summary." },
];

/**
 * First-run onboarding wizard + checklist. Shows once per browser (localStorage
 * gated), reflects REAL account state (connections / department runs / meetings)
 * so completed steps tick automatically, and routes the user to each surface.
 * Branded to match the VIGIL landing.
 */
export function OnboardingWizard() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<StepState>({ connected: false, ran: false, met: false });

  useEffect(() => {
    try {
      if (localStorage.getItem(DONE_KEY) === "1") return;
    } catch { /* private mode — show it */ }
    let on = true;
    void (async () => {
      const [conns, tasks, rooms] = await Promise.all([
        vigil.connect.status().then((d) => d.connections?.length ?? 0).catch(() => 0),
        vigil.ops.tasks(undefined, 1).then((d) => d.tasks?.length ?? 0).catch(() => 0),
        vigil.rooms.list().then((d) => d.rooms?.length ?? 0).catch(() => 0),
      ]);
      if (!on) return;
      setState({ connected: conns > 0, ran: tasks > 0, met: rooms > 0 });
      setOpen(true);
    })();
    return () => { on = false; };
  }, []);

  if (!open) return null;

  const done = (k: keyof StepState) => state[k];
  const completed = STEPS.filter((s) => done(s.key)).length;
  const dismiss = () => {
    try { localStorage.setItem(DONE_KEY, "1"); } catch { /* ignore */ }
    setOpen(false);
  };
  const go = (to: string) => { dismiss(); navigate(to); };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4"
         style={{ background: "rgba(2,12,12,.72)", backdropFilter: "blur(4px)" }}
         role="dialog" aria-modal="true" aria-label="Welcome to VIGIL">
      <style>{`@keyframes ob-in{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}`}</style>
      <div className="relative w-full max-w-lg overflow-hidden rounded-2xl"
           style={{ background: BRAND.panel, border: `1px solid ${BRAND.line}`, color: BRAND.ink, animation: "ob-in .5s cubic-bezier(.2,.7,.2,1) both" }}>
        <div aria-hidden className="pointer-events-none absolute inset-0"
             style={{ background: `radial-gradient(80% 50% at 50% 0%, ${BRAND.gold}18, transparent 70%)` }} />
        <button onClick={dismiss} aria-label="Skip" className="absolute right-3 top-3 z-10 rounded p-1.5"
                style={{ color: `${BRAND.ink}99` }}><X className="h-4 w-4" /></button>

        <div className="relative p-7">
          <div className="flex items-center gap-2" style={{ fontFamily: BRAND.mono, fontSize: 11, letterSpacing: ".18em", textTransform: "uppercase", color: BRAND.gold }}>
            <Sparkles className="h-3.5 w-3.5" /> Welcome to VIGIL
          </div>
          <h2 className="mt-2 text-3xl font-bold" style={{ fontFamily: BRAND.display }}>Let's get you set up</h2>
          <p className="mt-1.5 text-sm" style={{ color: `${BRAND.ink}99` }}>
            Three steps to your first defensible decision. {completed}/{STEPS.length} done.
          </p>

          {/* progress */}
          <div className="mt-4 h-1.5 w-full overflow-hidden rounded-full" style={{ background: `${BRAND.ink}1a` }}>
            <div className="h-full rounded-full transition-all" style={{ width: `${(completed / STEPS.length) * 100}%`, background: BRAND.gold }} />
          </div>

          <ol className="mt-5 flex flex-col gap-2.5">
            {STEPS.map((s, i) => {
              const isDone = done(s.key);
              const Icon = s.icon;
              return (
                <li key={s.key} className="flex items-start gap-3 rounded-lg p-3"
                    style={{ border: `1px solid ${isDone ? `${BRAND.emer}44` : BRAND.line}`, background: isDone ? `${BRAND.emer}0f` : "transparent" }}>
                  <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded"
                       style={{ background: isDone ? `${BRAND.emer}22` : `${BRAND.gold}1c`, color: isDone ? BRAND.emer : BRAND.gold }}>
                    {isDone ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold">{i + 1}. {s.title}</span>
                      {!isDone && (
                        <button onClick={() => go(s.to)} className="ml-auto inline-flex shrink-0 items-center gap-1 rounded px-2 py-1 text-[11px] font-bold uppercase tracking-widest"
                                style={{ background: BRAND.gold, color: BRAND.bg, fontFamily: BRAND.mono }}>
                          {s.cta} <ArrowRight className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                    <p className="mt-1 text-xs" style={{ color: `${BRAND.ink}88` }}>{s.body}</p>
                  </div>
                </li>
              );
            })}
          </ol>

          <div className="mt-5 flex items-center justify-between">
            <button onClick={dismiss} className="text-xs hover:underline" style={{ color: `${BRAND.ink}80` }}>Skip for now</button>
            <button onClick={dismiss} className="rounded px-4 py-2 text-xs font-bold uppercase tracking-widest"
                    style={{ border: `1px solid ${BRAND.line}`, color: BRAND.ink, fontFamily: BRAND.mono }}>
              {completed === STEPS.length ? "All set" : "I'll explore on my own"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
