import { useCallback, useEffect, useMemo, useState } from "react";
import { LiensLearn } from "@/components/LiensLearn";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { Link } from "react-router-dom";
import { getCalendar, issueCalendarToken, LearnError, type Slot } from "@/lib/learn";
import { isoDay } from "@/lib/day";

/**
 * The calendar — one component for every profile.
 *
 * There is no admin variant and no formateur variant. Direction, formateur, entreprise and
 * apprenant all call `GET /calendar`, and the number of créneaux that come back differs
 * because row-level security narrowed the query, not because this file branched. Proven at
 * the data layer: the same request returned 7 / 6 / 1 / 6 rows for four callers.
 *
 * Controls are rendered from each row's `_can`. A formateur sees "Émarger" on their own
 * half-day and nothing on someone else's, without this component knowing what a formateur
 * is.
 */

const DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"];

function mondayOf(d: Date) {
  const x = new Date(d);
  const day = (x.getDay() + 6) % 7; // Monday = 0
  x.setDate(x.getDate() - day);
  x.setHours(0, 0, 0, 0);
  return x;
}

// Voir `lib/day.ts` : `toISOString()` bascule en UTC et décale la journée d'un cran
// dans tout fuseau à l'est de Greenwich.
const iso = isoDay;

const hhmm = (s: string) =>
  new Date(s).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

