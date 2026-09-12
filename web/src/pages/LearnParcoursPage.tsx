import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import {
import { LiensLearn } from "@/components/LiensLearn";
  getSessions,
  getSession,
  getPrograms,
  getCourses,
  getCourseOutline,
  getAssessments,
  LearnError,
  type Session,
  type SessionDetail,
  type Program,
  type Course,
  type Assessment,
  type CourseModule,
} from "@/lib/learn";

/**
 * Le tableau des parcours — les sessions par état, et tout ce qui s'y rattache.
 *
 * Le planning répond à « quand » ; cette page répond à « où en est chaque formation ».
 * Ce sont deux questions différentes, et les confondre donne un agenda que personne ne
 * lit pour piloter.
 *
 * Les colonnes sont les états que la base autorise — `learn_sessions_status_check` les
 * énumère, et cette page ne peut donc pas en inventer un sixième. Une carte dépliée va
 * chercher le détail de la session (programme, formateurs, inscrits, créneaux) puis les
 * cours et les évaluations du même programme : « la formation et tout ce qui va avec »,
 * sur un seul écran.
 *
 * Pas de glisser-déposer. Faire avancer une session d'un état à l'autre demanderait une
 * route qui n'existe pas côté API ; un tableau où l'on peut saisir une carte sans que rien
 * ne soit enregistré est pire qu'un tableau qui ne le propose pas. L'action réellement
 * disponible — annuler, avec un motif — est offerte quand `_can.cancel` l'autorise.
 *
 * Un écran pour tous les profils : la RLS décide du nombre de cartes, pas ce fichier.
 */

const COLUMNS: { key: string; label: string; hint: string }[] = [
  { key: "draft", label: "Brouillon", hint: "pas encore ouverte aux inscriptions" },
  { key: "planned", label: "Planifiée", hint: "dates posées, inscriptions ouvertes" },
  { key: "running", label: "En cours", hint: "émargement en cours" },
  { key: "finished", label: "Terminée", hint: "dossier à clore" },
  { key: "cancelled", label: "Annulée", hint: "conservée pour la traçabilité" },
];

const MODALITE: Record<string, string> = {
  presentiel: "Présentiel",
  distanciel: "Distanciel",
  mixte: "Mixte",
};

function jour(d: string) {
  const [y, m, j] = d.split("-");
  return `${j}/${m}/${y.slice(2)}`;
}

