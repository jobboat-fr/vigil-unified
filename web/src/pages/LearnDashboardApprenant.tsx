import { useCallback, useEffect, useState } from "react";
import { Skeleton } from "@/components/EmptyState";
import { Link } from "react-router-dom";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import {
  getCalendar,
  getSessions,
  getGradebook,
  LearnError,
  type Slot,
  type Session,
  type GradeRow,
} from "@/lib/learn";
import { RejoindreSalle } from "@/components/RejoindreSalle";
import { isoDay } from "@/lib/day";
import { expliquerCourt } from "@/lib/refus";

/**
 * Le tableau de bord de l'apprenant.
 *
 * Il existe parce que l'écran commun ne pouvait pas convenir aux deux. Celui de
 * l'organisme est une liste de travail : réclamations ouvertes au titre de l'indicateur 31,
 * dossiers d'audit incomplets, apprenants à risque, « à régler avant d'accueillir un second
 * organisme ». Un stagiaire y lisait le tableau de bord de quelqu'un d'autre — des chiffres
 * exacts, tous sans objet pour lui, et dont certains ne le regardent pas.
 *
 * **Ce n'est pas un filtrage de rôle déguisé.** La règle du fichier voisin — ne pas
 * rejouer en TypeScript un tri que la base fait déjà — tient toujours : RLS restreint les
 * *lignes*, et il continue de le faire ici. Ce qui change n'est pas le périmètre des
 * données, ce sont les *questions posées*. « Combien de copies restent à corriger » n'est
 * pas une question plus large pour un apprenant, c'est une question qui n'est pas la
 * sienne. Aucune requête de cette page ne demande davantage que ce que le profil peut voir.
 *
 * Trois questions, dans l'ordre où elles se posent un lundi matin : où dois-je aller et
 * quand, où en suis-je, et qu'est-ce que j'ai obtenu.
 */

const JOURS = ["dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi"];
const MOIS = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

/** « lundi 26 octobre » — les dates de LEARN sont civiles, on les lit telles quelles. */
function dateLongue(iso: string): string {
  const [a, m, j] = iso.split("-").map(Number);
  const d = new Date(a, m - 1, j);
  return `${JOURS[d.getDay()]} ${j} ${MOIS[m - 1]}`;
}

function heure(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
}

function joursRestants(iso: string): number {
  const [a, m, j] = iso.split("-").map(Number);
  const cible = new Date(a, m - 1, j);
  const today = new Date();
  const zero = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((cible.getTime() - zero.getTime()) / 86_400_000);
}

function quand(iso: string): string {
  const n = joursRestants(iso);
  if (n === 0) return "aujourd'hui";
  if (n === 1) return "demain";
  if (n < 0) return dateLongue(iso);
  return `dans ${n} jours`;
}

