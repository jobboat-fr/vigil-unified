import { useCallback, useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { getVault, LearnError, type VaultObject } from "@/lib/learn";

/**
 * Documents et coffre.
 *
 * Le coffre n'est pas un dossier de fichiers : chaque pièce porte une horloge de
 * conservation et, parfois, une suspension légale. La suppression est refusée par un
 * déclencheur en base tant que la date n'est pas passée — y compris pour un super_admin.
 * Cet écran affiche donc l'échéance à côté de chaque pièce, parce que « pourquoi je ne peux
 * pas supprimer ça » est la question qu'on pose sinon.
 */
export default function LearnVaultPage() {
  const [items, setItems] = useState<VaultObject[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await getVault();
      setItems(r.items);
    } catch (e) {
      setItems([]);
      setError(e instanceof LearnError ? e.message : "Chargement impossible.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (items === null) return <p className="p-6 text-sm opacity-60">Chargement…</p>;

  const held = items.filter((i) => i.legal_hold);
  const retained = items.filter((i) => !i.legal_hold && i.retention_until);

  return (
    <div className="space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Documents et coffre</h1>
        <p className="mt-1 text-sm opacity-70">
          {items.length} pièce{items.length > 1 ? "s" : ""} · {retained.length} sous
          conservation · {held.length} sous suspension légale
        </p>
      </header>

      {error ? (
        <Card>
          <CardContent className="p-4 text-sm">
            {error}{" "}
            <button className="underline" onClick={() => void load()}>
              Réessayer
            </button>
          </CardContent>
        </Card>
      ) : null}

      {items.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm opacity-70">
            Le coffre est vide. Conventions, feuilles d&apos;émargement, attestations et
            certificats s&apos;y déposent automatiquement à mesure que les sessions avancent.
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Pièces conservées</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[44rem] text-sm">
                <thead>
                  <tr className="border-b border-current/10 text-left">
                    <Th>Pièce</Th>
                    <Th>Nature</Th>
                    <Th>Conservation</Th>
                    <Th>Taille</Th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((o) => (
                    <tr key={o.id} className="border-b border-current/5 last:border-0">
                      <td className="px-4 py-2.5">
                        {o.filename ?? o.id.slice(0, 8)}
                        {o.imported ? (
                          <span
                            className="ml-2 rounded px-1.5 py-0.5 text-[10px] ring-1 ring-current"
                            title="Reprise de données : archivé tel quel, jamais converti en signature"
                          >
                            importé
                          </span>
                        ) : null}
                      </td>
                      <td className="px-4 py-2.5 opacity-70">{o.kind}</td>
                      <td className="px-4 py-2.5 opacity-70">
                        {o.legal_hold
                          ? "suspension légale — suppression bloquée"
                          : o.retention_until
                            ? `jusqu'au ${frDate(o.retention_until)}`
                            : "—"}
                      </td>
                      <td className="px-4 py-2.5 tabular-nums opacity-70">
                        {o.size_bytes ? `${Math.round(o.size_bytes / 1024)} ko` : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wider opacity-60">
      {children}
    </th>
  );
}

function frDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("fr-FR");
}
