import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { EnTetePage } from "@/components/EnTetePage";
import { Refus } from "@/components/Refus";
import { SqueletteEcran } from "@/components/EmptyState";
import { getProfiles, type Person } from "@/lib/learn";
import {
  composerMessage,
  getMessagesAdmin,
  type MessageAdmin,
  type NatureMessage,
} from "@/lib/accueil";
import { nomRole } from "@/lib/mots";
import { expliquerCourt } from "@/lib/refus";

/**
 * Écrire aux personnes de son organisme.
 *
 * Tout ce qui partait de la plateforme était jusqu'ici déclenché par un événement. Une
 * administration qui voulait simplement prévenir d'une fermeture n'avait aucun moyen de le
 * faire.
 *
 * Le choix de la nature est le seul vrai choix de cet écran, et il n'est pas cosmétique :
 * il décide du régime de consentement appliqué par le serveur. L'écran le dit en toutes
 * lettres sous chaque option, parce que « annonce » et « lettre d'information » se
 * ressemblent beaucoup vues d'ici et pas du tout vues du droit.
 *
 * Ce que l'écran ne fait pas : filtrer les destinataires pour des raisons de sécurité. La
 * liste proposée vient déjà de ce que le serveur accepte de montrer, et la portée est
 * retranchée une seconde fois à l'envoi. Un écran qui se croirait responsable du
 * cloisonnement finirait par l'être.
 */

const NATURES: { code: NatureMessage; titre: string; regime: string }[] = [
  {
    code: "direct",
    titre: "Message",
    regime:
      "À des personnes avec qui l'organisme est déjà en relation. Pas de lien de désinscription : ce n'est pas de la prospection.",
  },
  {
    code: "annonces",
    titre: "Annonce",
    regime:
      "Information générale. Porte un lien de désinscription, et les personnes qui s'en sont retirées ne la reçoivent pas.",
  },
  {
    code: "newsletter",
    titre: "Lettre d'information",
    regime:
      "N'est adressée qu'aux personnes ayant explicitement consenti. Les autres sont écartées à l'envoi, sans erreur.",
  },
];

