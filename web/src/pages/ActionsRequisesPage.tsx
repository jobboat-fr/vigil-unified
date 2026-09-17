import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import {
  creerActionRequise,
  getActionsRequises,
  getPolitique,
  majActionRequise,
  messageAccueil,
  setPolitique,
  type ActionAdmin,
  type Politique,
} from "@/lib/accueil";
import { getProfiles, getSessions, type Person, type Session } from "@/lib/learn";

const champ = "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm";
const bouton = "rounded-md border border-current/30 px-3 py-1.5 text-sm font-medium hover:bg-current/10 disabled:opacity-40";

const TYPES: Record<string, string> = {
  activer_compte: "Activer son compte",
  signer_document: "Signer un document",
  completer_profil: "Compléter son profil",
  positionnement: "Test de positionnement",
  emarger: "Émarger",
  questionnaire: "Questionnaire",
  deposer_piece: "Déposer une pièce",
  autre: "Autre",
};
const AJOUTABLES = ["completer_profil", "positionnement", "emarger", "questionnaire", "deposer_piece", "autre"];
const ROLES: Record<string, string> = { apprenant: "Apprenants", formateur: "Formateurs", entreprise: "Entreprises", admin: "Administration" };

const dateCourte = (s: string) => new Date(s).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" });

/**
 * Ce que chacun doit faire, pour tous les rôles. Les actions système (activer, signer) sont
 * ouvertes et fermées par la plateforme ; l'administration ajoute les siennes à une personne,
 * à un rôle ou aux inscrits d'une session. Rappels et alerte suivent le rythme réglé ici.
 */
