import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { getCalendar, getSessions, getReviewQueue, LearnError, type Slot, type Session } from "@/lib/learn";
import { RejoindreSalle } from "@/components/RejoindreSalle";
import { isoDay } from "@/lib/day";

/**
 * Le tableau de bord du formateur.
 *
 * L'écran commun est celui de l'organisme (réclamations, dossiers d'audit, conformité de la
 * plateforme) : un formateur y lisait le travail de la direction. Ses questions sont
 * ailleurs : où et quand j'interviens, quelles sessions j'anime, quelles copies m'attendent.
 * Les lignes restent celles que la base lui laisse voir — ses créneaux, ses sessions.
 */

const heure = (iso: string) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
const jour = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });

export default function LearnDashboardFormateur() {
  const [creneaux, setCreneaux] = useState<Slot[] | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [copies, setCopies] = useState(0);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(async () => {
    const debut = new Date();
    const fin = new Date(debut.getTime() + 21 * 86_400_000);
    const [c, s, q] = await Promise.allSettled([
      getCalendar(isoDay(debut), isoDay(fin)),
      getSessions(),
      getReviewQueue(),
    ]);
    if (c.status === "fulfilled") setCreneaux(c.value.items.filter((x) => x.status !== "cancelled"));
    else {
      setCreneaux([]);
      setErreur(c.reason instanceof LearnError ? c.reason.message : "Chargement impossible.");
    }
    if (s.status === "fulfilled") setSessions(s.value.items.filter((x) => x.status === "planned" || x.status === "running"));
    if (q.status === "fulfilled") setCopies(q.value.items.length);
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  if (creneaux === null) return <p className="p-6 text-sm opacity-60">Chargement…</p>;

  const aujourdhui = isoDay(new Date());
  const duJour = creneaux.filter((x) => x.on_date === aujourdhui);

  return (
    <div className="space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Mon activité de formateur</h1>
        <p className="mt-1 text-sm opacity-70">Vos interventions des trois prochaines semaines, vos sessions et vos corrections.</p>
      </header>

      {erreur ? (
        <Card>
          <CardContent className="p-4 text-sm">{erreur}</CardContent>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <Link to="/learn/emargement">
          <Card className="h-full hover:ring-1 hover:ring-current/30">
            <CardContent className="p-4">
              <p className="text-3xl font-semibold">{duJour.length}</p>
              <p className="text-sm opacity-70">créneau{duJour.length > 1 ? "x" : ""} aujourd&apos;hui · émargement</p>
            </CardContent>
          </Card>
        </Link>
        <Link to="/learn/parcours">
          <Card className="h-full hover:ring-1 hover:ring-current/30">
            <CardContent className="p-4">
              <p className="text-3xl font-semibold">{sessions.length}</p>
              <p className="text-sm opacity-70">session{sessions.length > 1 ? "s" : ""} à venir ou en cours</p>
            </CardContent>
          </Card>
        </Link>
        <Link to="/learn/acquis">
          <Card className="h-full hover:ring-1 hover:ring-current/30">
            <CardContent className="p-4">
              <p className="text-3xl font-semibold">{copies}</p>
              <p className="text-sm opacity-70">copie{copies > 1 ? "s" : ""} à corriger</p>
            </CardContent>
          </Card>
        </Link>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Mes prochaines interventions</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {creneaux.length === 0 ? (
            <p className="p-6 text-sm opacity-70">Aucun créneau ne vous est attribué dans les trois prochaines semaines.</p>
          ) : (
            <ul className="divide-y divide-current/10 text-sm">
              {creneaux.slice(0, 12).map((x) => (
                <li key={x.id} className="flex flex-wrap justify-between gap-2 px-4 py-2.5">
                  <span className="font-medium capitalize">{jour(x.on_date)}</span>
                  <span className="opacity-70">
                    {heure(x.starts_at)} – {heure(x.ends_at)} · {x.title ?? "Session"}
                    {x.room_name ? ` · ${x.room_name}` : ""} · {x.enrolled} inscrit{x.enrolled > 1 ? "s" : ""}
                  </span>
                  <span className="w-full sm:w-auto"><RejoindreSalle slot={x} compact /></span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <nav className="flex flex-wrap gap-x-4 gap-y-2 text-sm opacity-75">
        <Link to="/learn/calendar" className="hover:underline">Mon planning</Link>
        <Link to="/learn/emargement" className="hover:underline">Émargement</Link>
        <Link to="/learn/parcours" className="hover:underline">Mes sessions</Link>
        <Link to="/learn/acquis" className="hover:underline">Suivi des acquis</Link>
        <Link to="/learn/coffre" className="hover:underline">Documents</Link>
      </nav>
    </div>
  );
}