export default function LearnDashboardApprenant() {
  const [creneaux, setCreneaux] = useState<Slot[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [notes, setNotes] = useState<GradeRow[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  const [indisponible, setIndisponible] = useState(false);
  const [charge, setCharge] = useState(false);

  const load = useCallback(async () => {
    // Quatre-vingt-dix jours devant : assez pour voir la prochaine session même quand
    // elle n'ouvre que le mois suivant, ce qui est le cas courant en formation.
    const debut = isoDay();
    const fin = isoDay(new Date(Date.now() + 90 * 86_400_000));
    try {
      const [cal, ses, grad] = await Promise.all([
        getCalendar(debut, fin).catch(() => ({ items: [] as Slot[] })),
        getSessions().catch(() => ({ items: [] as Session[] })),
        getGradebook().catch(() => ({ items: [] as GradeRow[] })),
      ]);
      setCreneaux(
        [...cal.items]
          .filter((s) => s.status !== "cancelled")
          .sort((a, b) => a.starts_at.localeCompare(b.starts_at)),
      );
      setSessions(ses.items);
      setNotes(grad.items.filter((g) => g.score !== null));
      setErreur(null);
    } catch (e) {
      if (e instanceof LearnError && e.unavailable) setIndisponible(true);
      else setErreur(expliquerCourt(e));
    } finally {
      setCharge(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (indisponible) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-text-secondary">
          La plateforme de formation n&apos;est pas disponible sur cet environnement.
        </CardContent>
      </Card>
    );
  }

  const prochain = creneaux[0];
  const suivants = creneaux.slice(1, 5);
  const reussies = notes.filter((n) => n.passed === true).length;

  return (
    <div className="flex flex-col gap-6">
      {/* ── Le prochain rendez-vous ────────────────────────────────────────────
          Mis en premier et en grand parce que c'est la seule chose qu'un stagiaire
          vient vérifier entre deux journées : où, quand, avec qui. */}
      <Card className={prochain ? "border-current/25" : undefined}>
        <CardHeader>
          <CardTitle>Ma prochaine journée</CardTitle>
        </CardHeader>
        <CardContent>
          {!charge ? (
            // La forme de ce qui arrive — une date, puis l'horaire et le lieu — plutôt
            // qu'un mot : la carte ne change plus de hauteur quand la réponse tombe.
            <div className="flex flex-col gap-2 py-1" role="status" aria-busy="true" aria-label="Chargement de votre prochaine journée">
              <Skeleton className="h-7 w-52 max-w-full" />
              <Skeleton className="h-4 w-72 max-w-full" />
            </div>
          ) : !prochain ? (
            <div className="py-4">
              <p className="text-sm">Aucun créneau planifié dans les trois prochains mois.</p>
              <p className="text-text-secondary mt-1 text-xs">
                Dès qu&apos;une session vous est ouverte, elle apparaît ici et dans votre
                calendrier.
              </p>
            </div>
          ) : (
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
              <div>
                <div className="text-xl font-semibold">{dateLongue(prochain.on_date)}</div>
                <div className="text-text-secondary mt-0.5 text-sm tabular-nums">
                  {heure(prochain.starts_at)} – {heure(prochain.ends_at)}
                  {prochain.room_name ? ` · ${prochain.room_name}` : ""}
                  {prochain.formateur_name ? ` · ${prochain.formateur_name}` : ""}
                </div>
                {prochain.title && <div className="mt-1 text-sm">{prochain.title}</div>}
              </div>
              <div className="flex items-center gap-3 text-sm font-medium">
                {quand(prochain.on_date)}
                <RejoindreSalle slot={prochain} />
              </div>
            </div>
          )}

          {suivants.length > 0 && (
            <ul className="mt-4 space-y-1.5 border-t border-current/10 pt-3 text-sm">
              {suivants.map((s) => (
                <li key={s.id} className="flex flex-wrap items-baseline gap-x-3">
                  <span className="tabular-nums">{dateLongue(s.on_date)}</span>
                  <span className="text-text-secondary tabular-nums text-xs">
                    {heure(s.starts_at)} – {heure(s.ends_at)}
                    {s.room_name ? ` · ${s.room_name}` : ""}
                  </span>
                  <RejoindreSalle slot={s} compact />
                </li>
              ))}
            </ul>
          )}

          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            <Link to="/learn/calendar" className="underline underline-offset-4">
              Mon calendrier
            </Link>
            <Link to="/learn/emargement" className="underline underline-offset-4">
              Signer ma présence
            </Link>
          </div>
        </CardContent>
      </Card>

      {/* ── Trois repères, et rien de l'organisme ───────────────────────────── */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <CardContent className="py-4">
            <div className="text-2xl font-semibold tabular-nums">{sessions.length}</div>
            <div className="mt-0.5 text-sm">Mes formations</div>
            <div className="text-text-secondary mt-1 text-xs">sessions où je suis inscrit</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="text-2xl font-semibold tabular-nums">{creneaux.length}</div>
            <div className="mt-0.5 text-sm">Journées à venir</div>
            <div className="text-text-secondary mt-1 text-xs">sur les 90 prochains jours</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="text-2xl font-semibold tabular-nums">
              {reussies}
              <span className="text-text-secondary text-base font-normal">/{notes.length}</span>
            </div>
            <div className="mt-0.5 text-sm">Évaluations réussies</div>
            <div className="text-text-secondary mt-1 text-xs">
              {notes.length === 0 ? "aucune copie rendue" : "sur mes copies corrigées"}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Mes formations ─────────────────────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>Mes formations</CardTitle>
        </CardHeader>
        <CardContent>
          {sessions.length === 0 ? (
            <p className="text-text-secondary py-6 text-center text-sm">
              Vous n&apos;êtes inscrit à aucune session pour le moment.
            </p>
          ) : (
            <ul className="space-y-2.5 text-sm">
              {sessions.map((s) => (
                <li key={s.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="font-medium">{s.program_title ?? s.title ?? s.code}</span>
                  <span className="text-text-secondary tabular-nums text-xs">
                    {dateLongue(s.starts_on)} → {dateLongue(s.ends_on)}
                  </span>
                  <span className="text-text-secondary text-xs">
                    {s.modality}
                    {s.place ? ` · ${s.place}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 text-sm">
            <Link to="/learn/parcours" className="underline underline-offset-4">
              Voir mon parcours
            </Link>
          </div>
        </CardContent>
      </Card>

      {/* ── Mes résultats ──────────────────────────────────────────────────────
          Lisible depuis la migration 0029 : l'apprenant avait `evaluation · create`
          sans `evaluation · read`, donc il rendait des copies qu'il ne pouvait pas
          relire. */}
      <Card>
        <CardHeader>
          <CardTitle>Mes résultats</CardTitle>
        </CardHeader>
        <CardContent>
          {notes.length === 0 ? (
            <p className="text-text-secondary py-6 text-center text-sm">
              Aucune copie corrigée pour l&apos;instant.
            </p>
          ) : (
            <ul className="space-y-2 text-sm">
              {notes.slice(0, 8).map((g) => (
                <li
                  key={`${g.session_id}-${g.assessment_title}-${g.attempt_no}`}
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-1"
                >
                  <span className="font-medium">{g.assessment_title ?? g.assessment_kind}</span>
                  <span className="tabular-nums">
                    {g.score}
                    {g.max_score != null ? ` / ${g.max_score}` : ""}
                  </span>
                  {g.passed != null && (
                    <span className={g.passed ? "text-xs" : "text-xs text-amber-500"}>
                      {g.passed ? "acquis" : "non acquis"}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            <Link to="/learn/acquis" className="underline underline-offset-4">
              Mes acquis
            </Link>
            <Link to="/learn/coffre" className="underline underline-offset-4">
              Mes attestations
            </Link>
          </div>
        </CardContent>
      </Card>

      {erreur && <p className="text-sm text-red-400">{erreur}</p>}
    </div>
  );
}
