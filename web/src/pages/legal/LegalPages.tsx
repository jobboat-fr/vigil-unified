import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useSeo } from "@/lib/seo";

/**
 * Compliance pages — Terms, Privacy (GDPR), Risk disclaimer, Cookies, Mentions
 * légales. Public (linked from the landing footer + required by app stores:
 * Google Play mandates a reachable privacy-policy URL). Prerendered to static
 * HTML like / and /docs so crawlers and store reviewers see full content
 * without JS. Operator identity is centralised in OPERATOR below.
 */
export const OPERATOR = {
  brand: "VIGIL",
  legalName: "AZZ&CO LABS", // SAS — Kbis à jour au 07/02/2026 (greffe de Versailles)
  form: "Société par actions simplifiée (SAS) au capital de 200,00 €",
  rcs: "100 667 021 R.C.S. Versailles",
  euid: "FR7803.100667021",
  address: "Bâtiment Fougères, Rue de Guyenne, 78840 Freneuse, France",
  publisher: "Azer Rached (Président)",
  country: "France",
  contact: "legal@vigil-ai.xyz",
  dpo: "privacy@vigil-ai.xyz",
  site: "https://vigil-ai.xyz",
  lastUpdated: "8 July 2026",
};

const INK = "#0b2239";
const BG = "#f4f7fb";
const LINE = "#0b223922";

function LegalLayout({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-h-dvh" style={{ background: BG, color: INK }}>
      <header className="mx-auto flex max-w-3xl items-center justify-between px-5 py-6">
        <Link to="/" className="text-sm font-bold uppercase tracking-widest" style={{ color: INK }}>
          ← {OPERATOR.brand}
        </Link>
        <nav className="flex gap-4 text-xs uppercase tracking-wider" style={{ color: `${INK}99` }}>
          <Link to="/legal/terms">Terms</Link>
          <Link to="/legal/privacy">Privacy</Link>
          <Link to="/legal/disclaimer">Risk</Link>
        </nav>
      </header>
      <main className="mx-auto max-w-3xl px-5 pb-20">
        <h1 className="mb-2 text-3xl font-bold">{title}</h1>
        <p className="mb-8 text-xs" style={{ color: `${INK}77` }}>
          Last updated: {OPERATOR.lastUpdated} · Operator: {OPERATOR.legalName}, {OPERATOR.country} ·{" "}
          <a href={`mailto:${OPERATOR.contact}`} className="underline">{OPERATOR.contact}</a>
        </p>
        <div className="legal-body space-y-6 text-sm leading-relaxed" style={{ color: `${INK}dd` }}>
          {children}
        </div>
        <style>{`.legal-body h2{font-size:1.15rem;font-weight:700;margin-top:2rem;color:${INK}} .legal-body ul{list-style:disc;padding-left:1.25rem;display:flex;flex-direction:column;gap:.35rem} .legal-body a{text-decoration:underline}`}</style>
      </main>
      <footer className="mx-auto max-w-3xl px-5 pb-10 text-xs" style={{ color: `${INK}66`, borderTop: `1px solid ${LINE}` }}>
        <p className="pt-4">
          © {new Date().getFullYear()} {OPERATOR.legalName} · <Link to="/legal/terms">Terms</Link> ·{" "}
          <Link to="/legal/privacy">Privacy</Link> · <Link to="/legal/disclaimer">Risk disclaimer</Link> ·{" "}
          <Link to="/legal/cookies">Cookies</Link> · <Link to="/legal/mentions">Mentions légales</Link>
        </p>
      </footer>
    </div>
  );
}

