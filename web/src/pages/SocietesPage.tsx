import { useCallback, useEffect, useState } from "react";
import { Button } from "@nous-research/ui/ui/components/button";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { EnTetePage } from "@/components/EnTetePage";
import { Refus } from "@/components/Refus";
import { SqueletteEcran } from "@/components/EmptyState";
import { getSocietes, reglerSociete, type Societe } from "@/lib/learn";
import { expliquerCourt } from "@/lib/refus";

/**
 * Les sociétés clientes, et ce que l'organisme leur ouvre.
 *
 * Un réglage de cet écran a une conséquence directe et peu intuitive : **marquer une
 * société « cliente » est ce qui autorise un assistant à créer des comptes pour elle.**
 * Tant que la case est décochée, l'entreprise ne peut inscrire personne et l'agent non
 * plus — c'est le défaut, et il est fermé.
 *
 * L'écran le dit en toutes lettres à côté de la case, parce que c'est exactement le genre
 * de réglage qu'on coche machinalement pour « débloquer quelque chose » sans voir ce qu'on
 * vient d'ouvrir.
 */
export default function SocietesPage() {
  const [items, setItems] = useState<Societe[]>([]);
  const [erreur, setErreur] = useState<unknown>(null);
  const [chargement, setChargement] = useState(true);
  const [occupe, setOccupe] = useState<string | null>(null);
  const [bilan, setBilan] = useState<string | null>(null);

  const charger = useCallback(async () => {
    setChargement(true);
    try {
      setItems((await getSocietes()).items);
      setErreur(null);
    } catch (e) {
      setErreur(e);
    } finally {
      setChargement(false);
    }
  }, []);
  useEffect(() => void charger(), [charger]);

  const regler = async (s: Societe, reglages: Parameters<typeof reglerSociete>[1]) => {
    setOccupe(s.id);
    setBilan(null);
    try {
      await reglerSociete(s.id, reglages);
      await charger();
    } catch (e) {
      setBilan(expliquerCourt(e, "ce réglage"));
    } finally {
      setOccupe(null);
    }
  };

  if (chargement) return <SqueletteEcran />;
  if (erreur) return <Refus erreur={erreur} quoi="les sociétés clientes" onReessayer={() => void charger()} />;

  const champ =
    "w-24 rounded-md border border-current/15 bg-transparent px-2 py-1 text-sm outline-none focus:border-current/40";

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <EnTetePage
        titre="Sociétés clientes"
        description="Ce que chaque entreprise peut faire : inscrire ses salariés, jusqu'à quel plafond, et avec quels outils."
      />

      {bilan && <p className="max-w-2xl rounded-lg border border-current/15 px-3 py-2 text-sm">{bilan}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        {items.map((s) => {
          const cliente = Boolean(s.cliente_depuis);
          const busy = occupe === s.id;
          return (
            <Card key={s.id} className="flex flex-col">
              <CardHeader className="pb-3">
                <CardTitle className="flex flex-wrap items-baseline justify-between gap-2 text-base">
                  <span className="min-w-0 truncate">{s.name}</span>
                  <span className="shrink-0 text-xs font-normal text-text-secondary">
                    {s.salaries} salarié{s.salaries > 1 ? "s" : ""}
                    {s.max_apprenants != null ? ` / ${s.max_apprenants}` : " · sans plafond"}
                  </span>
                </CardTitle>
                {s.siret && <p className="text-xs text-text-secondary">SIRET {s.siret}</p>}
              </CardHeader>

              <CardContent className="flex flex-1 flex-col gap-4 text-sm">
                <label className="flex cursor-pointer items-start gap-2.5">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={cliente}
                    disabled={busy}
                    onChange={(e) => void regler(s, { cliente: e.target.checked })}
                  />
                  <span>
                    <span className="font-medium">Société cliente</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-text-secondary">
                      Décoché, elle ne peut inscrire aucun salarié — et l&apos;assistant non
                      plus, quoi qu&apos;on lui demande. C&apos;est cette case qui ouvre la
                      création de comptes pour cette société.
                    </span>
                  </span>
                </label>

                <label className="flex cursor-pointer items-start gap-2.5">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={s.actif}
                    disabled={busy}
                    onChange={(e) => void regler(s, { actif: e.target.checked })}
                  />
                  <span>
                    <span className="font-medium">Accès actif</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-text-secondary">
                      Suspendre ferme l&apos;inscription sans effacer l&apos;historique. Réversible.
                    </span>
                  </span>
                </label>

                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-medium uppercase tracking-[0.14em] text-text-secondary">
                    Plafond
                  </span>
                  <input
                    type="number"
                    min={0}
                    className={champ}
                    defaultValue={s.max_apprenants ?? ""}
                    disabled={busy}
                    placeholder="—"
                    onBlur={(e) => {
                      const v = e.target.value.trim();
                      if (v === "" && s.max_apprenants == null) return;
                      if (v === "") return void regler(s, { plafond_illimite: true });
                      const n = Number(v);
                      if (Number.isFinite(n) && n !== s.max_apprenants) void regler(s, { max_apprenants: n });
                    }}
                  />
                  <span className="text-xs text-text-secondary">
                    vide = sans plafond
                  </span>
                </div>

                <p className="mt-auto text-xs text-text-secondary">
                  {cliente
                    ? `Cliente depuis le ${new Date(s.cliente_depuis!).toLocaleDateString("fr-FR")}.`
                    : "Pas encore cliente : aucune inscription possible."}
                </p>
              </CardContent>
            </Card>
          );
        })}
        {items.length === 0 && (
          <Card>
            <CardContent className="p-8 text-center text-sm text-text-secondary">
              Aucune société cliente. Elles se créent en ajoutant un compte « entreprise cliente ».
            </CardContent>
          </Card>
        )}
      </div>

      <Button size="sm" ghost onClick={() => void charger()} className="self-start">
        Recharger
      </Button>
    </div>
  );
}
