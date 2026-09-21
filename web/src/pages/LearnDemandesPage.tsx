import { useCallback, useEffect, useMemo, useState } from "react";
import { Skeleton, SqueletteEcran } from "@/components/EmptyState";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import {
  getLeads,
  getLead,
  getSessions,
  convertLead,
  refuseLead,
  type LeadDetail,
  type Session,
} from "@/lib/learn";
import { expliquerCourt } from "@/lib/refus";

const STATUT: Record<string, string> = {
  recue: "Reçue",
  positionnement_envoye: "Test envoyé",
  positionnement_fait: "Test passé",
  convertie: "Inscrite",
  refusee: "Refusée",
};

const NIVEAU: Record<string, string> = { debutant: "Débutant", intermediaire: "Intermédiaire", avance: "Avancé" };

const date = (s?: string | null) =>
  s ? new Date(s).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" }) : "—";

/**
 * Les demandes d'inscription venues du site, et ce que le candidat a répondu au test.
 *
 * L'organisme lit ici ce dont il a besoin pour décider : la formation et la semaine choisies,
 * le niveau, et surtout les réponses — le fil rouge, les documents, les aménagements. Les
 * actions (inscrire sur une session, refuser) ne s'affichent que si `_can` les accorde : un
 * auditeur lit, il ne décide pas.
 */