export default function ActionsRequisesPage() {
  const [items, setItems] = useState<ActionAdmin[]>([]);
  const [filtre, setFiltre] = useState<{ statut: string; retard: boolean }>({ statut: "a_faire", retard: false });
  const [pol, setPol] = useState<Politique | null>(null);
  const [personnes, setPersonnes] = useState<Person[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [cible, setCible] = useState<"personne" | "role" | "session">("personne");
  const dans7 = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10);
  const [f, setF] = useState({ kind: "autre", title: "", detail: "", link_path: "", due_on: dans7, assignee_id: "", role: "apprenant", session_id: "" });
  const [msg, setMsg] = useState<{ ok: boolean; texte: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    try {
      const r = await getActionsRequises(filtre.statut, filtre.retard);
      setItems(r.items);
    } catch (e) {
      setMsg({ ok: false, texte: messageAccueil(e) });
    }
  }, [filtre]);
  useEffect(() => void charger(), [charger]);
  useEffect(() => {
    getPolitique().then(setPol).catch(() => undefined);
    getProfiles().then((r) => setPersonnes(r.items)).catch(() => undefined);
    getSessions().then((r) => setSessions((r as { items: Session[] }).items ?? [])).catch(() => undefined);
  }, []);

  const agir = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, texte: ok });
      await charger();
      return true;
    } catch (e) {
      setMsg({ ok: false, texte: messageAccueil(e) });
      return false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {msg && <p className={`text-sm ${msg.ok ? "opacity-80" : "text-red-500"}`}>{msg.texte}</p>}

      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
          <CardTitle>Actions requises</CardTitle>
          <div className="flex items-center gap-3 text-sm">
            <select className="rounded-md border border-current/20 bg-transparent px-2 py-1" value={filtre.statut} onChange={(e) => setFiltre({ ...filtre, statut: e.target.value })}>
              <option value="a_faire">À faire</option>
              <option value="fait">Faites</option>
              <option value="annule">Annulées</option>
              <option value="tous">Toutes</option>
            </select>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={filtre.retard} onChange={(e) => setFiltre({ ...filtre, retard: e.target.checked })} />
              En retard
            </label>
          </div>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          {items.length === 0 ? (
            <p className="text-text-secondary px-4 pb-4 text-sm">Aucune action.</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs opacity-60">
                  <th className="px-4 py-2">Personne</th>
                  <th className="px-2">Action</th>
                  <th className="px-2">Échéance</th>
                  <th className="px-2">Relances</th>
                  <th className="px-2" />
                </tr>
              </thead>
              <tbody>
                {items.map((a) => {
                  const retard = a.status === "a_faire" && new Date(a.due_at) < new Date();
                  const systeme = a.kind === "activer_compte" || a.kind === "signer_document";
                  return (
                    <tr key={a.id} className="border-t border-current/10 align-top">
                      <td className="px-4 py-2">
                        {a.full_name}
                        <div className="text-text-secondary text-xs">{a.email}</div>
                      </td>
                      <td className="px-2 py-2">
                        {a.title}
                        <div className="text-text-secondary text-xs">{TYPES[a.kind] ?? a.kind}{systeme ? " · automatique" : ""}</div>
                      </td>
                      <td className={`whitespace-nowrap px-2 py-2 ${retard ? "text-amber-500" : ""}`}>{dateCourte(a.due_at)}</td>
                      <td className="px-2 py-2 text-xs">
                        {a.rappels} rappel{a.rappels > 1 ? "s" : ""}
                        {a.alerte_envoyee ? " · alerte envoyée" : ""}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2">
                        {a.status === "a_faire" && !systeme && (
                          <button className={bouton} disabled={busy} onClick={() => void agir(() => majActionRequise(a.id, "fait"), "Action marquée faite.")}>
                            Faite
                          </button>
                        )}{" "}
                        {a.status === "a_faire" && (
                          <button
                            className={bouton}
                            disabled={busy}
                            onClick={() => {
                              const motif = window.prompt("Motif de l'annulation ?");
                              if (motif?.trim()) void agir(() => majActionRequise(a.id, "annule", motif.trim()), "Action annulée.");
                            }}
                          >
                            Annuler
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ajouter une action</CardTitle>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-3 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              void agir(
                () =>
                  creerActionRequise({
                    kind: f.kind,
                    title: f.title.trim(),
                    detail: f.detail.trim() || null,
                    link_path: f.link_path.trim() || null,
                    due_on: f.due_on,
                    ...(cible === "personne" ? { assignee_id: f.assignee_id } : cible === "role" ? { role: f.role } : { session_id: f.session_id }),
                  }),
                "Action ajoutée : la personne est prévenue au prochain passage des relances.",
              ).then((ok) => ok && setF({ ...f, title: "", detail: "", link_path: "" }));
            }}
          >
            <select className={champ} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              {AJOUTABLES.map((k) => (
                <option key={k} value={k}>
                  {TYPES[k]}
                </option>
              ))}
            </select>
            <input className={champ} required minLength={3} placeholder="Intitulé (ce que la personne lira)" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
            <input className={champ} placeholder="Précision (facultatif)" value={f.detail} onChange={(e) => setF({ ...f, detail: e.target.value })} />
            <input className={champ} placeholder="Page de l'application (ex. /learn/coffre)" value={f.link_path} onChange={(e) => setF({ ...f, link_path: e.target.value })} />
            <label className="text-sm">
              Échéance
              <input type="date" className={champ} required value={f.due_on} onChange={(e) => setF({ ...f, due_on: e.target.value })} />
            </label>
            <div className="flex flex-col gap-2 text-sm">
              <div className="flex gap-3">
                {(["personne", "role", "session"] as const).map((c) => (
                  <label key={c} className="flex items-center gap-1">
                    <input type="radio" checked={cible === c} onChange={() => setCible(c)} />
                    {c === "personne" ? "Une personne" : c === "role" ? "Un rôle" : "Une session"}
                  </label>
                ))}
              </div>
              {cible === "personne" && (
                <select className={champ} required value={f.assignee_id} onChange={(e) => setF({ ...f, assignee_id: e.target.value })}>
                  <option value="">Choisir…</option>
                  {personnes.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.full_name} ({p.role})
                    </option>
                  ))}
                </select>
              )}
              {cible === "role" && (
                <select className={champ} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
                  {Object.entries(ROLES).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              )}
              {cible === "session" && (
                <select className={champ} required value={f.session_id} onChange={(e) => setF({ ...f, session_id: e.target.value })}>
                  <option value="">Choisir…</option>
                  {sessions.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.title ?? s.code}
                    </option>
                  ))}
                </select>
              )}
            </div>
            <div className="sm:col-span-2">
              <button className={bouton} disabled={busy}>
                Ajouter
              </button>
            </div>
          </form>
        </CardContent>
      </Card>

      {pol && (
        <Card>
          <CardHeader>
            <CardTitle>Rythme des relances</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-end gap-3 text-sm">
            <label>
              Rappels aux jours (séparés par des virgules)
              <input
                className={champ}
                value={pol.reminder_days.join(", ")}
                onChange={(e) =>
                  setPol({ ...pol, reminder_days: e.target.value.split(",").map((x) => parseInt(x.trim(), 10)).filter((x) => !Number.isNaN(x)) })
                }
              />
            </label>
            <label>
              Alerte à l'administration au jour
              <input type="number" min={1} max={60} className={champ} value={pol.admin_alert_day} onChange={(e) => setPol({ ...pol, admin_alert_day: Number(e.target.value) })} />
            </label>
            <label className="flex items-center gap-1">
              <input type="checkbox" checked={pol.active} onChange={(e) => setPol({ ...pol, active: e.target.checked })} />
              Relances actives
            </label>
            <button className={bouton} disabled={busy} onClick={() => void agir(() => setPolitique(pol), "Rythme enregistré.")}>
              Enregistrer
            </button>
            <p className="text-text-secondary w-full text-xs">
              Jours comptés depuis la création de l'action (J0 = le jour même). Une action faite ou annulée ne reçoit plus rien.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