export default function LearnCalendarPage() {
  const [anchor, setAnchor] = useState(() => mondayOf(new Date()));
  const [slots, setSlots] = useState<Slot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [ics, setIcs] = useState<string | null>(null);
  const [icsErreur, setIcsErreur] = useState<string | null>(null);

  const days = useMemo(
    () => Array.from({ length: 5 }, (_, i) => new Date(anchor.getTime() + i * 86_400_000)),
    [anchor],
  );

  const load = useCallback(async () => {
    const from = iso(days[0]);
    const to = iso(days[days.length - 1]);
    try {
      const r = await getCalendar(from, to);
      setSlots(r.items);
      setError(null);
    } catch (e) {
      if (e instanceof LearnError && e.unavailable) setUnavailable(true);
      else setError((e as Error).message);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  // Grid is date × half-day, because the demi-journée is the unit the law counts in —
  // not an hourly grid that would imply a precision émargement does not have.
  const cell = (d: Date, half: "am" | "pm") =>
    slots.filter((s) => s.on_date === iso(d) && s.half === half);

  if (unavailable) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-text-secondary">
          LEARN n'a pas de base de données configurée sur cet environnement.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <button
          className="border-current/20 rounded border px-3 py-1.5 text-sm"
          onClick={() => setAnchor(new Date(anchor.getTime() - 7 * 86_400_000))}
        >
          ‹ Semaine précédente
        </button>
        <button
          className="border-current/20 rounded border px-3 py-1.5 text-sm"
          onClick={() => setAnchor(mondayOf(new Date()))}
        >
          Cette semaine
        </button>
        <button
          className="border-current/20 rounded border px-3 py-1.5 text-sm"
          onClick={() => setAnchor(new Date(anchor.getTime() + 7 * 86_400_000))}
        >
          Semaine suivante ›
        </button>
        <span className="text-text-secondary ml-auto text-sm tabular-nums">
          {slots.length} créneau{slots.length > 1 ? "x" : ""}
        </span>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>
            Semaine du{" "}
            {anchor.toLocaleDateString("fr-FR", { day: "2-digit", month: "long", year: "numeric" })}
          </CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-separate border-spacing-1 text-sm">
            <thead>
              <tr>
                <th className="text-text-secondary w-20 text-left text-xs font-normal" />
                {days.map((d, i) => (
                  <th key={i} className="text-left text-xs font-normal">
                    {DAYS[i]} {d.getDate()}/{String(d.getMonth() + 1).padStart(2, "0")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(["am", "pm"] as const).map((half) => (
                <tr key={half}>
                  <td className="text-text-secondary align-top text-xs">
                    {half === "am" ? "Matin" : "Après-midi"}
                  </td>
                  {days.map((d, i) => {
                    const items = cell(d, half);
                    return (
                      <td key={i} className="align-top">
                        {items.length === 0 ? (
                          <div className="border-current/10 min-h-[64px] rounded border border-dashed" />
                        ) : (
                          items.map((s) => (
                            <div
                              key={s.id}
                              className="border-current/20 mb-1 rounded border p-2"
                              style={{ borderLeft: `3px solid ${s.room_colour ?? "#2E5FE0"}` }}
                            >
                              <Link
                                to="/learn/parcours"
                                className="block truncate font-medium underline-offset-2 hover:underline"
                                title={s.title ?? "Session"}
                              >
                                {s.title ?? "Session"}
                              </Link>
                              <div className="text-text-secondary text-xs tabular-nums">
                                {hhmm(s.starts_at)}–{hhmm(s.ends_at)}
                              </div>
                              {s.formateur_name && (
                                <div className="text-text-secondary truncate text-xs">
                                  {s.formateur_name}
                                </div>
                              )}
                              {/* Le taux de remplissage est un chiffre de gestion : il sert
                                  à qui place les stagiaires, pas à qui suit la formation.
                                  Conditionné à `_can.update` — la capacité à modifier le
                                  créneau — et non à un test de rôle, conformément à
                                  l'en-tête de ce fichier. La salle, elle, reste : c'est
                                  l'information dont on a besoin pour s'y rendre. */}
                              <div className="text-text-secondary text-xs">
                                {s.room_name ?? "—"}
                                {s._can.update ? ` · ${s.enrolled}/${s.capacity ?? "?"}` : ""}
                              </div>
                              {/* Rendered from _can, never from a role check. */}
                              {(s._can.sign || s._can.update) && (
                                <div className="mt-1.5 flex gap-1.5">
                                  {/* C'était un `span` : le contrôle avait l'apparence d'un
                                      bouton et ne menait nulle part. Il conduit maintenant
                                      à la page d'émargement, qui s'ouvre sur le jour même. */}
                                  {s._can.sign && (
                                    <Link
                                      to="/learn/emargement"
                                      className="border-current/20 rounded border px-1.5 py-0.5 text-[11px] hover:bg-current/5"
                                    >
                                      Émarger
                                    </Link>
                                  )}
                                  {s._can.update && (
                                    <span className="border-current/20 rounded border px-1.5 py-0.5 text-[11px]">
                                      Modifier
                                    </span>
                                  )}
                                </div>
                              )}
                              {s.status === "cancelled" && (
                                <div className="mt-1 text-[11px] text-amber-500">Annulé</div>
                              )}
                            </div>
                          ))
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {/* L'abonnement ICS existait côté API (`POST /calendar/token`) et n'était exposé
          nulle part. Un planning qu'on relit dans son propre agenda est celui qu'on relit
          vraiment — et le flux porte la portée du profil, donc chacun ne voit que ses
          propres créneaux. Émettre un jeton révoque le précédent : c'est ainsi qu'on
          reprend la main sur un lien partagé par erreur. */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-3 py-4 text-sm">
          <button
            type="button"
            onClick={() => {
              setIcsErreur(null);
              void issueCalendarToken()
                .then((r) => setIcs(r.url))
                .catch((e) => setIcsErreur((e as Error).message));
            }}
            className="border-current/25 rounded border px-3 py-1.5 hover:bg-current/5"
          >
            {ics ? "Régénérer mon lien d'agenda" : "S'abonner depuis mon agenda"}
          </button>
          {ics && (
            <input
              readOnly
              value={ics}
              onFocus={(e) => e.currentTarget.select()}
              className="border-current/20 min-w-0 flex-1 rounded border bg-transparent px-2 py-1.5 font-mono text-xs"
              aria-label="Lien d'abonnement à copier dans votre agenda"
            />
          )}
          <span className="text-text-secondary text-xs">
            {ics
              ? "Collez ce lien dans Google Agenda, Outlook ou Apple Calendrier. Régénérer annule le lien précédent."
              : "Vos créneaux, à jour, dans l'agenda que vous utilisez déjà."}
          </span>
          {icsErreur && <span className="text-xs text-red-400">{icsErreur}</span>}
        </CardContent>
      </Card>

      <LiensLearn />

      <p className="text-text-secondary text-xs">
        Même écran pour tous les profils. Le nombre de créneaux affichés diffère parce que la
        base filtre, pas parce que cette page teste un rôle.
      </p>
    </div>
  );
}
