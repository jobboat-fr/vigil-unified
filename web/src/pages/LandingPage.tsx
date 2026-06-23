import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight, Gavel, LineChart, Receipt, Contact, Mail, PenLine, Lock,
  ShieldCheck, Sparkles, BrainCircuit, GitBranch,
} from "lucide-react";
import { ww, type MarketOverview } from "@/lib/ww";
import { useSeo } from "@/lib/seo";

const A = "#7c5cff"; // violet accent
const B = "#22d3ee"; // cyan accent
const POS = "#34d399";
const NEG = "#fb7185";

export default function LandingPage() {
  const navigate = useNavigate();
  const [mkt, setMkt] = useState<MarketOverview | null>(null);
  useSeo({
    title: "VIGIL × WinnyWoo — the AI workspace that thinks before it acts",
    description:
      "An AI workspace that deliberates before acting: a multi-advisor council, a data-grounded crypto desk, and your finance, CRM, mail and document studio — all human-in-the-loop.",
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
    <div style={{ background: "#07080d", color: "#e7e9f3", minHeight: "100dvh" }} className="overflow-x-hidden">
      <style>{`
        @keyframes ll-float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-10px)} }
        @keyframes ll-grad { 0%{background-position:0% 50%} 100%{background-position:200% 50%} }
        @keyframes ll-in { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:none} }
        .ll-in{animation:ll-in .7s ease both}
        .ll-gradtext{background:linear-gradient(90deg,${A},${B},${A});background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:transparent;animation:ll-grad 6s linear infinite}
        .ll-card{transition:transform .2s ease,border-color .2s ease,background .2s ease}
        .ll-card:hover{transform:translateY(-4px);border-color:${A}66;background:#0e1019}
      `}</style>

      {/* NAV */}
      <nav className="sticky top-0 z-20 flex items-center justify-between px-5 py-4 md:px-10" style={{ background: "rgba(7,8,13,.72)", backdropFilter: "blur(10px)", borderBottom: "1px solid #ffffff10" }}>
        <Link to="/" className="flex items-center gap-2.5">
          <img src="/vigil-mark.svg" alt="" width={26} height={26} />
          <span className="text-sm font-bold tracking-[0.06em]">VIGIL <span style={{ opacity: 0.5 }}>×</span> WinnyWoo</span>
        </Link>
        <div className="flex items-center gap-1 md:gap-3">
          <Link to="/docs" className="hidden rounded-lg px-3 py-2 text-sm text-white/70 hover:text-white sm:block">Docs</Link>
          <Link to="/login" className="rounded-lg px-3 py-2 text-sm text-white/70 hover:text-white">Sign in</Link>
          <button onClick={() => navigate("/signup")} className="rounded-lg px-4 py-2 text-sm font-semibold text-[#07080d]" style={{ background: `linear-gradient(90deg,${A},${B})` }}>
            Get started
          </button>
        </div>
      </nav>

      {/* HERO */}
      <header className="relative px-5 pt-16 pb-20 text-center md:px-10 md:pt-24">
        <div aria-hidden className="pointer-events-none absolute inset-0" style={{ background: `radial-gradient(60% 50% at 50% 0%, ${A}22, transparent 70%)` }} />
        <div className="relative mx-auto max-w-4xl">
          <span className="ll-in inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium" style={{ border: `1px solid ${A}55`, color: B }}>
            <Sparkles className="h-3.5 w-3.5" /> One agent. Your council and your trading desk.
          </span>
          <h1 className="ll-in mt-6 text-4xl font-black leading-[1.05] tracking-tight md:text-6xl" style={{ animationDelay: ".05s" }}>
            Decisions you can <span className="ll-gradtext">defend</span>.<br />Trades you have to <span className="ll-gradtext">approve</span>.
          </h1>
          <p className="ll-in mx-auto mt-6 max-w-2xl text-base text-white/65 md:text-lg" style={{ animationDelay: ".12s" }}>
            VIGIL × WinnyWoo is an AI workspace that thinks before it acts — a multi-advisor council, a data-grounded crypto desk, and your finance, CRM, mail and document studio, all under one human-in-the-loop agent.
          </p>
          <div className="ll-in mt-9 flex flex-wrap items-center justify-center gap-3" style={{ animationDelay: ".18s" }}>
            <button onClick={() => navigate("/signup")} className="inline-flex items-center gap-2 rounded-xl px-6 py-3 text-sm font-semibold text-[#07080d]" style={{ background: `linear-gradient(90deg,${A},${B})` }}>
              Get started <ArrowRight className="h-4 w-4" />
            </button>
            <Link to="/docs" className="rounded-xl px-6 py-3 text-sm font-semibold text-white/80" style={{ border: "1px solid #ffffff22" }}>Read the docs</Link>
          </div>

          {/* LIVE market pulse */}
          <div className="ll-in mx-auto mt-12 max-w-3xl" style={{ animationDelay: ".24s" }}>
            <div className="mb-2 flex items-center justify-center gap-2 text-[11px] uppercase tracking-widest text-white/40">
              <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: POS, boxShadow: `0 0 8px ${POS}` }} />
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
          <Pillar icon={<BrainCircuit />} kicker="VIGIL" title="A workspace that deliberates" body="Convene an AI council over any decision — CFO, CTO, Legal, Product lenses argue, score, and a chairman synthesizes a verdict. Run meetings, crystallize artifacts, ground everything in your own documents." />
          <Pillar icon={<LineChart />} kicker="WinnyWoo" title="A desk that never trades alone" body="Forecasts and a data-grounded signal debate propose trades — every order passes a single-use human approval gate, capped at 5% of NAV. Connect your own broker; keys never leave your account." />
        </div>
      </section>

      {/* SURFACES */}
      <section className="px-5 py-12 md:px-10">
        <div className="mx-auto max-w-6xl">
          <h2 className="text-center text-2xl font-bold md:text-3xl">Everything in one workspace</h2>
          <p className="mx-auto mt-3 max-w-xl text-center text-sm text-white/55">Each surface is a real tool the agent can read, reason over, and act in — never autonomously where money or messages are involved.</p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {SURFACES.map((s) => (
              <div key={s.title} className="ll-card rounded-2xl p-5" style={{ border: "1px solid #ffffff14", background: "#0b0d15" }}>
                <div className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: `${A}1c`, color: B }}>{s.icon}</div>
                <h3 className="mt-4 text-base font-semibold">{s.title}</h3>
                <p className="mt-1.5 text-sm text-white/55">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section className="px-5 py-16 md:px-10">
        <div className="mx-auto max-w-5xl">
          <h2 className="text-center text-2xl font-bold md:text-3xl">How the agent works</h2>
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

      {/* CTA */}
      <section className="px-5 py-20 md:px-10">
        <div className="mx-auto max-w-3xl rounded-3xl p-10 text-center" style={{ background: `linear-gradient(135deg, ${A}22, ${B}18)`, border: `1px solid ${A}44` }}>
          <h2 className="text-2xl font-bold md:text-3xl">Bring your judgment. We'll bring the rigor.</h2>
          <p className="mx-auto mt-3 max-w-lg text-sm text-white/65">Create an account and convene your first council, or wire up your trading desk in minutes.</p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <button onClick={() => navigate("/signup")} className="inline-flex items-center gap-2 rounded-xl px-6 py-3 text-sm font-semibold text-[#07080d]" style={{ background: `linear-gradient(90deg,${A},${B})` }}>
              Get started <ArrowRight className="h-4 w-4" />
            </button>
            <Link to="/login" className="rounded-xl px-6 py-3 text-sm font-semibold text-white/80" style={{ border: "1px solid #ffffff22" }}>Sign in</Link>
          </div>
        </div>
      </section>

      {/* FOOTER */}
      <footer className="px-5 py-10 md:px-10" style={{ borderTop: "1px solid #ffffff10" }}>
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 text-sm text-white/45 sm:flex-row">
          <div className="flex items-center gap-2">
            <img src="/vigil-mark.svg" alt="" width={20} height={20} />
            <span>VIGIL × WinnyWoo</span>
          </div>
          <div className="flex gap-5">
            <Link to="/docs" className="hover:text-white">Docs</Link>
            <Link to="/login" className="hover:text-white">Sign in</Link>
            <Link to="/signup" className="hover:text-white">Get started</Link>
          </div>
          <span className="text-xs text-white/35">Not financial, tax, or legal advice.</span>
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
    <div className="rounded-xl px-3 py-2.5 text-left" style={{ background: "#0d0f18", border: "1px solid #ffffff12" }}>
      <div className="text-[10px] uppercase tracking-wider text-white/40">{label}</div>
      <div className="text-base font-bold tabular-nums">{value}</div>
      {c != null && <div className="text-xs tabular-nums" style={{ color: c >= 0 ? POS : NEG }}>{c >= 0 ? "▲" : "▼"} {Math.abs(c).toFixed(2)}%</div>}
      {sub && <div className="text-[10px] text-white/45">{sub}</div>}
    </div>
  );
}