export default function ComposerPage() {
  const [gens, setGens] = useState<Person[]>([]);
  const [passes, setPasses] = useState<MessageAdmin[]>([]);
  const [erreur, setErreur] = useState<unknown>(null);
  const [chargement, setChargement] = useState(true);

  const [nature, setNature] = useState<NatureMessage>("direct");
  const [sujet, setSujet] = useState("");
  const [corps, setCorps] = useState("");
  const [choisis, setChoisis] = useState<Set<string>>(new Set());
  const [filtreRole, setFiltreRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [bilan, setBilan] = useState<string | null>(null);

  const charger = useCallback(async () => {
    setChargement(true);
    try {
      const [p, m] = await Promise.all([getProfiles(), getMessagesAdmin()]);
      setGens(p.items);
      setPasses(m.items);
      setErreur(null);
    } catch (e) {
      setErreur(e);
    } finally {
      setChargement(false);
    }
  }, []);
  useEffect(() => void charger(), [charger]);

  const roles = useMemo(
    () => Array.from(new Set(gens.map((g) => g.role))).sort(),
    [gens],
  );
  const visibles = useMemo(
    () => (filtreRole ? gens.filter((g) => g.role === filtreRole) : gens),
    [gens, filtreRole],
  );

  const basculer = (id: string) =>
    setChoisis((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const toutCocher = () =>
    setChoisis((s) => {
      const n = new Set(s);
      const tous = visibles.every((g) => n.has(g.id));
      for (const g of visibles) {
        if (tous) n.delete(g.id);
        else n.add(g.id);
      }
      return n;
    });

  // Ce qui manque, dit avant l'envoi plutôt qu'après : un bouton qui se désactive sans
  // expliquer laisse chercher.
  const manque =
    choisis.size === 0
      ? "Choisissez au moins un destinataire."
      : sujet.trim().length < 3
        ? "L'objet doit faire au moins trois caractères."
        : corps.trim().length < 10
          ? "Le message est trop court."
          : null;

  const envoyer = async () => {
    if (manque) return;
    setBusy(true);
    setBilan(null);
    try {
      const r = await composerMessage({
        nature,
        sujet: sujet.trim(),
        corps: corps.trim(),
        destinataires: [...choisis],
      });
      setBilan(
        r.differes > 0
          ? `Message enregistré pour ${r.cibles} personnes. ${r.differes} envois partiront dans les minutes qui viennent.`
          : `Message traité pour ${r.cibles} personne${r.cibles > 1 ? "s" : ""}.`,
      );
      setSujet("");
      setCorps("");
      setChoisis(new Set());
      await charger();
    } catch (e) {
      setBilan(expliquerCourt(e, "ce message"));
    } finally {
      setBusy(false);
    }
  };

  if (chargement) return <SqueletteEcran />;
  if (erreur) return <Refus erreur={erreur} quoi="la composition" onReessayer={() => void charger()} />;

  const champ =
    "w-full rounded-md border border-current/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/40";

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <EnTetePage
        titre="Écrire aux personnes"
        description="Un message, une annonce ou une lettre d'information — adressés depuis les adresses de votre organisme, et consignés."
      />

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Le message</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <fieldset className="flex flex-col gap-2">
              <legend className="text-xs font-medium uppercase tracking-[0.14em] text-text-secondary">
                Nature
              </legend>
              {NATURES.map((n) => (
                <label
                  key={n.code}
                  className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-current/12 px-3 py-2.5"
                >
                  <input
                    type="radio"
                    name="nature"
                    className="mt-1"
                    checked={nature === n.code}
                    onChange={() => setNature(n.code)}
                  />
                  <span className="min-w-0">
                    <span className="text-sm font-medium">{n.titre}</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-text-secondary">
                      {n.regime}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium uppercase tracking-[0.14em] text-text-secondary">
                Objet
              </span>
              <input
                className={champ}
                value={sujet}
                maxLength={180}
                onChange={(e) => setSujet(e.target.value)}
                placeholder="Fermeture exceptionnelle du 24 décembre"
              />
            </label>

            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium uppercase tracking-[0.14em] text-text-secondary">
                Message
              </span>
              <textarea
                className={`${champ} min-h-44 resize-y font-normal`}
                value={corps}
                maxLength={20000}
                onChange={(e) => setCorps(e.target.value)}
                placeholder={"Nos bureaux seront fermés le 24 décembre.\n\nLes sessions prévues ce jour-là sont reportées."}
              />
              <span className="text-xs text-text-secondary">
                Une ligne vide sépare deux paragraphes. Rien d&apos;autre n&apos;est interprété :
                ni gras, ni balise.
              </span>
            </label>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={() => void envoyer()} disabled={busy || !!manque}>
                {busy ? "Envoi…" : `Envoyer à ${choisis.size} personne${choisis.size > 1 ? "s" : ""}`}
              </Button>
              {manque && <span className="text-xs text-text-secondary">{manque}</span>}
            </div>

            {bilan && (
              <p className="rounded-lg border border-current/15 px-3 py-2 text-sm">{bilan}</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Destinataires</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <select
                className={champ + " max-w-40"}
                value={filtreRole}
                onChange={(e) => setFiltreRole(e.target.value)}
              >
                <option value="">Tous les rôles</option>
                {roles.map((r) => (
                  <option key={r} value={r}>
                    {nomRole(r)}
                  </option>
                ))}
              </select>
              <Button size="sm" ghost onClick={toutCocher}>
                {visibles.every((g) => choisis.has(g.id)) ? "Tout décocher" : "Tout cocher"}
              </Button>
            </div>

            <ul className="max-h-[26rem] divide-y divide-current/10 overflow-y-auto rounded-lg border border-current/12">
              {visibles.map((g) => (
                <li key={g.id}>
                  <label className="flex cursor-pointer items-center gap-2.5 px-3 py-2 text-sm">
                    <input
                      type="checkbox"
                      checked={choisis.has(g.id)}
                      onChange={() => basculer(g.id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{g.full_name || g.email}</span>
                      <span className="block truncate text-xs text-text-secondary">
                        {nomRole(g.role)} · {g.email}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
              {visibles.length === 0 && (
                <li className="px-3 py-6 text-center text-sm text-text-secondary">
                  Aucune personne pour ce filtre.
                </li>
              )}
            </ul>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Ce qui a déjà été écrit</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <ul className="divide-y divide-current/10">
            {passes.map((m) => (
              <li key={m.id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2.5 text-sm">
                <span className="min-w-0">
                  <span className="block truncate font-medium">{m.sujet}</span>
                  <span className="block text-xs text-text-secondary">
                    {new Date(m.created_at).toLocaleDateString("fr-FR")}
                    {m.auteur_nom ? ` · ${m.auteur_nom}` : ""}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-text-secondary">
                  {m.envoyes} envoyé{m.envoyes > 1 ? "s" : ""}
                  {m.refuses > 0 ? ` · ${m.refuses} écarté${m.refuses > 1 ? "s" : ""}` : ""}
                  {m.attente > 0 ? ` · ${m.attente} en attente` : ""}
                </span>
              </li>
            ))}
            {passes.length === 0 && (
              <li className="px-4 py-8 text-center text-sm text-text-secondary">
                Rien n&apos;a encore été envoyé depuis cet écran.
              </li>
            )}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