export function TermsPage() {
  useSeo({
    title: "Terms of Service — VIGIL",
    description: "The terms governing your use of VIGIL: subscriptions, AI outputs, the human-in-the-loop trade desk, acceptable use, and liability.",
    path: "/legal/terms",
  });
  return (
    <LegalLayout title="Terms of Service">
      <h2>1. The service</h2>
      <p>
        {OPERATOR.brand} is a software-as-a-service workspace operated by {OPERATOR.legalName} that provides
        AI-assisted business tooling: autonomous AI departments with verified task checks, an AI council and
        meeting room, document vault, CRM/finance/mail surfaces, and a human-in-the-loop cryptocurrency trade
        desk that connects to <em>your own</em> exchange account. By creating an account you accept these terms.
      </p>
      <h2>2. Accounts</h2>
      <ul>
        <li>You must provide accurate information and keep your credentials secure. You are responsible for activity under your account.</li>
        <li>You must be at least 18 and legally able to contract. Business use requires authority to bind your organisation.</li>
      </ul>
      <h2>3. Subscriptions, billing & withdrawal</h2>
      <ul>
        <li>Paid plans (Starter, Pro, Team) bill monthly in EUR via Stripe. Prices are shown before checkout; VAT is handled at checkout.</li>
        <li>You can cancel anytime from the Billing page — the plan stays active until the end of the paid period. No partial-month refunds.</li>
        <li>EU consumers: by requesting immediate access to the digital service you consent to performance beginning at once and acknowledge the 14-day withdrawal right is waived once performance has begun (art. L221-28 C. consom.). Withdrawal before first use: write to {OPERATOR.contact}.</li>
        <li>We may change prices with 30 days' notice; changes apply from your next billing cycle.</li>
      </ul>
      <h2>4. AI outputs</h2>
      <ul>
        <li>Outputs are generated by machine-learning models and may be inaccurate, incomplete, or outdated. Review them before acting or publishing.</li>
        <li>Outputs are not professional advice of any kind (see the <Link to="/legal/disclaimer">Risk disclaimer</Link>).</li>
        <li>As between you and us, you own the outputs generated from your inputs, to the extent permitted by law.</li>
      </ul>
      <h2>5. Trade desk — human-in-the-loop only</h2>
      <ul>
        <li>The trade desk is an <strong>execution and analysis tool</strong>. It never trades autonomously: every order requires your explicit, per-order approval through the verification gate.</li>
        <li>You connect your own exchange API keys, scoped by you. We are never custodian of your funds and cannot withdraw them.</li>
        <li>Signals, forecasts, debates and analyst content are informational software output — <strong>not investment advice, not a recommendation, not a solicitation</strong>. See the <Link to="/legal/disclaimer">Risk disclaimer</Link>.</li>
        <li>You are solely responsible for trading decisions, exchange fees, taxes and losses. Cryptoasset markets are highly volatile; you can lose everything you commit.</li>
      </ul>
      <h2>6. Acceptable use</h2>
      <ul>
        <li>No unlawful, infringing, or abusive use; no attempts to breach security or others' tenancy; no market manipulation or activity that violates your exchange's terms; no scraping or reselling of the service.</li>
      </ul>
      <h2>7. Availability & changes</h2>
      <p>
        The service is provided "as available". We aim for high availability but do not guarantee uninterrupted
        operation, and we may modify or discontinue features with reasonable notice where a change is material.
      </p>
      <h2>8. Liability</h2>
      <p>
        To the maximum extent permitted by law, {OPERATOR.legalName} is not liable for indirect damages, lost
        profits, or trading losses, and our total liability is capped at the fees you paid in the 12 months before
        the claim. Nothing limits liability for gross negligence, wilful misconduct, or where the law forbids limitation.
      </p>
      <h2>9. Termination</h2>
      <p>
        You may delete your account at any time (GDPR erasure honoured — see <Link to="/legal/privacy">Privacy</Link>).
        We may suspend or terminate accounts that violate these terms, with notice where practicable.
      </p>
      <h2>10. Law & venue</h2>
      <p>French law governs. Mandatory consumer protections of your country of residence remain unaffected. Venue: the competent courts of {OPERATOR.country}.</p>
    </LegalLayout>
  );
}

