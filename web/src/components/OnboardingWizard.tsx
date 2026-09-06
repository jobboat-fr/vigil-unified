import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, CalendarDays, PenLine, Check, ArrowRight, X, Sparkles } from "lucide-react";
import { getPrograms, getSessions } from "@/lib/learn";
import { BRAND } from "@/lib/brand";

const DONE_KEY = "vtlvs.onboarding.done";

type StepState = { connected: boolean; ran: boolean; met: boolean };

interface Step {
  key: keyof StepState;
  icon: typeof BookOpen;
  title: string;
  body: string;
  cta: string;
  to: string;
}

const STEPS: Step[] = [
  { key: "connected", icon: BookOpen, title: "Publier un programme", to: "/learn/formations", cta: "Ouvrir Formations",
    body: "Objectifs, prérequis, durée, modalité. Un programme publié est ce qu'un auditeur ouvre en premier — et ce qu'un prospect voit sur le site vitrine." },
  { key: "ran", icon: CalendarDays, title: "Planifier une session", to: "/learn/calendar", cta: "Ouvrir le planning",
    body: "Des dates, une salle, un formateur. Le planning génère les demi-journées : c'est la maille de l'émargement, pas un simple agenda." },
  { key: "met", icon: PenLine, title: "Émarger la première demi-journée", to: "/learn/emargement", cta: "Ouvrir l'émargement",
    body: "Chaque signature entre dans une chaîne inaltérable — ni correction, ni suppression, par personne. C'est ce qui rend la présence opposable." },
];

/**
 * L'accueil du premier lancement : trois pas, une fois par navigateur.
 *
 * Il présentait les étapes de Hermes — connecter GitHub ou Stripe, lancer un département,
 * convoquer le conseil — en anglais, à un responsable d'organisme de formation. La première
 * chose que voyait un nouvel arrivant décrivait donc un autre produit.
 *
 * Les trois étapes sont désormais celles qui construisent un dossier opposable : un
 * programme, une session, une signature. Elles se cochent sur l'état réel du compte, pas
 * sur une case locale.
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
      // L'état réel du compte, pas une case cochée localement : une étape déjà faite
      // s'affiche faite. Les deux appels échouent silencieusement — un panneau
      // d'accueil ne doit pas être la première erreur que voit un nouvel arrivant.
      const [programs, sessions] = await Promise.all([
        getPrograms().then((r) => r.items.length).catch(() => 0),
        getSessions().then((r) => r.items.length).catch(() => 0),
      ]);
      if (!on) return;
      const slots = sessions > 0;
      setState({ connected: programs > 0, ran: sessions > 0, met: slots && sessions > 1 });
      setOpen(true);
    })();
    return () => { on = false; };
  }, []);

  // Modal a11y: focus the dialog on open, trap Tab inside it, close on Escape,
  // and restore focus to the previously-focused element on close.
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        try { localStorage.setItem(DONE_KEY, "1"); } catch { /* ignore */ }
        setOpen(false);
        return;
      }
      if (e.key !== "Tab") return;
      const node = dialogRef.current;
      if (!node) return;
      const f = Array.from(
        node.querySelectorAll<HTMLElement>('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])'),
      ).filter((el) => !el.hasAttribute("disabled"));
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [open]);

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
         style={{ background: "color-mix(in srgb, var(--midground-base) 45%, transparent)", backdropFilter: "blur(4px)" }}>
      <style>{`@keyframes ob-in{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
        .ob-modal{animation:ob-in .5s cubic-bezier(.2,.7,.2,1) both}
        .ob-modal button:focus-visible{outline:2px solid ${BRAND.gold};outline-offset:2px}
        @media (prefers-reduced-motion: reduce){.ob-modal{animation:none}}`}</style>
      <div ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Bienvenue sur VTLVS"
           className="ob-modal relative w-full max-w-lg overflow-hidden rounded-2xl outline-none"
           style={{ background: BRAND.panel, border: `1px solid ${BRAND.line}`, color: BRAND.ink }}>
        <div aria-hidden className="pointer-events-none absolute inset-0"
             style={{ background: `radial-gradient(80% 50% at 50% 0%, ${BRAND.gold}18, transparent 70%)` }} />
        <button onClick={dismiss} aria-label="Passer" className="absolute right-3 top-3 z-10 rounded p-1.5"
                style={{ color: `${BRAND.ink}99` }}><X className="h-4 w-4" /></button>

        <div className="relative p-7">
          <div className="flex items-center gap-2" style={{ fontFamily: BRAND.mono, fontSize: 11, letterSpacing: ".18em", textTransform: "uppercase", color: BRAND.gold }}>
            <Sparkles className="h-3.5 w-3.5" /> Bienvenue sur VTLVS
          </div>
          <h2 className="mt-2 text-3xl font-bold" style={{ fontFamily: BRAND.display }}>Vos trois premiers pas</h2>
          <p className="mt-1.5 text-sm" style={{ color: `${BRAND.ink}99` }}>
            De quoi tenir un dossier d'audit complet. {completed}/{STEPS.length} fait.
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
            <button onClick={dismiss} className="text-xs hover:underline" style={{ color: `${BRAND.ink}99` }}>Plus tard</button>
            <button onClick={dismiss} className="rounded px-4 py-2 text-xs font-bold uppercase tracking-widest"
                    style={{ border: `1px solid ${BRAND.line}`, color: BRAND.ink, fontFamily: BRAND.mono }}>
              {completed === STEPS.length ? "C'est prêt" : "Je découvre seul"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
