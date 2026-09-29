import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SqueletteEcran } from "@/components/EmptyState";
import { LiensLearn } from "@/components/LiensLearn";
import { getFactures, getFacturePdf, LearnError, type Facture, type Factures, type StatutFacture } from "@/lib/learn";
import { expliquerCourt } from "@/lib/refus";
import { useLearnRole } from "@/lib/supabase";

/**
 * Les factures (liste F5).
 *
 * Un seul écran pour tous ceux qui en ont l'usage — l'administration, l'audit, l'entreprise,
 * l'apprenant — et **c'est la base qui décide ce que chacun voit** (politique de
 * `learn_invoices`) : l'écran ne filtre rien par rôle, il ne fait qu'adapter ses mots. Un
 * salarié inscrit par son employeur ne voit pas la facture de l'employeur, parce que la base ne
 * la lui rend pas — pas parce que ce composant la cacherait.
 *
 * Stripe émet, la plateforme reflète : numéro, montants et statut sont ceux de Stripe. La pièce
 * qui fait foi est la copie du coffre, signée à chaque clic (deux minutes), jamais mémorisée.
 */

const STATUT: Record<StatutFacture, { libelle: string; ton: string }> = {
  paid: { libelle: "Payée", ton: "text-success ring-success/40" },
  open: { libelle: "En attente", ton: "text-warning ring-warning/40" },
  uncollectible: { libelle: "Irrécouvrable", ton: "text-destructive ring-destructive/40" },
  void: { libelle: "Annulée", ton: "opacity-60 ring-current/30" },
  draft: { libelle: "Brouillon", ton: "opacity-60 ring-current/30" },
};

const euros = (centimes: number) =>
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format((centimes || 0) / 100);

const jour = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("fr-FR");
};

type Filtre = "toutes" | "paid" | "open" | "a_rattacher";

