import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { getFactures, type Factures } from "@/lib/learn";

const euros = (centimes: number) =>
  new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format((centimes || 0) / 100);

/**
 * Les factures de l'organisme en quatre chiffres, en tête de la Finance (liste F5).
 *
 * Ce ne sont pas les livres de la Finance — ceux-là sont saisis et rapprochés plus bas — mais ce
 * que Stripe a émis pour les formations : encaissé, en attente, et les deux anomalies qu'on doit
 * voir sans les chercher. Silencieux s'il n'y a rien (aucune facture, ou LEARN injoignable) : ce
 * bloc n'a pas à alarmer une page qui a sa propre vie.
 */
export function FacturesApercu() {
  const [f, setF] = useState<Factures | null>(null);

  useEffect(() => {
    let vivant = true;
    getFactures()
      .then((r) => vivant && setF(r))
      .catch(() => vivant && setF(null));
    return () => {
      vivant = false;
    };
  }, []);

  if (!f || f.items.length === 0) return null;
  const { totaux, anomalies } = f;
  return (
    <Card>
      <CardHeader className="flex flex-row items-baseline justify-between pb-2">
        <CardTitle className="text-base">Factures des formations</CardTitle>
        <Link to="/learn/factures" className="text-sm underline opacity-80 hover:opacity-100">
          Voir les {f.items.length} facture{f.items.length > 1 ? "s" : ""}
        </Link>
      </CardHeader>
      <CardContent className="grid grid-cols-2 gap-3 pb-4 md:grid-cols-4">
        <Chiffre libelle="Encaissé" valeur={euros(totaux.encaisse)} />
        <Chiffre libelle="En attente" valeur={euros(totaux.en_attente)} />
        <Chiffre libelle="À rattacher" valeur={String(anomalies.a_rattacher)} />
        <Chiffre
          libelle="Payées, jamais envoyées"
          valeur={String(anomalies.payees_non_envoyees)}
          alerte={anomalies.payees_non_envoyees > 0}
        />
      </CardContent>
    </Card>
  );
}

function Chiffre({ libelle, valeur, alerte }: { libelle: string; valeur: string; alerte?: boolean }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wider opacity-60">{libelle}</div>
      <div className={`mt-1 text-lg font-semibold tabular-nums ${alerte ? "text-destructive" : ""}`}>{valeur}</div>
    </div>
  );
}
