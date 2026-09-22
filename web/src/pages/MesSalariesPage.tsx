import { useCallback, useEffect, useState } from "react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { EnTetePage } from "@/components/EnTetePage";
import { Refus } from "@/components/Refus";
import { SqueletteEcran } from "@/components/EmptyState";
import { getSalaries, inscrireSalarie, type EtatSalaries } from "@/lib/learn";
import { expliquerCourt } from "@/lib/refus";

/**
 * L'écran d'une entreprise cliente : ses salariés, et l'inscription d'un nouveau.
 *
 * Ce que cet écran ne fait pas : décider. L'éligibilité de la société — cliente établie,
 * active, sous son plafond — est tranchée côté serveur par `learn_societe_eligible()`, et
 * l'écran se contente d'en montrer le **motif**. Recalculer la règle ici produirait deux
 * versions de la même règle, et un jour elles ne diraient plus la même chose.
 *
 * Le motif est affiché tel qu'il est, traduit : « pas encore cliente » se règle avec son
 * organisme, « plafond atteint » se règle en demandant une extension. Deux situations très
 * différentes qu'un simple « impossible » confondrait.
 */

const MOTIFS: Record<string, string> = {
  societe_inconnue: "Cette société n'est pas reconnue par l'organisme.",
  societe_non_cliente:
    "Votre société n'est pas encore enregistrée comme cliente. Votre organisme de formation active cet accès.",
  societe_suspendue: "L'accès de votre société est suspendu. Contactez votre organisme.",
};

function motifLisible(motif: string | null): string {
  if (!motif) return "";
  if (motif.startsWith("plafond_atteint")) {
    const m = motif.match(/\((\d+)\/(\d+)\)/);
    return m
      ? `Vous avez atteint votre plafond de ${m[2]} salariés. Demandez une extension à votre organisme.`
      : "Vous avez atteint votre plafond de salariés.";
  }
  return MOTIFS[motif] ?? motif;
}

const ETATS: Record<string, string> = {
  deposee: "Déposée",
  verifiee: "Vérifiée",
  refusee: "Refusée",
  creee: "Compte créé",
};

export default function MesSalariesPage() {
  const [etat, setEtat] = useState<EtatSalaries | null>(null);
  const [erreur, setErreur] = useState<unknown>(null);
  const [chargement, setChargement] = useState(true);
  const [email, setEmail] = useState("");
  const [nom, setNom] = useState("");
  const [busy, setBusy] = useState(false);
  const [bilan, setBilan] = useState<string | null>(null);

  const charger = useCallback(async () => {
    setChargement(true);
    try {
      setEtat(await getSalaries());
      setErreur(null);
    } catch (e) {
      setErreur(e);
    } finally {
      setChargement(false);
    }
  }, []);
  useEffect(() => void charger(), [charger]);

  if (chargement) return <SqueletteEcran />;
  if (erreur || !etat) {
    return <Refus erreur={erreur} quoi="la liste de vos salariés" onReessayer={() => void charger()} />;
  }

  const champ =
    "w-full rounded-md border border-current/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/40";

  const manque =
    !nom.trim() || nom.trim().length < 2
      ? "Indiquez le nom et le prénom du salarié."
      : !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())
        ? "Indiquez une adresse e-mail valide."
        : null;

  const envoyer = async () => {
    if (manque) return;
    setBusy(true);
    setBilan(null);
    try {
      await inscrireSalarie(email.trim(), nom.trim());
      setBilan("Le salarié est inscrit. Une invitation vient de lui être envoyée.");
      setEmail("");
      setNom("");
      await charger();
    } catch (e) {
      setBilan(expliquerCourt(e, "cette inscription"));
    } finally {
      setBusy(false);
    }
  };

  const plafond = etat.places.plafond;

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <EnTetePage
        titre="Mes salariés"
        description={
          <>
            Les personnes de {etat.societe?.name ?? "votre société"} inscrites à des formations.
            {plafond != null
              ? ` ${etat.places.occupees} sur ${plafond} places utilisées.`
              : ` ${etat.places.occupees} inscrit${etat.places.occupees > 1 ? "s" : ""}.`}
          </>
        }
      />

      {!etat.eligible && (
        <Refus
          erreur={{ status: 403, code: "societe_non_eligible" }}
          quoi="l'inscription d'un salarié"
          className="max-w-2xl"
        />
      )}
      {!etat.eligible && etat.motif && (
        <p className="-mt-3 max-w-2xl text-sm text-text-secondary">{motifLisible(etat.motif)}</p>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Vos salariés</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-current/10">
              {etat.items.map((s) => (
                <li key={s.id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2.5 text-sm">
                  <span className="min-w-0">
                    <span className="block truncate">{s.full_name || s.email}</span>
                    <span className="block truncate text-xs text-text-secondary">{s.email}</span>
                  </span>
                  <span className="shrink-0 text-xs text-text-secondary">
                    depuis le {new Date(s.created_at).toLocaleDateString("fr-FR")}
                  </span>
                </li>
              ))}
              {etat.items.length === 0 && (
                <li className="px-4 py-8 text-center text-sm text-text-secondary">
                  Aucun salarié inscrit pour le moment.
                </li>
              )}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Inscrire un salarié</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium uppercase tracking-[0.14em] text-text-secondary">
                Nom et prénom
              </span>
              <input className={champ} value={nom} maxLength={120}
                     onChange={(e) => setNom(e.target.value)} placeholder="Camille Martin" />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium uppercase tracking-[0.14em] text-text-secondary">
                Adresse e-mail
              </span>
              <input className={champ} value={email} maxLength={254} inputMode="email"
                     onChange={(e) => setEmail(e.target.value)} placeholder="camille@exemple.fr" />
            </label>

            <Button onClick={() => void envoyer()} disabled={busy || !!manque || !etat.eligible}>
              {busy ? "Inscription…" : "Inscrire"}
            </Button>
            {manque && etat.eligible && (
              <span className="text-xs text-text-secondary">{manque}</span>
            )}
            {bilan && (
              <p className="rounded-lg border border-current/15 px-3 py-2 text-sm">{bilan}</p>
            )}
            <p className="text-xs leading-relaxed text-text-secondary">
              Le salarié reçoit une invitation et choisit lui-même son mot de passe. Votre
              organisme est prévenu de chaque inscription.
            </p>
          </CardContent>
        </Card>
      </div>

      {etat.demandes.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Vos demandes</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-current/10">
              {etat.demandes.map((d) => (
                <li key={d.id} className="flex flex-wrap items-baseline justify-between gap-2 px-4 py-2.5 text-sm">
                  <span className="min-w-0">
                    <span className="block truncate">{d.nom_complet || d.email}</span>
                    <span className="block truncate text-xs text-text-secondary">
                      {new Date(d.created_at).toLocaleDateString("fr-FR")}
                      {d.par_un_agent ? " · déposée par l'assistant" : ""}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-text-secondary">
                    {ETATS[d.statut] ?? d.statut}
                    {d.statut === "refusee" && d.motif ? ` — ${motifLisible(d.motif)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
