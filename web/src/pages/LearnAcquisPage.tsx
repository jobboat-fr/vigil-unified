import { useCallback, useEffect, useMemo, useState } from "react";
import { SqueletteEcran } from "@/components/EmptyState";
import { LiensLearn } from "@/components/LiensLearn";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import {
  getGradebook,
  getBlocs,
  getReviewQueue,
  getSessions,
  type GradeRow,
  type BlocRow,
  type Session,
} from "@/lib/learn";
import { expliquerCourt } from "@/lib/refus";
import { useLearnRole } from "@/lib/supabase";

/**
 * Les acquis — ce que chaque apprenant a obtenu, et ce qui reste à corriger.
 *
 * Un apprenant y lit ses propres résultats ; un formateur ceux de ses sessions ; la
 * direction et l'auditeur ceux de l'organisme. Un seul écran : c'est la vue
 * `learn_gradebook`, filtrée par la RLS, qui décide des lignes — cette page ne teste
 * jamais un rôle.
 *
 * Pourquoi cet écran existe, au-delà du confort : l'indicateur 3 demande qu'une action
 * certifiante soit évaluée, et l'indicateur 1 qu'un taux publié soit vérifiable avec la
 * population qui l'a produit. Les deux chiffres en tête sont calculés sur les lignes
 * affichées, jamais saisis à la main — et le nombre de tentatives qui les fonde est écrit
 * à côté, parce qu'un taux sans son effectif n'est pas vérifiable.
 *
 * Les blocs de compétences ne s'affichent que pour un organisme qui en produit : une
 * section vide dirait à tort qu'il manque quelque chose.
 */

const KIND: Record<string, string> = {
  positionnement: "Positionnement",
  acquis_entree: "Acquis à l'entrée",
  acquis_sortie: "Acquis à la sortie",
  examen: "Examen",
};

function pct(v: number | null) {
  return v == null ? "—" : `${Math.round(Number(v))} %`;
}

