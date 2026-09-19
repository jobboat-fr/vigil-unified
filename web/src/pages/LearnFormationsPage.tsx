import { useCallback, useEffect, useState } from "react";
import { SqueletteEcran } from "@/components/EmptyState";
import { LiensLearn } from "@/components/LiensLearn";
import { FormulaireProgramme, FormulaireSession } from "@/components/learn/Gestion";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import {
  getPrograms,
  getSessions,
  getCourses,
  getAssessments,
  getCourseOutline,
  LearnError,
  type Program,
  type Session,
  type Course,
  type Assessment,
  type Can,
} from "@/lib/learn";

/**
 * L'offre de formation, et tout ce qui s'y rattache.
 *
 * Une formation n'est pas une ligne de catalogue : c'est un programme, les sessions qui le
 * délivrent, les cours qu'on y suit et les évaluations qui le sanctionnent. Les quatre sont
 * réunis ici parce que séparés en quatre écrans, personne ne voit qu'un programme certifiant
 * n'a pas d'examen — et c'est exactement le genre de trou qu'un audit relève.
 *
 * Accessible à tous les rôles. Ce que chacun voit diffère parce que la base renvoie des
 * lignes différentes, pas parce que cette page interroge le rôle de l'appelant.
 */
export default function LearnFormationsPage() {
  const [programs, setPrograms] = useState<Program[] | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [exams, setExams] = useState<Assessment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [openCourse, setOpenCourse] = useState<string | null>(null);
  const [outline, setOutline] = useState<Record<string, { id: string; title: string }[]>>({});
  const [canProg, setCanProg] = useState<Can | null>(null);
  const [canSess, setCanSess] = useState<Can | null>(null);

  const load = useCallback(async () => {
    setError(null);
    // Settled, not all-or-nothing: a tenant with no course library should still see its
    // programmes rather than an error page.
    const [p, s, c, a] = await Promise.allSettled([
      getPrograms(),
      getSessions(),
      getCourses(),
      getAssessments(),
    ]);
    if (p.status === "fulfilled") {
      setPrograms(p.value.items);
      setCanProg(p.value._can ?? null);
    }
    else {
      setPrograms([]);
      setError(p.reason instanceof LearnError ? p.reason.message : "Chargement impossible.");
    }
    if (s.status === "fulfilled") {
      setSessions(s.value.items);
      setCanSess(s.value._can ?? null);
    }
    if (c.status === "fulfilled") setCourses(c.value.items);
    if (a.status === "fulfilled") setExams(a.value.items);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function toggleOutline(courseId: string) {
    if (openCourse === courseId) {
      setOpenCourse(null);
      return;
    }
    setOpenCourse(courseId);
    if (outline[courseId]) return;
    try {
      const r = await getCourseOutline(courseId);
      setOutline((m) => ({
        ...m,
        // `modules`, pas `items` : le plan revenait vide alors que l'appel renvoyait 200.
        [courseId]: r.modules.flatMap((mod) =>
          (mod.lessons ?? []).map((l) => ({ id: l.id, title: `${mod.title} · ${l.title}` })),
        ),
      }));
    } catch {
      setOutline((m) => ({ ...m, [courseId]: [] }));
    }
  }

  if (programs === null) {
    return <SqueletteEcran lignes={6} />;
  }

  return (
    <div className="space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Formations</h1>
        <p className="mt-1 text-sm opacity-70">
          Chaque programme avec ses sessions, ses cours et ses évaluations.
        </p>
      </header>

      {canProg?.create ? (
        <Card>
          <CardContent className="p-4">
            <details>
              <summary className="cursor-pointer text-sm font-medium">Nouveau programme</summary>
              <div className="mt-4">
                <FormulaireProgramme onCree={() => void load()} />
              </div>
            </details>
          </CardContent>
        </Card>
      ) : null}

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

      {programs.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm opacity-70">
            Aucun programme. Une formation se crée avec son intitulé exact, sa durée et ses
            objectifs évaluables — les trois mentions qu&apos;un audit vérifie en premier.
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-5 lg:grid-cols-2 xl:grid-cols-3">
        {programs.map((p) => {
          const ps = sessions.filter((s) => s.program_id === p.id);
          const pc = courses.filter((c) => c.program_id === p.id);
          const pe = exams.filter((e) => e.program_id === p.id);
          // Indicator 3: a certifying programme with nothing that sanctions it is a
          // finding. Surfaced here rather than left for an auditor to notice.
          const certifWithoutExam = p.certifiante && pe.length === 0;
          return (
            <Card key={p.id} className="flex flex-col">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-start justify-between gap-3 text-base">
                  <span className="min-w-0">{p.title}</span>
                  {!p.published ? (
                    <span className="shrink-0 rounded px-2 py-0.5 text-[11px] opacity-70 ring-1 ring-current">
                      brouillon
                    </span>
                  ) : null}
                </CardTitle>
                <p className="text-xs opacity-70">
                  {p.duration_hours} h · {p.modality}
                  {p.certifiante ? ` · certifiante${p.rncp_code ? ` (${p.rncp_code})` : ""}` : ""}
                  {p.version > 1 ? ` · v${p.version}` : ""}
                </p>
              </CardHeader>

              <CardContent className="flex-1 space-y-4 text-sm">
                {certifWithoutExam ? (
                  <p className="rounded px-2 py-1.5 text-xs ring-1 ring-current">
                    Programme certifiant sans évaluation rattachée — indicateur 3.
                  </p>
                ) : null}

                {canSess?.create ? (
                  <details>
                    <summary className="cursor-pointer text-xs font-medium opacity-80">Planifier une session</summary>
                    <div className="mt-3">
                      <FormulaireSession programId={p.id} modalite={p.modality} onCree={() => void load()} />
                    </div>
                  </details>
                ) : null}

                <Group title="Sessions" count={ps.length}>
                  {ps.slice(0, 4).map((s) => (
                    <li key={s.id} className="flex justify-between gap-3 py-1">
                      <span className="min-w-0 truncate">{s.code || s.title || "Session"}</span>
                      <span className="shrink-0 text-xs opacity-60">
                        {frDate(s.starts_on)} · {s.status}
                      </span>
                    </li>
                  ))}
                </Group>

                <Group title="Cours" count={pc.length}>
                  {pc.map((c) => (
                    <li key={c.id} className="py-1">
                      <button
                        type="button"
                        className="w-full text-left hover:underline"
                        onClick={() => void toggleOutline(c.id)}
                        aria-expanded={openCourse === c.id}
                      >
                        {c.title}
                      </button>
                      {openCourse === c.id ? (
                        <ul className="mt-1 space-y-0.5 pl-3 text-xs opacity-70">
                          {(outline[c.id] ?? []).length === 0 ? (
                            <li>Aucune leçon publiée.</li>
                          ) : (
                            outline[c.id].map((l) => <li key={l.id}>{l.title}</li>)
                          )}
                        </ul>
                      ) : null}
                    </li>
                  ))}
                </Group>

                <Group title="Évaluations" count={pe.length}>
                  {pe.map((e) => (
                    <li key={e.id} className="flex justify-between gap-3 py-1">
                      <span className="min-w-0 truncate">{e.title}</span>
                      <span className="shrink-0 text-xs opacity-60">{e.kind}</span>
                    </li>
                  ))}
                </Group>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <LiensLearn />
    </div>
  );
}

function Group({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider opacity-60">
        {title} ({count})
      </h3>
      {count === 0 ? (
        <p className="text-xs opacity-50">—</p>
      ) : (
        <ul className="divide-y divide-current/10">{children}</ul>
      )}
    </section>
  );
}

function frDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("fr-FR");
}
