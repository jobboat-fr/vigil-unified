import { useCallback, useEffect, useState } from "react";
import { SqueletteEcran } from "@/components/EmptyState";
import { LiensLearn } from "@/components/LiensLearn";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import {
  getCalendar,
  getSlotSheet,
  sign,
  countersign,
  type Slot,
  type SheetRow,
} from "@/lib/learn";
import { isoDay } from "@/lib/day";
import { expliquerCourt } from "@/lib/refus";

/**
 * Émargement — signer avant et après chaque demi-journée.
 *
 * Trois règles appartiennent au serveur ; cet écran ne fait que les refléter :
 *
 *   l'heure est celle du serveur   — l'horloge d'un téléphone permettrait de signer hier
 *   entrée et sortie sont 2 lignes — une sortie manquante reste visiblement manquante
 *   rien n'est modifiable ensuite  — UPDATE et DELETE sont révoqués sur la table
 *
 * Il n'y a donc aucun bouton « modifier ». Pas caché : absent. Proposer une action que le
 * serveur refusera est pire que ne jamais laisser croire qu'elle existait.
 */
export default function LearnEmargementPage() {
  const [slots, setSlots] = useState<Slot[] | null>(null);
  const [sheets, setSheets] = useState<Record<string, SheetRow[]>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    // Date civile locale : `toISOString()` renvoyait la veille entre minuit et 2 h
    // du matin à Paris. Voir `lib/day.ts`.
    const today = isoDay();
    try {
      const r = await getCalendar(today, today);
      setSlots(r.items);
    } catch (e) {
      setSlots([]);
      setError(expliquerCourt(e, "l'émargement"));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function refreshSheet(slotId: string) {
    try {
      const r = await getSlotSheet(slotId);
      setSheets((m) => ({ ...m, [slotId]: r.items }));
    } catch {
      /* the signature landed; a failed re-read must not look like a failed signature */
    }
  }

  async function act(slotId: string, fn: () => Promise<unknown>) {
    setBusy(slotId);
    setError(null);
    try {
      await fn();
      await refreshSheet(slotId);
    } catch (e) {
      setError(expliquerCourt(e, "votre signature"));
    } finally {
      setBusy(null);
    }
  }

  if (slots === null) return <SqueletteEcran lignes={5} />;

  return (
    <div className="space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Émargement</h1>
        <p className="mt-1 text-sm opacity-70">
          Vos créneaux d&apos;aujourd&apos;hui. L&apos;heure enregistrée est celle du serveur,
          pas celle de l&apos;appareil.
        </p>
      </header>

      {error ? (
        <Card>
          <CardContent className="p-4 text-sm">{error}</CardContent>
        </Card>
      ) : null}

      {slots.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm opacity-70">
            Aucun créneau aujourd&apos;hui. L&apos;émargement porte sur la demi-journée en
            cours.
          </CardContent>
        </Card>
      ) : null}

      {slots.map((s) => {
        const rows = sheets[s.id];
        const working = busy === s.id;
        return (
          <Card key={s.id}>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">
                {s.title || "Créneau"}
              </CardTitle>
              <p className="text-xs opacity-70">
                {s.half === "am" ? "Matin" : "Après-midi"} · {hhmm(s.starts_at)}–{hhmm(s.ends_at)}
                {s.room_name ? ` · ${s.room_name}` : ""}
                {s.formateur_name ? ` · ${s.formateur_name}` : ""} · {s.enrolled} inscrit
                {s.enrolled > 1 ? "s" : ""}
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <button
                  className="min-h-11 rounded px-4 text-sm ring-1 ring-current disabled:opacity-50"
                  disabled={working}
                  onClick={() => void act(s.id, () => sign(s.id, "in"))}
                >
                  Signer mon arrivée
                </button>
                <button
                  className="min-h-11 rounded px-4 text-sm ring-1 ring-current disabled:opacity-50"
                  disabled={working}
                  onClick={() => void act(s.id, () => sign(s.id, "out"))}
                >
                  Signer mon départ
                </button>
                <button
                  className="min-h-11 rounded px-4 text-sm ring-1 ring-current disabled:opacity-50"
                  disabled={working}
                  onClick={() => void act(s.id, () => countersign(s.id))}
                  title="Réservé au formateur du créneau — la base refuse les autres"
                >
                  Contresigner
                </button>
                <button
                  className="min-h-11 rounded px-4 text-sm underline disabled:opacity-50"
                  disabled={working}
                  onClick={() => void refreshSheet(s.id)}
                >
                  Voir la feuille
                </button>
              </div>

              {rows ? (
                rows.length === 0 ? (
                  <p className="text-sm opacity-60">Personne n&apos;est inscrit sur ce créneau.</p>
                ) : (
                  <ul className="divide-y divide-current/10 text-sm">
                    {rows.map((r) => (
                      <li
                        key={r.apprenant_id}
                        className="flex flex-wrap items-baseline justify-between gap-x-4 py-1.5"
                      >
                        <span className="min-w-0 font-medium">{r.apprenant_name}</span>
                        <span className="tabular-nums opacity-70">
                          {r.signed_in_at ? hhmm(r.signed_in_at) : "—"} →{" "}
                          {r.signed_out_at ? hhmm(r.signed_out_at) : "—"}
                        </span>
                        {/* The state is a word, not only a colour: an émargement sheet is
                            printed into an audit file, often in black and white. */}
                        <span className="opacity-70">{STATE[r.state] ?? r.state}</span>
                        {r.countersigned_at ? (
                          <span className="opacity-60">contresigné {hhmm(r.countersigned_at)}</span>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                )
              ) : null}

              <p className="text-xs opacity-60">
                Une signature enregistrée ne peut plus être modifiée ni supprimée, par
                personne. C&apos;est ce qui lui donne sa valeur de preuve.
              </p>
            </CardContent>
          </Card>
        );
      })}

      <LiensLearn />
    </div>
  );
}

/** "entree_seule" is the state that matters: it is a missing exit, visibly missing. */
const STATE: Record<string, string> = {
  complet: "entrée et sortie signées",
  entree_seule: "sortie manquante",
  absent: "absent",
  non_signe: "non signé",
};

function hhmm(iso: string | null | undefined): string {
  if (!iso) return "--:--";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "--:--"
    : d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}