function quand(s: string | null) {
  if (!s) return "—";
  const d = new Date(s);
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

export default function LearnAcquisPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [grades, setGrades] = useState<GradeRow[] | null>(null);
  const [blocs, setBlocs] = useState<BlocRow[]>([]);
  const [queue, setQueue] = useState<GradeRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [g, b, q] = await Promise.all([
        getGradebook(sessionId || undefined),
        getBlocs(sessionId || undefined).catch(() => ({ items: [] as BlocRow[] })),
        getReviewQueue().catch(() => ({ items: [] as GradeRow[] })),
      ]);
      setGrades(g.items);
      setBlocs(b.items);
      setQueue(q.items);
    } catch (e) {
      setGrades([]);
      setError(expliquerCourt(e, "vos acquis"));
    }
  }, [sessionId]);

  useEffect(() => {
    getSessions()
      .then((r) => setSessions(r.items))
      .catch(() => setSessions([]));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Les deux chiffres publiables, calculés sur ce qui est affiché — et jamais séparés de
  // l'effectif qui les produit.
  const stats = useMemo(() => {
    const notes = (grades ?? []).filter((g) => g.percent != null);
    const juges = (grades ?? []).filter((g) => g.passed != null);
    const reussite = juges.length
      ? Math.round((juges.filter((g) => g.passed).length / juges.length) * 100)
      : null;
    const moyenne = notes.length
      ? Math.round(notes.reduce((a, g) => a + Number(g.percent), 0) / notes.length)
      : null;
    const apprenants = new Set((grades ?? []).map((g) => g.profile_id)).size;
    return { reussite, moyenne, juges: juges.length, notes: notes.length, apprenants };
  }, [grades]);

  // Vrai quand tout le périmètre visible tient en une personne. C'est le cas de
  // l'apprenant, qui ne voit que lui — mais la condition porte sur les données, pas sur
  // le rôle : la page continue de ne jamais tester un profil, conformément à son en-tête.
  const { role } = useLearnRole();

  const solo = useMemo(() => {
    const ids = new Set((grades ?? []).map((g) => g.profile_id));
    // Au moins deux personnes dans le périmètre : c'est un suivi d'organisme, sans
    // ambiguïté possible.
    if (ids.size > 1) return false;
    // Une seule : c'est la personne elle-même.
    if (ids.size === 1) return true;
    // Zéro ligne, et là les données ne disent rien — ni « c'est vous », ni « c'est votre
    // groupe ». `<= 1` tranchait pour l'apprenant, ce qui est juste pour lui et faux pour
    // un formateur : le menu lui promet « Suivi des acquis » et la page lui répondait
    // « Mes résultats ». Constaté en parcourant l'application avec un vrai compte
    // formateur, sur un compte sans session attribuée.
    //
    // Le rôle sert donc uniquement d'arbitre à zéro ligne. La page continue de ne jamais
    // tester un profil, et dès qu'une donnée existe c'est elle qui décide.
    //
    // La liste est **positive** : seul l'apprenant consulte ses propres résultats. Écrite
    // en négatif (« tout sauf formateur, admin, auditeur… »), elle rangeait l'entreprise
    // du côté « mes résultats » — or une entreprise cliente regarde ceux de ses salariés,
    // jamais les siens : elle ne passe aucune évaluation. Une liste d'exclusions oublie
    // toujours quelqu'un, et c'est le rôle ajouté en dernier qui en fait les frais.
    return role === "apprenant";
  }, [grades, role]);

  const parApprenant = useMemo(() => {
    const m = new Map<string, GradeRow[]>();
    for (const g of grades ?? []) {
      const k = g.profile_id;
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(g);
    }
    return [...m.entries()].sort((a, b) =>
      (a[1][0].apprenant_name ?? "").localeCompare(b[1][0].apprenant_name ?? ""),
    );
  }, [grades]);

  if (grades === null) {
    return <SqueletteEcran lignes={6} />;
  }

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-6">
      {error && (
        <Card>
          <CardContent className="py-4 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <label className="text-[11px] uppercase tracking-wider opacity-60" htmlFor="acq-session">
          Session
        </label>
        <select
          id="acq-session"
          value={sessionId}
          onChange={(e) => setSessionId(e.target.value)}
          className="rounded-md border px-2 py-1.5 text-sm"
          style={{ borderColor: "var(--color-border)", background: "var(--color-card)" }}
        >
          <option value="">Toutes les sessions</option>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.code ? `${s.code} — ` : ""}{s.title ?? s.program_title ?? "Session"}
            </option>
          ))}
        </select>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Chiffre
          valeur={stats.reussite == null ? "—" : `${stats.reussite} %`}
          libelle="Taux de réussite"
          note={`sur ${stats.juges} tentative${stats.juges > 1 ? "s" : ""} évaluée${stats.juges > 1 ? "s" : ""}${solo ? "" : " — indicateur 1"}`}
        />
        <Chiffre
          valeur={stats.moyenne == null ? "—" : `${stats.moyenne} %`}
          libelle="Score moyen"
          note={`sur ${stats.notes} note${stats.notes > 1 ? "s" : ""}`}
        />
        {solo ? (
          <Chiffre
            valeur={String(stats.notes)}
            libelle="Évaluations passées"
            note={stats.notes === 0 ? "aucune tentative soumise" : "tentatives notées"}
          />
        ) : (
          <Chiffre
            valeur={String(stats.apprenants)}
            libelle="Apprenants évalués"
            note={queue.length ? `${queue.length} copie${queue.length > 1 ? "s" : ""} à corriger` : "aucune copie en attente"}
          />
        )}
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">{solo ? "Mes résultats" : "Résultats par apprenant"}</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {parApprenant.length === 0 ? (
            <p className="py-6 text-center text-sm opacity-55">
              Aucune évaluation passée sur ce périmètre. Les résultats apparaissent dès
              qu&apos;une tentative est soumise.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider opacity-55">
                    {!solo && <th className="py-2 pr-3 font-medium">Apprenant</th>}
                    <th className="py-2 pr-3 font-medium">Évaluation</th>
                    <th className="py-2 pr-3 font-medium">Type</th>
                    <th className="py-2 pr-3 font-medium">Tentative</th>
                    <th className="py-2 pr-3 font-medium">Score</th>
                    <th className="py-2 pr-3 font-medium">Résultat</th>
                    <th className="py-2 pr-3 font-medium">Soumise le</th>
                  </tr>
                </thead>
                <tbody>
                  {parApprenant.map(([id, rows]) =>
                    rows.map((g, i) => (
                      <tr key={`${id}-${g.assessment_title}-${g.attempt_no}`} className="border-t border-current/10">
                        {!solo && (
                          <td className="py-2 pr-3">{i === 0 ? (g.apprenant_name ?? "—") : ""}</td>
                        )}
                        <td className="py-2 pr-3">{g.assessment_title ?? "—"}</td>
                        <td className="py-2 pr-3 opacity-70">{KIND[g.assessment_kind] ?? g.assessment_kind}</td>
                        <td className="py-2 pr-3 tabular-nums opacity-70">{g.attempt_no}</td>
                        <td className="py-2 pr-3 tabular-nums">{pct(g.percent)}</td>
                        <td className="py-2 pr-3">
                          {g.review_status === "pending" ? (
                            <span className="opacity-60">à corriger</span>
                          ) : g.passed == null ? (
                            <span className="opacity-50">—</span>
                          ) : (
                            <span style={{ color: g.passed ? "var(--color-success)" : "var(--color-destructive)" }}>
                              {g.passed ? "Acquis" : "Non acquis"}
                            </span>
                          )}
                          {g.level && <span className="opacity-50"> · {g.level}</span>}
                        </td>
                        <td className="py-2 pr-3 tabular-nums opacity-70">{quand(g.submitted_at)}</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {blocs.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Par bloc de compétences</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wider opacity-55">
                    {!solo && <th className="py-2 pr-3 font-medium">Apprenant</th>}
                    <th className="py-2 pr-3 font-medium">Bloc</th>
                    <th className="py-2 pr-3 font-medium">Questions</th>
                    <th className="py-2 pr-3 font-medium">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {blocs.map((b, i) => (
                    <tr key={`${b.profile_id}-${b.bloc}-${i}`} className="border-t border-current/10">
                      {!solo && <td className="py-2 pr-3">{b.apprenant_name ?? "—"}</td>}
                      <td className="py-2 pr-3">{b.bloc}</td>
                      <td className="py-2 pr-3 tabular-nums opacity-70">{b.questions}</td>
                      <td className="py-2 pr-3 tabular-nums">{pct(b.percent)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <LiensLearn />

      <p className="px-1 text-[11px] leading-relaxed opacity-45">
        Les taux ci-dessus sont calculés sur les lignes affichées et publiés avec
        l&apos;effectif qui les produit : l&apos;indicateur 1 demande qu&apos;un taux soit
        vérifiable, pas seulement affiché. Ce que vous voyez dépend de votre profil —
        c&apos;est la base qui filtre.
      </p>
    </div>
  );
}

function Chiffre({ valeur, libelle, note }: { valeur: string; libelle: string; note: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="text-2xl font-semibold tabular-nums">{valeur}</div>
        <div className="mt-0.5 text-sm">{libelle}</div>
        <div className="mt-0.5 text-[11px] opacity-55">{note}</div>
      </CardContent>
    </Card>
  );
}