function Pillar({ icon, kicker, title, body }: { icon: ReactNode; kicker: string; title: string; body: string }) {
  return (
    <div className="ll-card rounded-2xl p-7" style={{ border: "1px solid #ffffff14", background: "#0b0d15" }}>
      <div className="flex h-11 w-11 items-center justify-center rounded-xl" style={{ background: `${B}18`, color: B }}>{icon}</div>
      <div className="mt-4 text-[11px] font-bold uppercase tracking-widest" style={{ color: A }}>{kicker}</div>
      <h3 className="mt-1 text-xl font-bold">{title}</h3>
      <p className="mt-2 text-sm text-white/60">{body}</p>
    </div>
  );
}

function Step({ n, title, body }: { n: string; title: string; body: string }) {
  return (
    <div className="rounded-2xl p-6" style={{ border: "1px solid #ffffff14", background: "#0b0d15" }}>
      <div className="text-3xl font-black ll-gradtext">{n}</div>
      <h3 className="mt-3 text-lg font-semibold">{title}</h3>
      <p className="mt-1.5 text-sm text-white/55">{body}</p>
    </div>
  );
}

function Principle({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <div className="rounded-2xl p-5" style={{ border: "1px solid #ffffff14" }}>
      <div className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ background: `${A}1c`, color: B }}>{icon}</div>
      <h3 className="mt-3 text-sm font-semibold">{title}</h3>
      <p className="mt-1 text-xs text-white/50">{body}</p>
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