export function PrivacyPage() {
  useSeo({
    title: "Privacy Policy — VIGIL",
    description: "How VIGIL processes personal data under the GDPR: what we collect, why, where it lives, our processors, retention, and your rights.",
    path: "/legal/privacy",
  });
  return (
    <LegalLayout title="Privacy Policy">
      <h2>1. Controller</h2>
      <p>
        {OPERATOR.legalName} ({OPERATOR.country}) is the data controller for {OPERATOR.site}. Contact:{" "}
        <a href={`mailto:${OPERATOR.dpo}`}>{OPERATOR.dpo}</a>.
      </p>
      <h2>2. What we process, and why</h2>
      <ul>
        <li><strong>Account data</strong> (email, name, hashed credentials) — to provide the service. Legal basis: contract.</li>
        <li><strong>Workspace content</strong> (documents you upload to the vault, CRM/mail/finance records you connect, meeting transcripts you create) — to provide the features you invoke. Basis: contract.</li>
        <li><strong>Broker API keys</strong> — encrypted at rest (Fernet) and used only to execute the actions you approve. Basis: contract. We never hold your funds.</li>
        <li><strong>Billing data</strong> — handled by Stripe; we store your subscription tier and Stripe customer/subscription identifiers, never card numbers. Basis: contract & legal obligation.</li>
        <li><strong>Usage & security logs</strong> (IP, timestamps, actions) — to secure and improve the service. Basis: legitimate interest.</li>
        <li><strong>AI processing</strong> — your prompts and relevant workspace context are sent to model providers to generate responses. We do not use your content to train models.</li>
      </ul>
      <h2>3. Processors & transfers</h2>
      <ul>
        <li>Supabase (database & authentication), Vercel (web hosting), Railway (API hosting), OVHcloud (EU — AI runtime), Stripe (payments), Hugging Face & model providers (AI inference), LiveKit (real-time meetings), ElevenLabs (voice synthesis, when used).</li>
        <li>Where a processor is outside the EEA, transfers rely on adequacy decisions or Standard Contractual Clauses.</li>
      </ul>
      <h2>4. Retention</h2>
      <ul>
        <li>Account & workspace data: for the life of the account, deleted or anonymised within 30 days of account deletion.</li>
        <li>Billing records: as required by French commercial and tax law (up to 10 years).</li>
        <li>Security logs: up to 12 months.</li>
      </ul>
      <h2>5. Your rights</h2>
      <p>
        Under the GDPR you may access, rectify, erase, restrict, object, and port your data, and withdraw consent
        where processing rests on consent. Use the in-app privacy tools (data export & deletion request) or write
        to <a href={`mailto:${OPERATOR.dpo}`}>{OPERATOR.dpo}</a>. You may lodge a complaint with the CNIL (cnil.fr).
      </p>
      <h2>6. Security</h2>
      <p>
        TLS everywhere, row-level tenant isolation in the database plus route-layer scoping, encrypted secrets,
        owner-gated outbound actions, and per-order approval for anything that moves money.
      </p>
      <h2>7. Mobile app</h2>
      <p>
        The VIGIL mobile app is a shell around this same service and processes the same data — no additional
        device permissions, no advertising identifiers, no third-party ad SDKs, no sale of personal data.
      </p>
    </LegalLayout>
  );
}

export function DisclaimerPage() {
  useSeo({
    title: "Risk & AI Disclaimer — VIGIL",
    description: "VIGIL is software, not an adviser: no investment, legal, tax, or accounting advice; AI outputs can be wrong; crypto trading risks apply.",
    path: "/legal/disclaimer",
  });
  return (
    <LegalLayout title="Risk & AI Disclaimer">
      <h2>Not investment advice</h2>
      <p>
        Nothing in {OPERATOR.brand} — signals, forecasts, analyst debates, council verdicts, chat responses, or any
        other output — constitutes investment advice, a personal recommendation, or a solicitation to buy or sell
        any financial instrument or cryptoasset. {OPERATOR.legalName} is <strong>not</strong> an investment firm,
        broker, portfolio manager, or financial adviser, and is not licensed or registered with the AMF, SEC, or
        any other financial regulator.
      </p>
      <h2>Cryptoassets are high-risk</h2>
      <ul>
        <li>Prices are extremely volatile; you can lose your entire investment.</li>
        <li>Past performance and model forecasts do not predict future results.</li>
        <li>You trade on your own exchange account, at your own initiative, with per-order approval — every decision and its consequences are yours.</li>
      </ul>
      <h2>AI outputs can be wrong</h2>
      <p>
        Outputs are produced by statistical models. They can be inaccurate, incomplete, outdated, or misleading —
        including when they sound confident. Verify anything that matters, especially legal, financial, medical,
        and tax questions, with a qualified professional.
      </p>
      <h2>No professional-client relationship</h2>
      <p>
        Using {OPERATOR.brand} creates no adviser-client, attorney-client, accountant-client, or fiduciary
        relationship. Department outputs (legal review, finance reports, and similar) are software-generated
        working documents for your own review, not professional deliverables.
      </p>
    </LegalLayout>
  );
}