export default function LearnParcoursPage() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [programs, setPrograms] = useState<Program[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, SessionDetail>>({});
  const [outline, setOutline] = useState<Record<string, CourseModule[]>>({});

  const load = useCallback(async () => {
    try {
      const [s, p, c, a] = await Promise.all([
        getSessions(),
        getPrograms().catch(() => ({ items: [] as Program[] })),
        getCourses().catch(() => ({ items: [] as Course[] })),
        getAssessments().catch(() => ({ items: [] as Assessment[] })),
      ]);
      setSessions(s.items);
      setPrograms(p.items);
      setCourses(c.items);
      setAssessments(a.items);
      setError(null);
    } catch (e) {
      setSessions([]);
      setError(e instanceof LearnError ? e.message : "Chargement impossible.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const byStatus = useMemo(() => {
    const m: Record<string, Session[]> = {};
    for (const col of COLUMNS) m[col.key] = [];
    for (const s of sessions ?? []) (m[s.status] ??= []).push(s);
    return m;
  }, [sessions]);

  async function toggle(s: Session) {
    if (open === s.id) {
      setOpen(null);
      return;
    }
    setOpen(s.id);
    if (detail[s.id]) return;
    try {
      const d = await getSession(s.id);
      setDetail((m) => ({ ...m, [s.id]: d }));
    } catch {
      /* la carte reste ouverte sur ce qu'elle savait déjà */
    }
  }

  async function loadOutline(courseId: string) {
    if (outline[courseId]) return;
    try {
      const r = await getCourseOutline(courseId);
      setOutline((m) => ({ ...m, [courseId]: r.modules }));
    } catch {
      setOutline((m) => ({ ...m, [courseId]: [] }));
    }
  }

  if (sessions === null) {
    return <p className="p-6 text-sm opacity-60">Chargement…</p>;
  }

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-6">
      {error && (
        <Card>
          <CardContent className="py-4 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      <div className="grid gap-3 lg:grid-cols-5 md:grid-cols-3 sm:grid-cols-2">
        {COLUMNS.map((col) => {
          const items = byStatus[col.key] ?? [];
          return (
            <section key={col.key} className="flex min-w-0 flex-col gap-2">
              <header className="flex items-baseline justify-between gap-2 px-1">
                <h2 className="text-[11px] font-semibold uppercase tracking-wider opacity-70">
                  {col.label}
                </h2>
                <span className="text-[11px] tabular-nums opacity-50">{items.length}</span>
              </header>
              <p className="px-1 text-[11px] leading-snug opacity-45">{col.hint}</p>

              <div className="flex flex-col gap-2">
                {items.length === 0 && (
                  <div className="rounded-lg border border-dashed border-current/15 p-3 text-center text-[11px] opacity-40">
                    Aucune
                  </div>
                )}

                {items.map((s) => {
                  const prog = programs.find((p) => p.id === s.program_id);
                  const d = detail[s.id];
                  const isOpen = open === s.id;
                  const progCourses = courses.filter((c) => c.program_id === s.program_id);
                  // Les évaluations rattachées au programme, plus celles de l'organisme
                  // entier — le test de positionnement n'appartient à aucun programme, il
                  // se passe avant l'inscription. L'omettre laissait « Évaluations (0) »
                  // sur une session qui en a bel et bien une.
                  const progAssessments = assessments.filter(
                    (a) => a.program_id === s.program_id || a.program_id == null,
                  );
                  return (
                    <Card key={s.id} className="overflow-hidden">
                      <button
                        type="button"
                        onClick={() => void toggle(s)}
                        aria-expanded={isOpen}
                        className="w-full text-left"
                      >
                        <CardHeader className="gap-1 pb-2">
                          <CardTitle className="text-sm leading-snug">
                            {s.title ?? prog?.title ?? "Session"}
                          </CardTitle>
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] opacity-60">
                            {s.code && <span className="font-mono">{s.code}</span>}
                            <span>
                              {jour(s.starts_on)} → {jour(s.ends_on)}
                            </span>
                            <span>{MODALITE[s.modality] ?? s.modality}</span>
                          </div>
                        </CardHeader>
                        <CardContent className="flex items-center justify-between gap-2 pb-3 text-[11px]">
                          <span className="opacity-60">
                            {s.enrolled ?? 0}/{s.capacity} inscrits
                          </span>
                          {prog?.certifiante && (
                            <span
                              className="rounded px-1.5 py-px text-[10px] font-medium"
                              style={{ background: "var(--color-accent)", color: "var(--color-accent-foreground)" }}
                            >
                              Certifiante
                            </span>
                          )}
                        </CardContent>
                      </button>

                      {isOpen && (
                        <div className="border-t border-current/10 px-4 py-3 text-[11px]">
                          <Bloc titre="Programme">
                            <p className="opacity-70">
                              {prog?.title ?? "—"}
                              {prog ? ` · ${prog.duration_hours} h` : ""}
                            </p>
                          </Bloc>

                          <Bloc titre={`Formateurs (${d?.formateurs?.length ?? 0})`}>
                            {d?.formateurs?.length
                              ? <ul className="opacity-70">{d.formateurs.map((f) => <li key={f.id}>{f.full_name ?? f.email}</li>)}</ul>
                              : <p className="opacity-45">Aucun créneau attribué.</p>}
                          </Bloc>

                          <Bloc titre={`Inscrits (${d?.learners?.length ?? 0})`}>
                            {d?.learners?.length
                              ? (
                                <ul className="opacity-70">
                                  {d.learners.map((l) => (
                                    <li key={l.enrollment_id}>
                                      {l.full_name ?? l.email}
                                      <span className="opacity-50"> · {l.status}</span>
                                      {l.company && <span className="opacity-50"> · {l.company}</span>}
                                    </li>
                                  ))}
                                </ul>
                              )
                              : <p className="opacity-45">Aucun inscrit.</p>}
                          </Bloc>

                          <Bloc titre={`Cours (${progCourses.length})`}>
                            {progCourses.length === 0 && <p className="opacity-45">Aucun cours rattaché au programme.</p>}
                            {progCourses.map((c) => (
                              <div key={c.id} className="mb-1">
                                <button
                                  type="button"
                                  className="text-left underline-offset-2 hover:underline"
                                  onClick={() => void loadOutline(c.id)}
                                >
                                  {c.title}
                                  {!c.published && <span className="opacity-50"> · brouillon</span>}
                                </button>
                                {outline[c.id] && (
                                  <ul className="mt-1 ml-3 border-l border-current/15 pl-2 opacity-70">
                                    {outline[c.id].length === 0 && <li className="opacity-50">Plan vide.</li>}
                                    {outline[c.id].map((mod) => (
                                      <li key={mod.id} className="mb-1">
                                        <span className="font-medium">{mod.position}. {mod.title}</span>
                                        {!mod.required && <span className="opacity-50"> · facultatif</span>}
                                        {mod.lessons?.length ? (
                                          <ul className="ml-3 opacity-75">
                                            {mod.lessons.map((l) => (
                                              <li key={l.id}>· {l.title}{l.duration_minutes ? ` (${l.duration_minutes} min)` : ""}</li>
                                            ))}
                                          </ul>
                                        ) : null}
                                      </li>
                                    ))}
                                  </ul>
                                )}
                              </div>
                            ))}
                          </Bloc>

                          <Bloc titre={`Évaluations (${progAssessments.length})`}>
                            {progAssessments.length === 0 && <p className="opacity-45">Aucune évaluation rattachée.</p>}
                            <ul className="opacity-70">
                              {progAssessments.map((a) => (
                                <li key={a.id}>
                                  {a.title}
                                  <span className="opacity-50"> · {a.kind.replace("_", " ")} · {a.duration_minutes} min</span>
                                  {a.program_id == null && (
                                    <span className="opacity-50"> · tout l&apos;organisme</span>
                                  )}
                                </li>
                              ))}
                            </ul>
                          </Bloc>

                          <Bloc titre={`Créneaux (${d?.slots?.length ?? 0})`}>
                            {d?.slots?.length
                              ? <p className="opacity-70">{d.slots.length} demi-journées planifiées — voir le planning et l&apos;émargement.</p>
                              : <p className="opacity-45">Aucun créneau généré.</p>}
                          </Bloc>
                        </div>
                      )}
                    </Card>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>

      <LiensLearn />

      <p className="px-1 text-[11px] leading-relaxed opacity-45">
        Les colonnes sont les états que la base autorise. Le nombre de cartes visibles
        dépend de votre profil : c&apos;est la base qui filtre, pas cette page.
      </p>
    </div>
  );
}

function Bloc({ titre, children }: { titre: string; children: React.ReactNode }) {
  return (
    <div className="mb-3 last:mb-0">
      <h3 className="mb-1 text-[10px] font-semibold uppercase tracking-wider opacity-50">{titre}</h3>
      {children}
    </div>
  );
}