export default function LearnDemandesPage() {
  const [items, setItems] = useState<Record<string, unknown>[] | null>(null);
  const [filtre, setFiltre] = useState<string>("");
  const [selection, setSelection] = useState<string | null>(null);
  const [fiche, setFiche] = useState<LeadDetail | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sessionChoisie, setSessionChoisie] = useState("");
  const [motif, setMotif] = useState("");

  const charger = useCallback(async () => {
    setErreur(null);
    try {
      const r = await getLeads(filtre || undefined);
      setItems(r.items);
    } catch (e) {
      setItems([]);
      setErreur(expliquerCourt(e, "les demandes"));
    }
  }, [filtre]);

  useEffect(() => {
    void charger();
  }, [charger]);

  useEffect(() => {
    if (!selection) {
      setFiche(null);
      return;
    }
    setFiche(null);
    void getLead(selection)
      .then((f) => {
        setFiche(f);
        setSessionChoisie(f.session_id ?? "");
      })
      .catch((e) => setErreur(expliquerCourt(e, "cette fiche")));
  }, [selection]);

  useEffect(() => {
    void getSessions("planned").then((r) => setSessions(r.items)).catch(() => setSessions([]));
  }, []);

  const blocs = useMemo(() => {
    const m = new Map<string, LeadDetail["positioning_answers"]>();
    for (const r of fiche?.positioning_answers ?? []) {
      const k = r.bloc || "Réponses";
      m.set(k, [...(m.get(k) ?? []), r]);
    }
    return [...m.entries()];
  }, [fiche]);

  async function inscrire() {
    if (!fiche || !sessionChoisie) return;
    setBusy(true);
    setErreur(null);
    try {
      await convertLead(fiche.id, sessionChoisie);
      setSelection(null);
      await charger();
    } catch (e) {
      setErreur(expliquerCourt(e, "cette inscription"));
    }
    setBusy(false);
  }

  async function refuser() {
    if (!fiche || motif.trim().length < 5) return;
    setBusy(true);
    setErreur(null);
    try {
      await refuseLead(fiche.id, motif.trim());
      setMotif("");
      setSelection(null);
      await charger();
    } catch (e) {
      setErreur(expliquerCourt(e, "ce refus"));
    }
    setBusy(false);
  }

  if (items === null) return <SqueletteEcran lignes={6} />;

  const peutDecider = Boolean(fiche?._can?.create) && fiche?.status !== "convertie" && fiche?.status !== "refusee";
  const sessionsDuProgramme = sessions.filter((s) => !fiche?.program_id || s.program_id === fiche.program_id);

  return (
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Demandes d&apos;inscription</h1>
          <p className="mt-1 text-sm opacity-70">
            {items.length} demande{items.length > 1 ? "s" : ""} venue{items.length > 1 ? "s" : ""} du site · réponses au test de positionnement
          </p>
        </div>
        <select
          value={filtre}
          onChange={(e) => setFiltre(e.target.value)}
          className="rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm"
          aria-label="Filtrer par statut"
        >
          <option value="">Tous les statuts</option>
          {Object.entries(STATUT).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </header>

      {erreur ? (
        <Card>
          <CardContent className="p-4 text-sm">{erreur}</CardContent>
        </Card>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardContent className="p-0">
            {items.length === 0 ? (
              <p className="p-8 text-center text-sm opacity-70">Aucune demande.</p>
            ) : (
              <ul className="divide-y divide-current/10 text-sm">
                {items.map((l) => {
                  const id = String(l.id);
                  return (
                    <li key={id}>
                      <button
                        type="button"
                        onClick={() => setSelection(id)}
                        className={`flex w-full flex-col items-start gap-0.5 px-4 py-3 text-left hover:bg-current/5 ${selection === id ? "bg-current/10" : ""}`}
                      >
                        <span className="flex w-full justify-between gap-2">
                          <span className="font-medium">{String(l.full_name ?? "—")}</span>
                          <span className="text-xs opacity-60">{date(l.created_at as string)}</span>
                        </span>
                        <span className="opacity-70">{String(l.program_title ?? "Formation non choisie")}{l.session_code ? ` · ${String(l.session_code)}` : ""}</span>
                        <span className="text-xs opacity-60">
                          {STATUT[String(l.status)] ?? String(l.status)}
                          {l.level ? ` · ${NIVEAU[String(l.level)] ?? String(l.level)}` : ""}
                          {l.score != null ? ` · ${String(l.score)} pts` : ""}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          {!selection ? (
            <Card>
              <CardContent className="p-8 text-center text-sm opacity-70">Sélectionnez une demande pour lire ses réponses.</CardContent>
            </Card>
          ) : !fiche ? (
            <div className="flex flex-col gap-2" role="status" aria-busy="true" aria-label="Chargement de la fiche">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-64 max-w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
            <>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">{fiche.full_name}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-1 text-sm">
                  <p><span className="opacity-60">Courriel :</span> {fiche.email}</p>
                  {fiche.phone ? <p><span className="opacity-60">Téléphone :</span> {fiche.phone}</p> : null}
                  {fiche.company_name ? <p><span className="opacity-60">Structure :</span> {fiche.company_name}</p> : null}
                  <p><span className="opacity-60">Formation :</span> {fiche.program_title ?? "—"}{fiche.session_code ? ` · session ${fiche.session_code}` : ""}</p>
                  <p>
                    <span className="opacity-60">Statut :</span> {STATUT[fiche.status] ?? fiche.status}
                    {fiche.level ? ` · niveau ${NIVEAU[fiche.level] ?? fiche.level}` : ""}
                    {fiche.score != null ? ` · ${fiche.score} pts` : ""}
                  </p>
                  {fiche.message ? <p className="whitespace-pre-wrap pt-2 opacity-80">{fiche.message}</p> : null}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Réponses au test de positionnement</CardTitle>
                </CardHeader>
                <CardContent className="space-y-5 text-sm">
                  {blocs.length === 0 ? (
                    <p className="opacity-60">Le test n&apos;a pas encore été passé.</p>
                  ) : (
                    blocs.map(([bloc, reponses]) => (
                      <section key={bloc}>
                        <h3 className="text-xs font-semibold uppercase tracking-wide opacity-60">{bloc}</h3>
                        <dl className="mt-2 space-y-2">
                          {reponses.map((r, i) => (
                            <div key={i}>
                              <dt className="font-medium">{r.question}</dt>
                              <dd className="whitespace-pre-wrap opacity-80">
                                {Array.isArray(r.reponse) ? (r.reponse.length ? r.reponse.join(", ") : "— sans réponse") : r.reponse || "— sans réponse"}
                              </dd>
                            </div>
                          ))}
                        </dl>
                      </section>
                    ))
                  )}
                </CardContent>
              </Card>

              {peutDecider ? (
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-base">Décision</CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <select
                        value={sessionChoisie}
                        onChange={(e) => setSessionChoisie(e.target.value)}
                        className="min-w-[16rem] rounded-md border border-current/20 bg-transparent px-3 py-2"
                        aria-label="Session"
                      >
                        <option value="">Choisir la session…</option>
                        {sessionsDuProgramme.map((s) => (
                          <option key={s.id} value={s.id}>
                            {(s.program_title ?? s.title ?? "Session")} · {date(s.starts_on)} → {date(s.ends_on)}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        disabled={!sessionChoisie || busy}
                        onClick={() => void inscrire()}
                        className="rounded-md bg-current/90 px-4 py-2 font-medium disabled:opacity-40"
                      >
                        <span className="text-background">Inscrire</span>
                      </button>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <input
                        value={motif}
                        onChange={(e) => setMotif(e.target.value)}
                        placeholder="Motif du refus (5 caractères minimum)"
                        className="min-w-[16rem] flex-1 rounded-md border border-current/20 bg-transparent px-3 py-2"
                      />
                      <button
                        type="button"
                        disabled={motif.trim().length < 5 || busy}
                        onClick={() => void refuser()}
                        className="rounded-md border border-current/30 px-4 py-2 disabled:opacity-40"
                      >
                        Refuser
                      </button>
                    </div>
                  </CardContent>
                </Card>
              ) : null}
            </>
          )}
        </div>
      </div>

    </div>
  );
}
