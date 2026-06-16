import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

const A = "#7c5cff";
const B = "#22d3ee";

type Sec = { id: string; title: string; blocks: Block[] };
type Block = { h?: string; p?: string; list?: string[] };

const SECTIONS: Sec[] = [
  {
    id: "getting-started",
    title: "Getting started",
    blocks: [
      { p: "VIGIL × WinnyWoo is one AI agent across two surfaces: the VIGIL workspace (council, meetings, studio, vault, finance, CRM, mail) and the WinnyWoo trading desk. This guide explains what each does and how to begin." },
      { h: "Create your account", p: "Sign up with email, or continue with Google, Apple, GitHub, or Railway. Email signups confirm via a link. Your session is shared across both surfaces — sign in once." },
      { h: "First moves", list: [
        "Convene a council in the Meeting Room over a decision you're weighing.",
        "Open the Trade Desk to see live candles and the signal debate (read-only until you connect a broker).",
        "Add a few transactions in Finance, or a contact in the CRM, to see the agent reason over real data.",
        "Drop a document in the Vault so drafts and answers cite your actual material.",
      ] },
    ],
  },
  {
    id: "surfaces",
    title: "The surfaces",
    blocks: [
      { h: "AI Council & Meeting Room", p: "Convene a panel of advisor lenses (CFO, CTO, Legal, Product) over a topic or meeting transcript. They argue, score each other, and a chairman synthesizes a verdict with a readiness score. Dissent is deliberate — you see the bear case, not just the bull." },
      { h: "Trade Desk", p: "Live OHLCV candles, model forecasts, and a data-grounded signal debate (bull/bear/risk) enriched from multiple market sources. The agent proposes trades; it never sizes or places them on its own." },
      { h: "Finance", p: "A books/ledger: capture a transaction, classify it into a category, reconcile it. A running P&L and by-category rollup the CFO methodology reasons over." },
      { h: "CRM", p: "Contacts and a deal pipeline (lead → qualified → proposal → negotiation → won/lost). Weighted pipeline value rolls up to Finance; deals can route to the Council for review." },
      { h: "Mail", p: "Inbox triage over your mailbox (via the himalaya transport when connected). The agent classifies messages into buckets and priorities. Outbound is review-then-send — drafts are prepared, never auto-dispatched." },
      { h: "Studio", p: "Draft, refine, and crystallize artifacts — proposals, briefs, contracts, memos, reports. It brainstorms the shape first, then drafts only the approach you approve, grounded in your Vault." },
      { h: "Vault", p: "Your real documents. The agent reads and cites them rather than guessing what a contract, invoice, or statement says." },
      { h: "Audit", p: "A tamper-evident, hash-chained log of what the agent and you did — every decision, proposal, and approval, defensible after the fact." },
    ],
  },
  {
    id: "connect-broker",
    title: "Connecting your broker",
    blocks: [
      { p: "WinnyWoo is connect-your-own-broker. You add your exchange API keys from your account dashboard — they're stored against your account and used only to act on your behalf." },
      { list: [
        "Without a broker connected, the desk is fully usable in read-only / markets mode — forecasts, signals, and the debate.",
        "With a broker connected, the agent can propose orders sized against your real NAV — still behind the approval gate.",
        "Keys are never shared between users and never used to act for anyone but you.",
      ] },
    ],
  },
  {
    id: "approval-gate",
    title: "The approval gate",
    blocks: [
      { p: "Every order the agent proposes must pass a single-use human approval before it can execute. This is a hard rule the agent cannot bypass." },
      { list: [
        "Each approval is single-use — it authorizes exactly one order, then is consumed.",
        "Position size is capped at 5% of your NAV by default.",
        "The agent proposes and explains; you approve, modify, or reject. Nothing moves money without you.",
      ] },
    ],
  },
  {
    id: "privacy",
    title: "Privacy & data",
    blocks: [
      { p: "Your data is scoped to you. Every record — transactions, deals, mail, artifacts, documents, broker credentials — is isolated per user and enforced at the database layer." },
      { list: [
        "Row-level security plus an additional gateway-side scope guard on every read and write.",
        "The agent only ever sees the data of the signed-in user it's working for.",
        "You can export or delete your data from your account settings.",
      ] },
    ],
  },
  {
    id: "faq",
    title: "FAQ",
    blocks: [
      { h: "Is this financial advice?", p: "No. VIGIL × WinnyWoo provides information and tooling, not licensed financial, tax, or legal advice. You make the decisions." },
      { h: "Will it trade automatically?", p: "No. The agent proposes trades; a human approval gate stands between any proposal and execution, capped at 5% of NAV." },
      { h: "Where do my broker keys live?", p: "Against your own account, used only to act for you. They are never shared across users." },
      { h: "What if no AI key is configured?", p: "LLM-backed features (Studio drafting, Mail triage, the Council) degrade to a safe deterministic stub rather than failing — the rest of the workspace still works." },
      { h: "Do the advisors always agree?", p: "Deliberately not. The council surfaces dissent and a readiness score, and you can always override the verdict." },
    ],
  },
];

