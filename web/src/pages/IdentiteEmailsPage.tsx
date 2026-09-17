import { useCallback, useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import {
  ajouterDomaine,
  apercuModele,
  deposerLogo,
  getDomaines,
  getEnvois,
  getMarque,
  getModelesEmail,
  messageAccueil,
  retirerDomaine,
  retirerModele,
  setMarque,
  validerModele,
  verifierDomaine,
  type Domaine,
  type Envoi,
  type Marque,
  type ModeleEmail,
} from "@/lib/accueil";

const champ = "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm";
const bouton = "rounded-md border border-current/30 px-3 py-1.5 text-sm font-medium hover:bg-current/10 disabled:opacity-40";

const STATUT_DOMAINE: Record<string, string> = {
  en_attente: "En attente des enregistrements DNS",
  verifie: "Vérifié",
  echec: "Vérification échouée",
  retire: "Retiré",
};
const STATUT_ENVOI: Record<string, string> = {
  envoye: "Envoyé",
  echec: "Échec",
  brouillon: "En attente",
  annule: "Non envoyé",
  planifie: "Planifié",
};
const RAISON: Record<string, string> = {
  modele_non_valide: "modèle non validé",
  validation_requise: "validation requise",
  adresse_suspendue: "adresse suspendue (rebond ou plainte)",
  desinscrit: "destinataire désinscrit",
  sans_consentement: "sans consentement",
  fournisseur_absent: "envoi non configuré",
};

/**
 * Identité et e-mails de l'organisme. Tout ce qui part de VTLVS en son nom porte ce qui est
 * réglé ici : logo, couleur, mentions, adresse de réponse, domaine d'envoi. Les modèles
 * automatiques ne partent qu'une fois validés — l'aperçu montre l'e-mail exact.
 */
export default function IdentiteEmailsPage() {
  const [marque, setM] = useState<Marque | null>(null);
  const [domaines, setDomaines] = useState<{ items: Domaine[]; repli: string; familles: { code: string; libelle: string; adresse: string }[] } | null>(null);
  const [modeles, setModeles] = useState<ModeleEmail[]>([]);
  const [envois, setEnvois] = useState<Envoi[]>([]);
  const [apercu, setApercu] = useState<{ cle: string; html: string } | null>(null);
  const [nouveauDomaine, setNouveauDomaine] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; texte: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const charger = useCallback(async () => {
    try {
      const [m, d, mo, e] = await Promise.all([getMarque(), getDomaines(), getModelesEmail(), getEnvois()]);
      setM(m);
      setDomaines(d);
      setModeles(mo.items);
      setEnvois(e.items);
    } catch (e) {
      setMsg({ ok: false, texte: messageAccueil(e) });
    }
  }, []);
  useEffect(() => void charger(), [charger]);

  const agir = async (f: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setMsg(null);
    try {
      await f();
      setMsg({ ok: true, texte: ok });
      await charger();
    } catch (e) {
      setMsg({ ok: false, texte: messageAccueil(e) });
    } finally {
      setBusy(false);
    }
  };

  if (!marque || !domaines) return <p className="p-6 text-sm opacity-70">{msg?.texte ?? "Chargement…"}</p>;
  const verifie = domaines.items.find((d) => d.status === "verifie");
  const set = (k: keyof Marque) => (e: React.ChangeEvent<HTMLInputElement>) => setM({ ...marque, [k]: e.target.value });

  return (
    <div className="flex flex-col gap-4">
      {msg && <p className={`text-sm ${msg.ok ? "opacity-80" : "text-red-500"}`}>{msg.texte}</p>}

      <Card>
        <CardHeader>
          <CardTitle>Identité de l'organisme</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <div className="flex items-center gap-4 sm:col-span-2">
            {marque.logo_url ? (
              <img src={marque.logo_url} alt="Logo" className="h-12 max-w-[200px] rounded border border-current/10 bg-white object-contain p-1" />
            ) : (
              <span className="text-text-secondary text-xs">Aucun logo : les e-mails affichent le nom de l'organisme.</span>
            )}
            <label className={`${bouton} cursor-pointer`}>
              Déposer un logo
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void agir(() => deposerLogo(f), "Logo enregistré.");
                }}
              />
            </label>
            <span className="text-text-secondary text-[11px]">PNG, JPEG ou WebP, 1 Mo maximum, fond clair.</span>
          </div>
          <input className={champ} placeholder="Raison sociale" value={marque.legal_name ?? ""} onChange={set("legal_name")} />
          <div className="flex items-center gap-2">
            <input type="color" value={marque.primary_colour || "#1D3FAE"} onChange={set("primary_colour")} className="h-9 w-12 rounded" aria-label="Couleur" />
            <input className={champ} placeholder="#1D3FAE" value={marque.primary_colour ?? ""} onChange={set("primary_colour")} />
          </div>
          <input className={champ} placeholder="Adresse postale" value={marque.address ?? ""} onChange={set("address")} />
          <input className={champ} placeholder="E-mail de contact (adresse de réponse)" value={marque.contact_email ?? ""} onChange={set("contact_email")} />
          <input className={champ} placeholder="N° de déclaration d'activité (NDA)" value={marque.nda ?? ""} onChange={set("nda")} />
          <input className={champ} placeholder="SIRET" value={marque.siret ?? ""} onChange={set("siret")} />
          <input className={champ} placeholder="Site web (https://…)" value={marque.website ?? ""} onChange={set("website")} />
          <input className={champ} placeholder="Mentions complémentaires (pied des e-mails)" value={marque.footer_mentions ?? ""} onChange={set("footer_mentions")} />
          <div className="sm:col-span-2">
            <button
              className={bouton}
              disabled={busy || !(marque.legal_name ?? "").trim()}
              onClick={() =>
                void agir(
                  () =>
                    setMarque({
                      legal_name: marque.legal_name,
                      logo_url: marque.logo_url || null,
                      primary_colour: marque.primary_colour || null,
                      address: marque.address || null,
                      nda: marque.nda || null,
                      siret: marque.siret || null,
                      footer_mentions: marque.footer_mentions || null,
                      contact_email: marque.contact_email || null,
                      website: marque.website || null,
                    }),
                  "Identité enregistrée.",
                )
              }
            >
              Enregistrer
            </button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Domaine d'envoi</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <p className="text-text-secondary">
            {verifie
              ? `Vos e-mails partent de ${verifie.domain}.`
              : `Tant qu'aucun domaine n'est vérifié, vos e-mails partent de ${domaines.repli} à votre nom.`}{" "}
            Une adresse par famille :
          </p>
          <ul className="text-text-secondary grid gap-x-4 text-xs sm:grid-cols-2">
            {domaines.familles.map((f) => (
              <li key={f.code}>
                {f.libelle} — <code>{f.adresse}@{verifie?.domain ?? domaines.repli}</code>
              </li>
            ))}
          </ul>
          {domaines.items
            .filter((d) => d.status !== "retire")
            .map((d) => (
              <div key={d.id} className="rounded-md border border-current/15 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <strong>{d.domain}</strong>
                  <span className={d.status === "verifie" ? "text-green-600" : "text-amber-500"}>{STATUT_DOMAINE[d.status]}</span>
                </div>
                {d.status !== "verifie" && d.dns_records.length > 0 && (
                  <div className="mt-2 overflow-x-auto">
                    <p className="text-text-secondary mb-1 text-xs">Ajoutez ces enregistrements chez votre hébergeur DNS, puis vérifiez :</p>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left opacity-60">
                          <th className="pr-2">Type</th>
                          <th className="pr-2">Nom</th>
                          <th className="pr-2">Valeur</th>
                          <th>Priorité</th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.dns_records.map((r, i) => (
                          <tr key={i} className="align-top">
                            <td className="pr-2">{r.type}</td>
                            <td className="pr-2"><code>{r.name}</code></td>
                            <td className="pr-2"><code className="break-all">{r.value}</code></td>
                            <td>{r.priority ?? ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <div className="mt-2 flex gap-2">
                  {d.status !== "verifie" && (
                    <button className={bouton} disabled={busy} onClick={() => void agir(() => verifierDomaine(d.id), "Vérification demandée.")}>
                      Vérifier
                    </button>
                  )}
                  <button className={bouton} disabled={busy} onClick={() => void agir(() => retirerDomaine(d.id), "Domaine retiré.")}>
                    Retirer
                  </button>
                </div>
              </div>
            ))}
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              void agir(() => ajouterDomaine(nouveauDomaine), "Domaine ajouté : ajoutez les enregistrements DNS affichés.").then(() =>
                setNouveauDomaine(""),
              );
            }}
          >
            <input className={champ} placeholder="exemple : hbs-formation.fr" value={nouveauDomaine} onChange={(e) => setNouveauDomaine(e.target.value)} />
            <button className={bouton} disabled={busy || !nouveauDomaine.trim()}>
              Ajouter
            </button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Modèles d'e-mails</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <p className="text-text-secondary px-4 pb-2 text-xs">
            Un modèle automatique ne part qu'une fois validé. Si VTLVS modifie son texte, sa version change et il faut le revalider.
          </p>
          <ul className="divide-y divide-current/10">
            {modeles.map((m) => (
              <li key={m.cle} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm">
                <div className="min-w-0">
                  <div className="font-medium">
                    {m.libelle} <span className="text-text-secondary text-xs">v{m.version} · {m.famille_libelle} · {m.adresse}@</span>
                  </div>
                  <div className="text-text-secondary truncate text-xs">{m.sujet_exemple}</div>
                </div>
                <div className="flex items-center gap-2">
                  <span className={m.valide ? "text-xs text-green-600" : "text-xs text-amber-500"}>
                    {m.valide ? "Validé" : m.envoi_auto ? "À valider" : "Validation à chaque envoi"}
                  </span>
                  <button className={bouton} onClick={() => void apercuModele(m.cle).then((html) => setApercu({ cle: m.cle, html }))}>
                    Aperçu
                  </button>
                  {m.envoi_auto &&
                    (m.valide ? (
                      <button className={bouton} disabled={busy} onClick={() => void agir(() => retirerModele(m.cle), "Validation retirée.")}>
                        Retirer
                      </button>
                    ) : (
                      <button className={bouton} disabled={busy} onClick={() => void agir(() => validerModele(m.cle), "Modèle validé.")}>
                        Valider
                      </button>
                    ))}
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {apercu && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Aperçu — {modeles.find((m) => m.cle === apercu.cle)?.libelle}</CardTitle>
            <button className={bouton} onClick={() => setApercu(null)}>
              Fermer
            </button>
          </CardHeader>
          <CardContent>
            <iframe title="Aperçu de l'e-mail" srcDoc={apercu.html} sandbox="" className="h-[640px] w-full rounded-md border border-current/10 bg-white" />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Derniers envois</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-0">
          {envois.length === 0 ? (
            <p className="text-text-secondary px-4 pb-4 text-sm">Aucun e-mail pour le moment.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left opacity-60">
                  <th className="px-4 py-2">Date</th>
                  <th className="px-2">Destinataire</th>
                  <th className="px-2">Objet</th>
                  <th className="px-2">État</th>
                </tr>
              </thead>
              <tbody>
                {envois.map((e) => (
                  <tr key={e.id} className="border-t border-current/10 align-top">
                    <td className="whitespace-nowrap px-4 py-2">{new Date(e.created_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</td>
                    <td className="px-2 py-2">{e.email}</td>
                    <td className="px-2 py-2">{e.subject}</td>
                    <td className="px-2 py-2">
                      {e.bounced_at ? "Rebond" : e.delivered_at ? "Délivré" : STATUT_ENVOI[e.status] ?? e.status}
                      {e.error ? ` — ${RAISON[e.error] ?? e.error}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