export default function LearnFacturesPage() {
  const { role, resolu } = useLearnRole();
  const [params, setParams] = useSearchParams();
  const societe = params.get("societe") ?? undefined;
  const [filtre, setFiltre] = useState<Filtre>("toutes");
  const [donnees, setDonnees] = useState<Factures | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [ouverture, setOuverture] = useState<string | null>(null);

  const pilote = role === "super_admin" || role === "admin" || role === "auditeur";

  const charger = useCallback(async () => {
    setErreur(null);
    try {
      setDonnees(
        await getFactures({
          company_id: societe,
          statut: filtre === "paid" || filtre === "open" ? filtre : undefined,
          a_rattacher: filtre === "a_rattacher" ? true : undefined,
        }),
      );
    } catch (e) {
      setDonnees({ items: [], totaux: { encaisse: 0, en_attente: 0, irrecouvrable: 0, devise: "eur" },
                   anomalies: { payees_non_envoyees: 0, a_rattacher: 0 }, tronque: false });
      setErreur(expliquerCourt(e, "les factures"));
    }
  }, [societe, filtre]);

  useEffect(() => {
    if (!resolu) return;
    void charger();
  }, [charger, resolu]);

  const ouvrir = useCallback(async (f: Facture) => {
    setOuverture(f.id);
    setErreur(null);
    try {
      // Signature demandée maintenant : chaque clic repasse par le contrôle d'accès.
      const r = await getFacturePdf(f.id);
      window.open(r.url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setErreur(e instanceof LearnError ? e.message : "La facture n'a pas pu être ouverte.");
    } finally {
      setOuverture(null);
    }
  }, []);

  const titre = useMemo(() => {
    if (role === "apprenant") return "Mes factures";
    if (role === "entreprise") return "Factures de votre société";
    return "Factures";
  }, [role]);

  if (!resolu || donnees === null) return <SqueletteEcran lignes={6} />;

  const { items, totaux, anomalies } = donnees;
  const societeNom = societe ? items.find((f) => f.company_id === societe)?.societe : null;

  return (
    <div className="space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">{titre}</h1>
        <p className="mt-1 text-sm opacity-70">
          {role === "auditeur"
            ? "Lecture seule : le financement des actions de formation, tel que Stripe l'a émis."
            : "Émises par Stripe, conservées au coffre. La copie du coffre est la pièce qui fait foi."}
        </p>
        {societe ? (
          <p className="mt-2 text-sm">
            Société : <strong>{societeNom ?? "sélectionnée"}</strong>{" "}
            <button className="underline opacity-70" onClick={() => setParams({})}>
              voir toutes
            </button>
          </p>
        ) : null}
      </header>

      {pilote ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Indicateur libelle="Encaissé" valeur={euros(totaux.encaisse)} />
          <Indicateur libelle="En attente de paiement" valeur={euros(totaux.en_attente)} />
          <Indicateur
            libelle="À rattacher"
            valeur={String(anomalies.a_rattacher)}
            aide="Acheteur pas encore connu dans LEARN : la facture se rattachera d'elle-même à la création de son compte."
          />
          <Indicateur
            libelle="Payées, jamais envoyées"
            valeur={String(anomalies.payees_non_envoyees)}
            alerte={anomalies.payees_non_envoyees > 0}
            aide="Quelqu'un a payé sans recevoir sa facture. À regarder en premier."
          />
        </div>
      ) : null}

      {pilote ? (
        <div className="flex flex-wrap gap-2 text-sm" role="tablist" aria-label="Filtrer les factures">
          {(
            [
              ["toutes", "Toutes"],
              ["paid", "Payées"],
              ["open", "En attente"],
              ["a_rattacher", "À rattacher"],
            ] as const
          ).map(([v, l]) => (
            <button
              key={v}
              role="tab"
              aria-selected={filtre === v}
              onClick={() => setFiltre(v)}
              className={`rounded border px-3 py-1 ${filtre === v ? "border-current" : "border-current/20 opacity-70 hover:opacity-100"}`}
            >
              {l}
            </button>
          ))}
        </div>
      ) : null}

      {erreur ? (
        <Card>
          <CardContent className="p-4 text-sm">
            {erreur}{" "}
            <button className="underline" onClick={() => void charger()}>
              Réessayer
            </button>
          </CardContent>
        </Card>
      ) : null}

      {items.length === 0 && !erreur ? (
        <Card>
          <CardContent className="p-8 text-center text-sm opacity-70">
            {role === "apprenant"
              ? "Aucune facture à votre nom. Si votre employeur a payé votre formation, la facture lui est adressée."
              : role === "entreprise"
                ? "Aucune facture pour votre société pour le moment."
                : "Aucune facture. Elles apparaissent ici dès que Stripe les émet — commande, échéance ou relance."}
          </CardContent>
        </Card>
      ) : items.length > 0 ? (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              {items.length} facture{items.length > 1 ? "s" : ""}
              {donnees.tronque ? " (les plus récentes)" : ""}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[52rem] text-sm">
                <thead>
                  <tr className="border-b border-current/10 text-left">
                    <Th>Facture</Th>
                    {pilote ? <Th>Débiteur</Th> : null}
                    <Th>Émise le</Th>
                    <Th>Montant TTC</Th>
                    <Th>Statut</Th>
                    <Th>Envoyée</Th>
                    <Th>&nbsp;</Th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((f) => {
                    const oubliee = f.statut === "paid" && !f.envoyee_le;
                    return (
                      <tr key={f.id} className="border-b border-current/5 last:border-0">
                        <td className="px-4 py-2.5">
                          <div className="font-medium tabular-nums">{f.numero ?? "—"}</div>
                          <div className="text-xs opacity-60">
                            {[f.formation, f.session_code].filter(Boolean).join(" · ") || "—"}
                          </div>
                        </td>
                        {pilote ? (
                          <td className="px-4 py-2.5">
                            {f.a_rattacher ? (
                              <span
                                className="rounded px-1.5 py-0.5 text-[10px] ring-1 ring-current"
                                title="Se rattachera d'elle-même à la création du compte de l'acheteur"
                              >
                                à rattacher
                              </span>
                            ) : (
                              <span>{f.societe ?? f.personne ?? "—"}</span>
                            )}
                            <div className="text-xs opacity-60">{f.destinataire_nom ?? f.destinataire_email}</div>
                          </td>
                        ) : null}
                        <td className="px-4 py-2.5 opacity-80">{jour(f.emise_le)}</td>
                        <td className="px-4 py-2.5 tabular-nums">{euros(f.montant_ttc)}</td>
                        <td className="px-4 py-2.5">
                          <span className={`rounded px-1.5 py-0.5 text-xs ring-1 ${STATUT[f.statut]?.ton ?? ""}`}>
                            {STATUT[f.statut]?.libelle ?? f.statut}
                          </span>
                        </td>
                        <td className={`px-4 py-2.5 ${oubliee && pilote ? "text-destructive" : "opacity-70"}`}>
                          {f.envoyee_le ? jour(f.envoyee_le) : oubliee && pilote ? "jamais" : "—"}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <button
                            type="button"
                            onClick={() => void ouvrir(f)}
                            disabled={ouverture === f.id}
                            className="rounded border border-current/25 px-2.5 py-1 text-xs hover:bg-current/5 disabled:opacity-50"
                            title={f.piece_au_coffre ? "Copie conservée au coffre" : "Page de la facture chez Stripe"}
                          >
                            {ouverture === f.id ? "Ouverture…" : f.piece_au_coffre ? "PDF" : "Voir"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <LiensLearn />
    </div>
  );
}

function Indicateur({ libelle, valeur, aide, alerte }: { libelle: string; valeur: string; aide?: string; alerte?: boolean }) {
  return (
    <Card>
      <CardContent className="py-4" title={aide}>
        <div className="text-[11px] font-semibold uppercase tracking-wider opacity-60">{libelle}</div>
        <div className={`mt-1 text-xl font-semibold tabular-nums ${alerte ? "text-destructive" : ""}`}>{valeur}</div>
      </CardContent>
    </Card>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wider opacity-60">{children}</th>;
}