export function CookiesPage() {
  useSeo({
    title: "Cookie Policy — VIGIL",
    description: "VIGIL uses only strictly-necessary storage: authentication session tokens. No advertising trackers, no third-party analytics cookies.",
    path: "/legal/cookies",
  });
  return (
    <LegalLayout title="Cookie Policy">
      <h2>What we store</h2>
      <ul>
        <li><strong>Authentication session</strong> (Supabase token in localStorage / secure cookies) — strictly necessary to keep you signed in. Lifetime: your session.</li>
        <li><strong>Interface preferences</strong> (theme, sidebar state, onboarding progress) — strictly necessary local storage, never sent to third parties.</li>
      </ul>
      <h2>What we do NOT use</h2>
      <ul>
        <li>No advertising or cross-site tracking cookies.</li>
        <li>No third-party analytics cookies.</li>
        <li>No fingerprinting.</li>
      </ul>
      <p>
        Because only strictly-necessary storage is used, no consent banner is required under the ePrivacy
        directive and CNIL guidance. If we ever add analytics or marketing cookies, we will ask for consent first
        and update this page.
      </p>
    </LegalLayout>
  );
}

export function MentionsPage() {
  useSeo({
    title: "Mentions légales — VIGIL",
    description: "Informations légales de l'éditeur du site vigil-ai.xyz : identification, hébergement, contact, propriété intellectuelle.",
    path: "/legal/mentions",
  });
  return (
    <LegalLayout title="Mentions légales">
      <h2>Éditeur</h2>
      <ul>
        <li>Dénomination : <strong>{OPERATOR.legalName}</strong> (sigle AZ LABS)</li>
        <li>Forme : {OPERATOR.form}</li>
        <li>Immatriculation : {OPERATOR.rcs} — EUID {OPERATOR.euid}</li>
        <li>Siège social : {OPERATOR.address}</li>
        <li>Directeur de la publication : {OPERATOR.publisher}</li>
        <li>Contact : <a href={`mailto:${OPERATOR.contact}`}>{OPERATOR.contact}</a></li>
      </ul>
      <h2>Hébergement</h2>
      <ul>
        <li>Site web : Vercel Inc., 440 N Barranca Ave #4133, Covina, CA 91723, USA — vercel.com</li>
        <li>API : Railway Corp., USA — railway.com</li>
        <li>Traitement IA : OVHcloud, 2 rue Kellermann, 59100 Roubaix, France — ovhcloud.com</li>
        <li>Base de données & authentification : Supabase Inc. — supabase.com</li>
      </ul>
      <h2>Propriété intellectuelle</h2>
      <p>
        La structure du site, les marques, logos et contenus originaux sont la propriété de {OPERATOR.legalName} ou
        de ses concédants. Toute reproduction non autorisée est interdite.
      </p>
      <h2>Données personnelles</h2>
      <p>
        Voir la <Link to="/legal/privacy">politique de confidentialité</Link>. Réclamations : CNIL, 3 place de
        Fontenoy, 75007 Paris — cnil.fr.
      </p>
      <h2>Signalement</h2>
      <p>
        Pour signaler un contenu illicite ou un abus : <a href={`mailto:${OPERATOR.contact}`}>{OPERATOR.contact}</a>.
      </p>
    </LegalLayout>
  );
}