export default function DocsPage() {
  const navigate = useNavigate();
  return (
    <div style={{ background: "#07080d", color: "#e7e9f3", minHeight: "100dvh" }}>
      <style>{`.docsec{scroll-margin-top:88px}`}</style>
      <nav className="sticky top-0 z-20 flex items-center justify-between px-5 py-4 md:px-10" style={{ background: "rgba(7,8,13,.72)", backdropFilter: "blur(10px)", borderBottom: "1px solid #ffffff10" }}>
        <Link to="/" className="flex items-center gap-2 text-sm font-bold tracking-[0.06em]">
          <ArrowLeft className="h-4 w-4 text-white/60" /> <img src="/vigil-mark.svg" alt="" width={22} height={22} /> Docs
        </Link>
        <div className="flex items-center gap-2">
          <Link to="/login" className="rounded-lg px-3 py-2 text-sm text-white/70 hover:text-white">Sign in</Link>
          <button onClick={() => navigate("/signup")} className="rounded-lg px-4 py-2 text-sm font-semibold text-[#07080d]" style={{ background: `linear-gradient(90deg,${A},${B})` }}>Get started</button>
        </div>
      </nav>

      <div className="mx-auto grid max-w-6xl gap-10 px-5 py-12 md:grid-cols-[200px_1fr] md:px-10">
        {/* sidebar */}
        <aside className="hidden md:block">
          <div className="sticky top-24 flex flex-col gap-1 text-sm">
            {SECTIONS.map((s) => (
              <a key={s.id} href={`#${s.id}`} className="rounded-md px-3 py-1.5 text-white/55 hover:bg-white/5 hover:text-white">{s.title}</a>
            ))}
          </div>
        </aside>

        {/* content */}
        <main className="min-w-0">
          <h1 className="text-3xl font-black tracking-tight md:text-4xl">Documentation</h1>
          <p className="mt-3 max-w-2xl text-white/60">Everything you need to understand the workspace, the trading desk, and how the agent stays accountable.</p>

          {SECTIONS.map((s) => (
            <section key={s.id} id={s.id} className="docsec mt-12">
              <h2 className="text-2xl font-bold" style={{ color: B }}>{s.title}</h2>
              <div className="mt-4 flex flex-col gap-4">
                {s.blocks.map((b, i) => (
                  <div key={i}>
                    {b.h && <h3 className="text-base font-semibold text-white/90">{b.h}</h3>}
                    {b.p && <p className="mt-1 text-sm leading-relaxed text-white/65">{b.p}</p>}
                    {b.list && (
                      <ul className="mt-1 flex flex-col gap-1.5 pl-5 text-sm text-white/65" style={{ listStyle: "disc" }}>
                        {b.list.map((li, j) => <li key={j}>{li}</li>)}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            </section>
          ))}

          <div className="mt-16 rounded-2xl p-7 text-center" style={{ background: `linear-gradient(135deg, ${A}1f, ${B}14)`, border: `1px solid ${A}40` }}>
            <h3 className="text-lg font-bold">Ready to start?</h3>
            <button onClick={() => navigate("/signup")} className="mt-4 rounded-xl px-6 py-3 text-sm font-semibold text-[#07080d]" style={{ background: `linear-gradient(90deg,${A},${B})` }}>Create your account</button>
          </div>
        </main>
      </div>
    </div>
  );
}
