import { useEffect, useMemo, useState } from "react";
import {
  createProfile,
  createProgram,
  createSession,
  enrollLearner,
  generateSlots,
  getProfiles,
  listCompanies,
  type Person,
} from "@/lib/learn";
import { expliquerCourt } from "@/lib/refus";
import { nomRole } from "@/lib/mots";

/**
 * Les formulaires de gestion de l'organisme : comptes, programmes, sessions, créneaux,
 * inscriptions. Ils ne décident d'aucun droit : la page ne les affiche que si `_can` l'accorde,
 * et l'API refuse de toute façon ce que la base n'autorise pas.
 */

const champ = "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm";
const bouton = "rounded-md border border-current/30 px-4 py-2 text-sm font-medium hover:bg-current/10 disabled:opacity-40";

function useEnvoi() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; texte: string } | null>(null);
  async function run<R>(fn: () => Promise<R>, ok: string | ((r: R) => string)) {
    setBusy(true);
    setMessage(null);
    try {
      const r = await fn();
      setMessage({ ok: true, texte: typeof ok === "function" ? ok(r) : ok });
      return true;
    } catch (e) {
      setMessage({ ok: false, texte: expliquerCourt(e, "cet enregistrement") });
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { busy, message, run };
}

function Retour({ message }: { message: { ok: boolean; texte: string } | null }) {
  if (!message) return null;
  return <p className={`text-sm ${message.ok ? "opacity-80" : "text-red-500"}`}>{message.texte}</p>;
}

const ROLE_LABEL: Record<string, string> = {
  admin: "Administration",
  formateur: "Formateur",
  entreprise: "Entreprise cliente",
  auditeur: "Auditeur",
  apprenant: "Apprenant",
};

// ── Comptes ──────────────────────────────────────────────────────────────────────────

export function FormulaireCompte({ roles, onCree }: { roles: string[]; onCree: () => void }) {
  const [f, setF] = useState({ full_name: "", email: "", role: roles[0] ?? "", username: "", phone: "", password: "", company_name: "" });
  // `learn_profiles_company_required` impose une société à tout profil « entreprise ».
  // Le formulaire proposait le rôle sans jamais demander la société : la création
  // échouait à tous les coups, sur un « invalid_value » que personne ne pouvait lire.
  const [societes, setSocietes] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    if (f.role !== "entreprise" || societes.length) return;
    void listCompanies().then((r) => setSocietes(r.items)).catch(() => undefined);
  }, [f.role, societes.length]);
  const { busy, message, run } = useEnvoi();
  useEffect(() => {
    if (!f.role && roles[0]) setF((x) => ({ ...x, role: roles[0] }));
  }, [roles, f.role]);
  if (roles.length === 0) return null;
  return (
    <form
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={async (e) => {
        e.preventDefault();
        const ok = await run(
          () =>
            createProfile({
              full_name: f.full_name.trim(),
              email: f.email.trim(),
              role: f.role,
              username: f.username.trim() || null,
              phone: f.phone.trim() || null,
              company_name: f.role === "entreprise" ? f.company_name.trim() || null : null,
              password: f.password || null,
            }),
          (r) =>
            r.password_set
              ? "Compte créé et actif."
              : r.invitation?.envoi === "envoye"
                ? `Invitation envoyée à ${f.email.trim()} (lien valable 72 h).`
                : `Compte créé, mais l'invitation n'est pas partie (${r.invitation?.erreur ?? "raison inconnue"}). Voir « Identité & e-mails ».`,
        );
        if (ok) {
          setF({ full_name: "", email: "", role: roles[0] ?? "", username: "", phone: "", password: "", company_name: "" });
          onCree();
        }
      }}
    >
      <input className={champ} required minLength={2} placeholder="Nom complet" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
      <input className={champ} required type="email" placeholder="Adresse e-mail" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
      <select className={champ} value={nomRole(f.role)} onChange={(e) => setF({ ...f, role: e.target.value })} aria-label="Rôle">
        {roles.map((r) => (
          <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>
        ))}
      </select>
      {f.role === "entreprise" && (
        <>
          <input
            className={champ}
            required
            list="societes-clientes"
            placeholder="Société cliente"
            value={f.company_name}
            onChange={(e) => setF({ ...f, company_name: e.target.value })}
          />
          {/* Choisir une société existante ou en nommer une nouvelle : le serveur
              rattache à celle qui porte ce nom, et ne la crée que si elle manque —
              sans quoi deux collègues finiraient dans deux sociétés homonymes. */}
          <datalist id="societes-clientes">
            {societes.map((s) => <option key={s.id} value={s.name} />)}
          </datalist>
        </>
      )}
      <input className={champ} placeholder="Identifiant court (facultatif)" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
      <input className={champ} placeholder="Téléphone +33… (facultatif)" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
      <input className={champ} type="password" minLength={12} autoComplete="new-password" placeholder="Mot de passe (facultatif : sans mot de passe, la personne reçoit une invitation)" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
      <div className="flex items-center gap-3 sm:col-span-2">
        <button className={bouton} disabled={busy}>{busy ? "Création…" : "Créer le compte"}</button>
        <Retour message={message} />
      </div>
    </form>
  );
}

