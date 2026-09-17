import { useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import {
  creerDocumentASigner,
  envoyerInvitation,
  getDocumentsASigner,
  getSuiviSignatures,
  messageAccueil,
  modifierDocumentASigner,
  type LigneSuivi,
  type ModeleDocument,
} from "@/lib/accueil";

const champ = "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm";
const bouton = "rounded-md border border-current/30 px-3 py-1.5 text-sm font-medium hover:bg-current/10 disabled:opacity-40";

const TYPES: Record<string, string> = {
  contrat: "Contrat de formation",
  convention: "Convention de formation",
  reglement_interieur: "Règlement intérieur",
  programme: "Programme",
  convocation: "Convocation",
  devis: "Devis",
  attestation: "Attestation",
  certificat: "Certificat",
  feuille_emargement: "Feuille d'émargement",
  facture: "Facture",
};
const ROLES: Record<string, string> = { apprenant: "Apprenant", formateur: "Formateur", entreprise: "Entreprise" };

const vide = { code: "", kind: "reglement_interieur", title: "", body_html: "", required_for: ["apprenant"] };

/**
 * Les documents qu'une personne doit signer avant d'accéder à son espace, et le suivi.
 * VTLVS n'impose aucun contenu : l'organisme écrit ses documents. Modifier le texte crée une
 * nouvelle version, que chacun doit signer à nouveau ; les signatures précédentes restent des
 * preuves.
 */
export default function DocumentsASignerPage() {
  const [docs, setDocs] = useState<ModeleDocument[]>([]);
  const [suivi, setSuivi] = useState<LigneSuivi[]>([]);
  const [f, setF] = useState(vide);
  const [edition, setEdition] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; texte: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    try {
      const [d, s] = await Promise.all([getDocumentsASigner(), getSuiviSignatures()]);
      setDocs(d.items);
      setSuivi(s.items);
    } catch (e) {
      setMsg({ ok: false, texte: messageAccueil(e) });
    }
  }, []);
  useEffect(() => void charger(), [charger]);

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

  const manquants = useMemo(() => suivi.filter((l) => !l.signed_at), [suivi]);
  const parPersonne = useMemo(() => {
    const m = new Map<string, { nom: string; email: string; role: string; actif: boolean; docs: string[] }>();
    for (const l of manquants) {
      const x = m.get(l.profile_id) ?? { nom: l.full_name, email: l.email, role: l.role, actif: Boolean(l.activated_at), docs: [] };
      x.docs.push(l.title);
      m.set(l.profile_id, x);
    }
    return [...m.entries()];
  }, [manquants]);

  const enregistrer = async (e: React.FormEvent) => {
    e.preventDefault();
    const ok = edition
      ? await agir(
          () => modifierDocumentASigner(edition, { title: f.title, body_html: f.body_html, required_for: f.required_for }),
          "Document mis à jour.",
        )
      : await agir(() => creerDocumentASigner(f), "Document créé : les personnes concernées doivent le signer.");
    if (ok) {
      setF(vide);
      setEdition(null);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {msg && <p className={`text-sm ${msg.ok ? "opacity-80" : "text-red-500"}`}>{msg.texte}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Documents à signer</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {docs.length === 0 ? (
            <p className="text-text-secondary px-4 pb-4 text-sm">
              Aucun document. Tant qu'il n'y en a pas, les comptes s'ouvrent dès l'activation.
            </p>
          ) : (
            <ul className="divide-y divide-current/10">
              {docs.map((d) => (
                <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
                  <div>
                    <div className="font-medium">
                      {d.title} <span className="text-text-secondary text-xs">v{d.version} · {TYPES[d.kind] ?? d.kind}</span>
                    </div>
                    <div className="text-text-secondary text-xs">
                      Requis pour : {d.required_for.map((r) => ROLES[r] ?? r).join(", ") || "personne"} · {d.signatures} signature
                      {d.signatures > 1 ? "s" : ""} de cette version {d.active ? "" : "· désactivé"}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      className={bouton}
                      onClick={() => {
                        setEdition(d.id);
                        setF({ code: d.code, kind: d.kind, title: d.title, body_html: "", required_for: d.required_for });
                      }}
                    >
                      Modifier
                    </button>
                    <button
                      className={bouton}
                      disabled={busy}
                      onClick={() => void agir(() => modifierDocumentASigner(d.id, { active: !d.active }), d.active ? "Document désactivé." : "Document réactivé.")}
                    >
                      {d.active ? "Désactiver" : "Réactiver"}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{edition ? "Modifier le document" : "Nouveau document à signer"}</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="grid gap-3 sm:grid-cols-2" onSubmit={enregistrer}>
            <input className={champ} required placeholder="Titre" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
            {!edition && (
              <input
                className={champ}
                required
                pattern="[a-z0-9_\-]+"
                placeholder="Code interne (ex. reglement-2026)"
                value={f.code}
                onChange={(e) => setF({ ...f, code: e.target.value })}
              />
            )}
            {!edition && (
              <select className={champ} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
                {Object.entries(TYPES).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            )}
            <div className="flex flex-wrap items-center gap-3 text-sm">
              Requis pour :
              {Object.entries(ROLES).map(([k, v]) => (
                <label key={k} className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={f.required_for.includes(k)}
                    onChange={(e) =>
                      setF({ ...f, required_for: e.target.checked ? [...f.required_for, k] : f.required_for.filter((r) => r !== k) })
                    }
                  />
                  {v}
                </label>
              ))}
            </div>
            <textarea
              className={`${champ} min-h-[220px] font-mono text-xs sm:col-span-2`}
              required={!edition}
              placeholder={edition ? "Nouveau texte (laisser vide pour ne changer que les rôles)" : "Texte du document (HTML simple : <h2>, <p>, <ul>, <strong>)"}
              value={f.body_html}
              onChange={(e) => setF({ ...f, body_html: e.target.value })}
            />
            {edition && f.body_html && (
              <p className="text-xs text-amber-500 sm:col-span-2">
                Changer le texte crée une nouvelle version : toutes les personnes concernées devront signer à nouveau.
              </p>
            )}
            <div className="flex gap-2 sm:col-span-2">
              <button className={bouton} disabled={busy}>
                {edition ? "Enregistrer" : "Créer"}
              </button>
              {edition && (
                <button type="button" className={bouton} onClick={() => (setEdition(null), setF(vide))}>
                  Annuler
                </button>
              )}
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Signatures manquantes ({parPersonne.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {parPersonne.length === 0 ? (
            <p className="text-text-secondary px-4 pb-4 text-sm">Tout le monde est à jour.</p>
          ) : (
            <ul className="divide-y divide-current/10">
              {parPersonne.map(([id, p]) => (
                <li key={id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
                  <div>
                    <div className="font-medium">
                      {p.nom} <span className="text-text-secondary text-xs">{p.email} · {ROLES[p.role] ?? p.role}</span>
                    </div>
                    <div className="text-text-secondary text-xs">
                      {p.actif ? "À signer : " : "Compte non activé · "}
                      {p.docs.join(", ")}
                    </div>
                  </div>
                  {!p.actif && (
                    <button className={bouton} disabled={busy} onClick={() => void agir(() => envoyerInvitation(id), "Invitation renvoyée.")}>
                      Renvoyer l'invitation
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
