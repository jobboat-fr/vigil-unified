import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight, Gavel, LineChart, Receipt, Contact, Mail, PenLine, Lock,
  ShieldCheck, Sparkles, BrainCircuit, GitBranch,
} from "lucide-react";
import { ww, type MarketOverview } from "@/lib/ww";
import { useSeo } from "@/lib/seo";

// Hermes design language (LENS_0): teal canvas + cream ink + warm amber glow +
// emerald positive. Display type is Mondwest (the Nous DS brand face, loaded in
// index.css); labels are JetBrains Mono. Mirrors the dashboard so the marketing
// site and the product read as one product.
const BG = "#041c1c";       // teal canvas
const INK = "#ffe6cb";      // cream
const GOLD = "#ffbd38";     // warm accent (CTA / highlight)
const EMER = "#34d399";     // positive
const ROSE = "#fb7185";     // negative
const PANEL = "#07211f";    // raised teal panel
const LINE = "rgba(255,230,203,0.14)";
const DISPLAY = "'Mondwest', ui-serif, Georgia, serif";
const MONO = "'JetBrains Mono', ui-monospace, 'Cascadia Mono', Menlo, monospace";

export default function LandingPage() {
  const navigate = useNavigate();
  const [mkt, setMkt] = useState<MarketOverview | null>(null);
  useSeo({
    title: "VIGIL — the AI workspace that thinks before it acts",
    description:
      "An AI workspace that deliberates before acting: a multi-advisor council, a data-grounded trade desk, and your finance, CRM, mail and document studio — all human-in-the-loop.",
    path: "/",
  });

  useEffect(() => {
    let on = true;
    const pull = () => ww.market.overview().then((d) => on && setMkt(d)).catch(() => {});
    pull();
    const t = setInterval(pull, 30_000);
    return () => { on = false; clearInterval(t); };
  }, []);

  return (
    <div style={{ background: BG, color: INK, minHeight: "100dvh" }} className="overflow-x-hidden">
      <style>{`
        @keyframes ll-in { from{opacity:0;transform:translateY(16px)} to{opacity:1;transform:none} }
        @keyframes ll-grad { 0%{background-position:0% 50%} 100%{background-position:200% 50%} }
        @keyframes ll-blink { 0%,49%{opacity:1} 50%,100%{opacity:0} }
        .ll-in{animation:ll-in .7s cubic-bezier(.2,.7,.2,1) both}
        .ll-disp{font-family:${DISPLAY};letter-spacing:.01em}
        .ll-mono{font-family:${MONO}}
        .ll-grad{background:linear-gradient(90deg,${GOLD},${INK},${EMER},${GOLD});background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:transparent;animation:ll-grad 7s linear infinite}
        .ll-cursor::after{content:"_";margin-left:.06em;animation:ll-blink 1.1s step-end infinite;color:${GOLD}}
        .ll-card{transition:transform .2s ease,border-color .2s ease,background .2s ease}
        .ll-card:hover{transform:translateY(-4px);border-color:${GOLD}66;background:#0a2a28}
        .ll-grid{background-image:linear-gradient(${LINE} 1px,transparent 1px),linear-gradient(90deg,${LINE} 1px,transparent 1px);background-size:46px 46px}
        .ll-mono:focus-visible,a:focus-visible{outline:2px solid ${GOLD};outline-offset:2px;border-radius:2px}
        @media (forced-colors: active){.ll-grad{-webkit-text-fill-color:CanvasText;color:CanvasText;background:none}}
        @media (prefers-reduced-motion: reduce){.ll-in,.ll-grad,.ll-cursor::after{animation:none!important}}
      `}</style>

      {/* NAV */}
      <nav className="sticky top-0 z-20 flex items-center justify-between px-5 py-4 md:px-10"
           style={{ background: "rgba(4,28,28,.78)", backdropFilter: "blur(10px)", borderBottom: `1px solid ${LINE}` }}>
        <Link to="/" className="flex items-center gap-2.5">
          <img src="/vigil-mark.svg" alt="" width={26} height={26} />
          <span className="ll-disp text-lg font-bold tracking-[0.04em]">VIGIL</span>
        </Link>
        <div className="flex items-center gap-1 md:gap-3">
          <Link to="/docs" className="ll-mono hidden rounded px-3 py-2 text-xs uppercase tracking-widest hover:bg-white/5 sm:block" style={{ color: `${INK}aa` }}>Docs</Link>
          <Link to="/login" className="ll-mono rounded px-3 py-2 text-xs uppercase tracking-widest hover:bg-white/5" style={{ color: `${INK}aa` }}>Sign in</Link>
          <button onClick={() => navigate("/signup")} className="ll-mono rounded px-4 py-2 text-xs font-bold uppercase tracking-widest" style={{ background: GOLD, color: BG }}>
            Get started
          </button>
        </div>
      </nav>

      {/* HERO */}
      <header className="relative overflow-hidden px-5 pt-20 pb-24 text-center md:px-10 md:pt-28">
        <div aria-hidden className="ll-grid pointer-events-none absolute inset-0 opacity-[0.5]" style={{ maskImage: "radial-gradient(80% 60% at 50% 0%, #000 30%, transparent 75%)" }} />
        <div aria-hidden className="pointer-events-none absolute inset-0" style={{ background: `radial-gradient(60% 45% at 50% -5%, ${GOLD}22, transparent 70%)` }} />
        <div className="relative mx-auto max-w-4xl">
          <span className="ll-in ll-mono inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11px] uppercase tracking-widest"
                style={{ border: `1px solid ${GOLD}44`, color: GOLD }}>
            <Sparkles className="h-3.5 w-3.5" /> One agent · your council & your desk
          </span>
          <h1 className="ll-in ll-disp mt-7 text-5xl font-bold leading-[0.98] md:text-[5.5rem]" style={{ animationDelay: ".05s" }}>
            Decisions you can <span className="ll-grad">defend</span>.<br />
            Trades you have to <span className="ll-grad ll-cursor">approve</span>.
          </h1>
          <p className="ll-in mx-auto mt-7 max-w-2xl text-base md:text-lg" style={{ color: `${INK}b0`, animationDelay: ".12s" }}>
            VIGIL is an AI workspace that thinks before it acts — a multi-advisor council, a
            data-grounded trade desk, and your finance, CRM, mail and document studio, all under
            one human-in-the-loop agent.
          </p>
          <div className="ll-in mt-9 flex flex-wrap items-center justify-center gap-3" style={{ animationDelay: ".18s" }}>
            <button onClick={() => navigate("/signup")} className="ll-mono inline-flex items-center gap-2 rounded px-6 py-3 text-sm font-bold uppercase tracking-widest" style={{ background: GOLD, color: BG }}>
              Get started <ArrowRight className="h-4 w-4" />
            </button>
            <Link to="/docs" className="ll-mono rounded px-6 py-3 text-sm font-bold uppercase tracking-widest" style={{ border: `1px solid ${LINE}`, color: INK }}>Read the docs</Link>
          </div>

          {/* LIVE market pulse */}
          <div className="ll-in mx-auto mt-14 max-w-3xl" style={{ animationDelay: ".24s" }}>
            <div className="ll-mono mb-2 flex items-center justify-center gap-2 text-[11px] uppercase tracking-widest" style={{ color: `${INK}99` }}>
              <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: EMER, boxShadow: `0 0 8px ${EMER}` }} />
              Live market pulse
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <Pulse label="BTC" value={mkt?.btc_price ? `$${fmt(mkt.btc_price)}` : "—"} chg={mkt?.btc_24h_change} />
              <Pulse label="ETH" value={mkt?.eth_price ? `$${fmt(mkt.eth_price)}` : "—"} chg={mkt?.eth_24h_change} />
              <Pulse label="BTC dom." value={mkt?.btc_dominance_pct != null ? `${mkt.btc_dominance_pct.toFixed(1)}%` : "—"} />
              <Pulse label="Fear/Greed" value={mkt?.fear_greed_index != null ? String(mkt.fear_greed_index) : "—"} sub={mkt?.fear_greed_label} />
            </div>
          </div>
        </div>
      </header>

      {/* TWO PILLARS */}
      <section className="px-5 py-16 md:px-10">
        <div className="mx-auto grid max-w-5xl gap-5 md:grid-cols-2">
          <Pillar icon={<BrainCircuit />} kicker="The Council" title="A workspace that deliberates" body="Convene an AI council over any decision — CFO, CTO, Legal, Product lenses argue, score, and a chairman synthesizes a verdict. Run meetings, crystallize artifacts, ground everything in your own documents." />
          <Pillar icon={<LineChart />} kicker="The Desk" title="A desk that never trades alone" body="Forecasts and a data-grounded signal debate propose trades — every order passes a single-use human approval gate, capped at 5% of NAV. Connect your own broker; keys never leave your account." />
        </div>
      </section>

      {/* SURFACES */}
      <section className="px-5 py-12 md:px-10">
        <div className="mx-auto max-w-6xl">
          <h2 className="ll-disp text-center text-3xl font-bold md:text-4xl">Everything in one workspace</h2>
          <p className="mx-auto mt-3 max-w-xl text-center text-sm" style={{ color: `${INK}99` }}>Each surface is a real tool the agent can read, reason over, and act in — never autonomously where money or messages are involved.</p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {SURFACES.map((s) => (
              <div key={s.title} className="ll-card rounded-lg p-5" style={{ border: `1px solid ${LINE}`, background: PANEL }}>
                <div className="flex h-10 w-10 items-center justify-center rounded" style={{ background: `${GOLD}1c`, color: GOLD }}>{s.icon}</div>
                <h3 className="ll-disp mt-4 text-lg font-bold">{s.title}</h3>
                <p className="mt-1.5 text-sm" style={{ color: `${INK}99` }}>{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="px-5 py-16 md:px-10">
        <div className="mx-auto max-w-5xl">
          <h2 className="ll-disp text-center text-3xl font-bold md:text-4xl">How the agent works</h2>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            <Step n="01" title="Thinks first" body="Before building or recommending, it brainstorms approaches and presents a design. No jumping to output on unexamined assumptions." />
            <Step n="02" title="Grounds in your data" body="It reasons from your Vault documents, your live broker, your books — citing real numbers, never fabricating." />
            <Step n="03" title="Waits for you" body="Trades go through an approval gate; outbound mail is review-then-send. You stay in control of anything with consequence." />
          </div>
        </div>
      </section>

      {/* PRINCIPLES */}
      <section className="px-5 py-12 md:px-10">
        <div className="mx-auto grid max-w-5xl gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Principle icon={<ShieldCheck />} title="Human-in-the-loop" body="Single-use approval gate on every order. 5%-NAV cap. Nothing moves money on its own." />
          <Principle icon={<Lock />} title="Your keys, your data" body="Connect your own broker; credentials stay in your account. Every record scoped to you alone." />
          <Principle icon={<Gavel />} title="Dissent by design" body="The council surfaces the bear case, not just the bull. You can always override the verdict." />
          <Principle icon={<GitBranch />} title="Evidence over confidence" body="No 'done' without verification. No tax or trade claim without a cited source." />
        </div>
      </section>

      {/* FAQ — engagement + long-tail keywords; mirrors the FAQPage JSON-LD in index.html */}
      <section className="px-5 py-12 md:px-10">
        <div className="mx-auto max-w-3xl">
          <h2 className="ll-disp text-center text-3xl font-bold md:text-4xl">Questions, answered</h2>
          <div className="mt-8 flex flex-col gap-2.5">
            {FAQS.map((f) => (
              <details key={f.q} className="ll-card group rounded-lg p-4" style={{ border: `1px solid ${LINE}`, background: PANEL }}>
                <summary className="ll-disp flex cursor-pointer list-none items-center justify-between gap-3 text-base font-bold">
                  {f.q}
                  <span className="ll-mono shrink-0 text-lg leading-none transition-transform group-open:rotate-45" style={{ color: GOLD }}>+</span>
                </summary>
                <p className="mt-2.5 text-sm leading-relaxed" style={{ color: `${INK}b0` }}>{f.a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="px-5 py-20 md:px-10">
        <div className="relative mx-auto max-w-3xl overflow-hidden rounded-2xl p-10 text-center" style={{ background: PANEL, border: `1px solid ${GOLD}3a` }}>
          <div aria-hidden className="pointer-events-none absolute inset-0" style={{ background: `radial-gradient(70% 80% at 50% 0%, ${GOLD}1a, transparent 70%)` }} />
          <h2 className="ll-disp relative text-3xl font-bold md:text-4xl">Bring your judgment.<br />We'll bring the rigor.</h2>
          <p className="relative mx-auto mt-3 max-w-lg text-sm" style={{ color: `${INK}a0` }}>Create an account and convene your first council, or wire up your trading desk in minutes.</p>
          <div className="relative mt-7 flex flex-wrap justify-center gap-3">
            <button onClick={() => navigate("/signup")} className="ll-mono inline-flex items-center gap-2 rounded px-6 py-3 text-sm font-bold uppercase tracking-widest" style={{ background: GOLD, color: BG }}>
              Get started <ArrowRight className="h-4 w-4" />
            </button>
            <Link to="/login" className="ll-mono rounded px-6 py-3 text-sm font-bold uppercase tracking-widest" style={{ border: `1px solid ${LINE}`, color: INK }}>Sign in</Link>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="px-5 py-12 md:px-10" style={{ borderTop: `1px solid ${LINE}` }}>
        <div className="mx-auto max-w-6xl">
          <div className="grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
            <div className="sm:col-span-2 lg:col-span-1">
              <div className="flex items-center gap-2.5">
                <img src="/vigil-mark.svg" alt="" width={24} height={24} />
                <span className="ll-disp text-lg font-bold tracking-[0.04em]">VIGIL</span>
              </div>
              <p className="mt-3 max-w-xs text-sm" style={{ color: `${INK}99` }}>
                The AI workspace that thinks before it acts. One human-in-the-loop agent across your council, desk, and books.
              </p>
            </div>
            <FooterCol title="Product" links={[["Council & Meetings", "/login"], ["Trade Desk", "/login"], ["Finance & CRM", "/login"], ["Studio & Vault", "/login"]]} />
            <FooterCol title="Company" links={[["Docs", "/docs"], ["Sign in", "/login"], ["Get started", "/signup"]]} />
            <FooterCol title="Trust" links={[["Human-in-the-loop", "/docs"], ["Your keys, your data", "/docs"], ["Audit log", "/login"]]} />
          </div>
          <div className="mt-10 flex flex-col items-start justify-between gap-3 border-t pt-6 sm:flex-row sm:items-center" style={{ borderColor: LINE }}>
            <span className="ll-mono text-xs uppercase tracking-widest" style={{ color: `${INK}99` }}>© {new Date().getFullYear()} VIGIL</span>
            <span className="text-xs" style={{ color: `${INK}99` }}>Not financial, tax, or legal advice.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

function fmt(s: string) {
  const n = Number(s);
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: n >= 100 ? 0 : 2 }) : s;
}

function Pulse({ label, value, chg, sub }: { label: string; value: string; chg?: string; sub?: string }) {
  const c = chg != null ? Number(chg) : null;
  return (
    <div className="rounded px-3 py-2.5 text-left" style={{ background: PANEL, border: `1px solid ${LINE}` }}>
      <div className="ll-mono text-[10px] uppercase tracking-wider" style={{ color: `${INK}99` }}>{label}</div>
      <div className="ll-mono text-base font-bold tabular-nums" style={{ color: INK }}>{value}</div>
      {c != null && <div className="ll-mono text-xs tabular-nums" style={{ color: c >= 0 ? EMER : ROSE }}>{c >= 0 ? "▲" : "▼"} {Math.abs(c).toFixed(2)}%</div>}
      {sub && <div className="text-[10px]" style={{ color: `${INK}99` }}>{sub}</div>}
    </div>
  );
}

function Pillar({ icon, kicker, title, body }: { icon: ReactNode; kicker: string; title: string; body: string }) {
  return (
    <div className="ll-card rounded-lg p-7" style={{ border: `1px solid ${LINE}`, background: PANEL }}>
      <div className="flex h-11 w-11 items-center justify-center rounded" style={{ background: `${GOLD}18`, color: GOLD }}>{icon}</div>
      <div className="ll-mono mt-4 text-[11px] font-bold uppercase tracking-widest" style={{ color: GOLD }}>{kicker}</div>
      <h3 className="ll-disp mt-1 text-xl font-bold">{title}</h3>
      <p className="mt-2 text-sm" style={{ color: `${INK}85` }}>{body}</p>
    </div>
  );
}

function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div className="rounded-lg p-6" style={{ border: `1px solid ${LINE}`, background: PANEL }}>
      <div className="ll-disp ll-grad text-4xl font-bold">{n}</div>
      <h3 className="ll-disp mt-3 text-lg font-bold">{title}</h3>
      <p className="mt-1.5 text-sm" style={{ color: `${INK}99` }}>{body}</p>
    </div>
  );
}

function Principle({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <div className="rounded-lg p-5" style={{ border: `1px solid ${LINE}` }}>
      <div className="flex h-9 w-9 items-center justify-center rounded" style={{ background: `${GOLD}1c`, color: GOLD }}>{icon}</div>
      <h3 className="ll-disp mt-3 text-base font-bold">{title}</h3>
      <p className="mt-1 text-xs" style={{ color: `${INK}99` }}>{body}</p>
    </div>
  );
}

function FooterCol({ title, links }: { title: string; links: string[][] }) {
  return (
    <div>
      <div className="ll-mono text-[11px] font-bold uppercase tracking-widest" style={{ color: `${INK}99` }}>{title}</div>
      <ul className="mt-3 space-y-2">
        {links.map((l) => (
          <li key={l[0]}><Link to={l[1]} className="text-sm hover:underline" style={{ color: `${INK}b0` }}>{l[0]}</Link></li>
        ))}
      </ul>
    </div>
  );
}

const SURFACES: { title: string; body: string; icon: ReactNode }[] = [
  { title: "AI Council & Meeting Room", body: "Multi-advisor deliberation over any topic or transcript, with weighted consensus and a chairman's verdict.", icon: <Gavel className="h-5 w-5" /> },
  { title: "Trade Desk", body: "Live candles, forecasts, and a data-grounded signal debate — proposing trades behind the approval gate.", icon: <LineChart className="h-5 w-5" /> },
  { title: "Finance", body: "Capture → classify → reconcile your books. A P&L the CFO suite reasons over.", icon: <Receipt className="h-5 w-5" /> },
  { title: "CRM", body: "Contacts and a deal pipeline; value rolls up to Finance, deals route to the Council.", icon: <Contact className="h-5 w-5" /> },
  { title: "Mail", body: "Inbox triage over your mailbox, with AI classification. Outbound is review-then-send.", icon: <Mail className="h-5 w-5" /> },
  { title: "Studio", body: "Draft, refine, and crystallize artifacts — proposals, briefs, contracts — grounded in your Vault.", icon: <PenLine className="h-5 w-5" /> },
  { title: "Vault", body: "Your real documents, so the agent cites what your contracts and statements actually say.", icon: <Lock className="h-5 w-5" /> },
  { title: "Audit", body: "A tamper-evident, hash-chained log of everything the agent does. Defensible by design.", icon: <ShieldCheck className="h-5 w-5" /> },
];

// FAQ — kept IN SYNC with the FAQPage JSON-LD in web/index.html (static HTML is
// what AI crawlers / answer engines actually read, since they don't run JS).
const FAQS: { q: string; a: string }[] = [
  { q: "What is VIGIL?",
    a: "VIGIL is an AI workspace that deliberates before it acts. It combines a multi-advisor AI council, autonomous AI departments, and a human-in-the-loop crypto trade desk with your finance, CRM, mail, and documents — all under one agent that thinks first and waits for your approval." },
  { q: "How is VIGIL different from a chatbot or AI assistant?",
    a: "Unlike a chatbot, VIGIL is built around human-in-the-loop control: every trade passes a single-use approval gate and outbound mail is review-then-send, so nothing with real consequence happens autonomously. It also brainstorms and presents a plan before acting, and grounds answers in your own documents and live data." },
  { q: "What is the AI council?",
    a: "The AI council is a panel of advisor lenses — CFO, CTO, Legal, and Product — that debate a decision, score it, and have a chairman synthesize a defensible verdict. It surfaces the bear case and dissent instead of hiding it, and you can always override the verdict." },
  { q: "Can VIGIL trade crypto automatically?",
    a: "No. VIGIL proposes trades from data-grounded forecasts, but every order is human-approved and capped at 5% of NAV. You connect your own broker and your API keys never leave your account." },
  { q: "Is my data private and secure?",
    a: "Yes. Every record is scoped to your account with row-level security, your broker and API keys stay in your account, and a tamper-evident, hash-chained audit log records everything the agent does." },
  { q: "What can VIGIL's AI departments do?",
    a: "VIGIL runs autonomous AI departments for recurring work — support triage, finance reconciliation, revenue follow-ups, lead scouting, and legal review. Each department only counts a task as done when it passes a deterministic effectiveness check, so output is verified, not assumed." },
];