// ── Programmes ───────────────────────────────────────────────────────────────────────

export function FormulaireProgramme({ onCree }: { onCree: () => void }) {
  const vide = { title: "", code: "", duration_hours: "21", modality: "distanciel", objectives: "", prerequisites: "", published: true };
  const [f, setF] = useState(vide);
  const { busy, message, run } = useEnvoi();
  return (
    <form
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={async (e) => {
        e.preventDefault();
        const ok = await run(
          () =>
            createProgram({
              title: f.title.trim(),
              code: f.code.trim() || null,
              duration_hours: Number(f.duration_hours) || 0,
              modality: f.modality,
              objectives: f.objectives.trim() || null,
              prerequisites: f.prerequisites.trim() || null,
              published: f.published,
            }),
          "Programme créé.",
        );
        if (ok) {
          setF(vide);
          onCree();
        }
      }}
    >
      <input className={champ} required minLength={2} placeholder="Intitulé du programme" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
      <input className={champ} placeholder="Code (ex. DATA360)" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
      <input className={champ} type="number" min={0} step="0.5" placeholder="Durée (heures)" value={f.duration_hours} onChange={(e) => setF({ ...f, duration_hours: e.target.value })} />
      <select className={champ} value={f.modality} onChange={(e) => setF({ ...f, modality: e.target.value })} aria-label="Modalité">
        <option value="distanciel">Distanciel</option>
        <option value="presentiel">Présentiel</option>
        <option value="mixte">Mixte</option>
      </select>
      <textarea className={`${champ} sm:col-span-2`} rows={2} placeholder="Objectifs" value={f.objectives} onChange={(e) => setF({ ...f, objectives: e.target.value })} />
      <textarea className={`${champ} sm:col-span-2`} rows={2} placeholder="Prérequis" value={f.prerequisites} onChange={(e) => setF({ ...f, prerequisites: e.target.value })} />
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <input type="checkbox" checked={f.published} onChange={(e) => setF({ ...f, published: e.target.checked })} /> Publié
      </label>
      <div className="flex items-center gap-3 sm:col-span-2">
        <button className={bouton} disabled={busy}>{busy ? "Création…" : "Créer le programme"}</button>
        <Retour message={message} />
      </div>
    </form>
  );
}

// ── Sessions ─────────────────────────────────────────────────────────────────────────

export function FormulaireSession({ programId, modalite, onCree }: { programId: string; modalite?: string; onCree: () => void }) {
  const vide = { starts_on: "", ends_on: "", code: "", capacity: "12", modality: modalite ?? "distanciel", place: "" };
  const [f, setF] = useState(vide);
  const { busy, message, run } = useEnvoi();
  return (
    <form
      className="grid gap-2 sm:grid-cols-3"
      onSubmit={async (e) => {
        e.preventDefault();
        const ok = await run(
          () =>
            createSession({
              program_id: programId,
              starts_on: f.starts_on,
              ends_on: f.ends_on || f.starts_on,
              code: f.code.trim() || null,
              capacity: Number(f.capacity) || 12,
              modality: f.modality,
              place: f.place.trim() || null,
            }),
          "Session planifiée.",
        );
        if (ok) {
          setF(vide);
          onCree();
        }
      }}
    >
      <label className="text-xs opacity-70">Début<input className={champ} type="date" required value={f.starts_on} onChange={(e) => setF({ ...f, starts_on: e.target.value })} /></label>
      <label className="text-xs opacity-70">Fin<input className={champ} type="date" value={f.ends_on} onChange={(e) => setF({ ...f, ends_on: e.target.value })} /></label>
      <label className="text-xs opacity-70">Places<input className={champ} type="number" min={1} value={f.capacity} onChange={(e) => setF({ ...f, capacity: e.target.value })} /></label>
      <input className={champ} placeholder="Code (facultatif)" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
      <select className={champ} value={f.modality} onChange={(e) => setF({ ...f, modality: e.target.value })} aria-label="Modalité">
        <option value="distanciel">Distanciel</option>
        <option value="presentiel">Présentiel</option>
        <option value="mixte">Mixte</option>
      </select>
      <input className={champ} placeholder="Lieu (facultatif)" value={f.place} onChange={(e) => setF({ ...f, place: e.target.value })} />
      <div className="flex items-center gap-3 sm:col-span-3">
        <button className={bouton} disabled={busy}>{busy ? "Planification…" : "Planifier la session"}</button>
        <Retour message={message} />
      </div>
    </form>
  );
}

// ── Dans une session : créneaux (et formateur), inscriptions ─────────────────────────

function joursEntre(debut: string, fin: string) {
  const out: string[] = [];
  const d = new Date(`${debut}T12:00:00Z`);
  const f = new Date(`${fin}T12:00:00Z`);
  while (d <= f && out.length < 200) {
    out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
}

export function GestionSession({
  sessionId,
  startsOn,
  endsOn,
  onChange,
}: {
  sessionId: string;
  startsOn: string;
  endsOn: string;
  onChange: () => void;
}) {
  const jours = useMemo(() => joursEntre(startsOn, endsOn), [startsOn, endsOn]);
  const [dates, setDates] = useState<string[]>([]);
  const [halves, setHalves] = useState<("am" | "pm")[]>(["am", "pm"]);
  const [formateur, setFormateur] = useState("");
  const [apprenant, setApprenant] = useState("");
  const [formateurs, setFormateurs] = useState<Person[]>([]);
  const [apprenants, setApprenants] = useState<Person[]>([]);
  const creneaux = useEnvoi();
  const inscription = useEnvoi();

  useEffect(() => {
    void getProfiles("formateur").then((r) => setFormateurs(r.items)).catch(() => setFormateurs([]));
    void getProfiles("apprenant").then((r) => setApprenants(r.items)).catch(() => setApprenants([]));
  }, []);

  const libelle = (iso: string) =>
    new Date(`${iso}T12:00:00Z`).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });

  return (
    <div className="space-y-4 rounded-md border border-current/15 p-3">
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide opacity-60">Créneaux et formateur</p>
        <div className="flex flex-wrap gap-2">
          {jours.map((j) => (
            <label key={j} className="flex items-center gap-1 rounded border border-current/15 px-2 py-1 text-xs">
              <input
                type="checkbox"
                checked={dates.includes(j)}
                onChange={(e) => setDates((d) => (e.target.checked ? [...d, j] : d.filter((x) => x !== j)))}
              />
              {libelle(j)}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {(["am", "pm"] as const).map((h) => (
            <label key={h} className="flex items-center gap-1">
              <input
                type="checkbox"
                checked={halves.includes(h)}
                onChange={(e) => setHalves((x) => (e.target.checked ? [...x, h] : x.filter((y) => y !== h)))}
              />
              {h === "am" ? "Matin (9 h – 12 h 30)" : "Après-midi (13 h 30 – 17 h)"}
            </label>
          ))}
          <select className={`${champ} max-w-xs`} value={formateur} onChange={(e) => setFormateur(e.target.value)} aria-label="Formateur">
            <option value="">Formateur…</option>
            {formateurs.map((p) => (
              <option key={p.id} value={p.id}>{p.full_name ?? p.email}</option>
            ))}
          </select>
          <button
            type="button"
            className={bouton}
            disabled={creneaux.busy || dates.length === 0 || halves.length === 0}
            onClick={async () => {
              const ok = await creneaux.run(
                () => generateSlots(sessionId, { dates: [...dates].sort(), halves, formateur_id: formateur || null }),
                `${dates.length * halves.length} créneau(x) créé(s).`,
              );
              if (ok) {
                setDates([]);
                onChange();
              }
            }}
          >
            Générer les créneaux
          </button>
        </div>
        <Retour message={creneaux.message} />
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wide opacity-60">Inscrire un apprenant</p>
        <div className="flex flex-wrap items-center gap-2">
          <select className={`${champ} max-w-sm`} value={apprenant} onChange={(e) => setApprenant(e.target.value)} aria-label="Apprenant">
            <option value="">Apprenant…</option>
            {apprenants.map((p) => (
              <option key={p.id} value={p.id}>{p.full_name ?? p.email}</option>
            ))}
          </select>
          <button
            type="button"
            className={bouton}
            disabled={inscription.busy || !apprenant}
            onClick={async () => {
              const ok = await inscription.run(() => enrollLearner(sessionId, apprenant), "Apprenant inscrit.");
              if (ok) {
                setApprenant("");
                onChange();
              }
            }}
          >
            Inscrire
          </button>
        </div>
        <Retour message={inscription.message} />
      </div>
    </div>
  );
}
