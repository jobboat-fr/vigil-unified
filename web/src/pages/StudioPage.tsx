import { useCallback, useEffect, useState, lazy, Suspense } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { useSearchParams } from "react-router-dom";
import { vigil, type Artifact, type BrainstormPlan } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";
import { useLearnRole } from "@/lib/supabase";
import { ACCESS_LABELS, KINDS, KIND_LABELS, dateRelative } from "@/lib/studio";
import { PartagerArtefact } from "@/components/studio/PartagerArtefact";
import { AssistantArtefact } from "@/components/studio/AssistantArtefact";

const ArtifactCanvas = lazy(() =>
  import("@/components/ArtifactCanvas").then((m) => ({ default: m.ArtifactCanvas })),
);

type Onglet = "miens" | "partages" | "organisme";

const champ = "w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50";

function Squelette({ lignes = 3 }: { lignes?: number }) {
  return (
    <div className="flex animate-pulse flex-col gap-2" aria-label="Chargement">
      {Array.from({ length: lignes }).map((_, i) => (
        <div key={i} className="h-10 rounded-md bg-current/5" />
      ))}
    </div>
  );
}

export default function StudioPage() {
  const { role } = useLearnRole();
  const estAdmin = role === "admin" || role === "super_admin";
  const peutCreer = role !== "auditeur";

  const [onglet, setOnglet] = useState<Onglet>("miens");
  const [miens, setMiens] = useState<Artifact[] | null>(null);
  const [partages, setPartages] = useState<Artifact[]>([]);
  const [organisme, setOrganisme] = useState<Artifact[] | null>(null);
  const [erreurListe, setErreurListe] = useState<string | null>(null);

  const [brief, setBrief] = useState("");
  const [kind, setKind] = useState<string>("proposal");
  const [grounding, setGrounding] = useState("");
  const [plan, setPlan] = useState<BrainstormPlan | null>(null);
  const [planStub, setPlanStub] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [active, setActive] = useState<Artifact | null>(null);
  const [partager, setPartager] = useState(false);
  const [confirmerSuppression, setConfirmerSuppression] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await vigil.studio.list();
      setMiens(r.artifacts);
      setPartages(r.shared_with_me ?? []);
      setErreurListe(null);
    } catch (e) {
      setMiens([]);
      setErreurListe(e instanceof GatewayError && e.code === "NO_SESSION" ? "Connectez-vous pour ouvrir le studio." : (e as Error).message);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- chargement initial
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (onglet !== "organisme" || !estAdmin) return;
    vigil.studio.listOrganisme().then((r) => setOrganisme(r.artifacts)).catch((e) => {
      setOrganisme([]);
      setErreurListe((e as Error).message);
    });
  }, [onglet, estAdmin]);

  const [searchParams] = useSearchParams();
  useEffect(() => {
    const id = searchParams.get("artifact");
    if (id) vigil.studio.get(id).then(setActive).catch((e) => setError((e as Error).message));
  }, [searchParams]);

  useEffect(() => {
    document.title = active ? `${active.title} — Studio` : "Studio";
  }, [active]);

  const runBrainstorm = async () => {
    if (!brief.trim()) return;
    setThinking(true);
    setError(null);
    setPlan(null);
    try {
      const res = await vigil.studio.brainstorm(brief.trim(), kind, grounding.trim() || undefined);
      setPlan(res.plan);
      setPlanStub(res.stub);
    } catch (e) {
      setError(`${(e as Error).message} Votre consigne est gardée : réessayez quand vous voulez.`);
    } finally {
      setThinking(false);
    }
  };

  const draftFrom = async (approachText: string) => {
    setDrafting(true);
    setError(null);
    try {
      const art = await vigil.studio.create({
        title: brief.trim().slice(0, 60) || "Document sans titre",
        kind,
        brief: brief.trim(),
        approach: approachText,
        grounding: grounding.trim() || undefined,
      });
      setActive(art);
      setPlan(null);
      setBrief("");
      setGrounding("");
      setOnglet("miens");
      await refresh();
    } catch (e) {
      setError(`${(e as Error).message} Les approches restent affichées : vous pouvez relancer la rédaction.`);
    } finally {
      setDrafting(false);
    }
  };

  const open = async (id: string) => {
    setPartager(false);
    try {
      setActive(await vigil.studio.get(id));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const remove = async (id: string) => {
    try {
      await vigil.studio.remove(id);
      if (active?.id === id) setActive(null);
      setConfirmerSuppression(null);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const newBoard = async () => {
    try {
      const art = await vigil.studio.blankCanvas("Nouveau tableau");
      setActive(art);
      setOnglet("miens");
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const liste = onglet === "miens" ? miens : onglet === "partages" ? partages : organisme;
  const vide = {
    miens: "Rien pour l'instant. Décrivez un document à gauche, ou ouvrez un tableau vierge pour réfléchir.",
    partages: "Personne ne vous a encore partagé de document.",
    organisme: "Aucun document créé par les membres de votre organisme.",
  }[onglet];

  const peutEcrire = active && (active.access === "owner" || active.access === "edit");
  const estTableau = !!active && !!(active.canvas || active.tldraw);

  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-bold tracking-tight">Studio</h1>
          <p className="text-sm text-text-secondary">
            Vos documents et vos tableaux de réflexion, rédigés avec l'assistant. Ils sont à vous ; vous choisissez avec qui les partager.
          </p>
        </div>
        {peutCreer && <Button onClick={() => void newBoard()}>+ Nouveau tableau</Button>}
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="flex flex-col gap-4">
          {peutCreer && (
            <Card>
              <CardHeader><CardTitle>Nouveau document</CardTitle></CardHeader>
              <CardContent className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Type de document">
                  {KINDS.map((k) => (
                    <button
                      key={k}
                      type="button"
                      role="radio"
                      aria-checked={kind === k}
                      onClick={() => setKind(k)}
                      className="rounded-full px-3 py-1 text-xs"
                      style={{
                        border: "1px solid currentColor",
                        opacity: kind === k ? 1 : 0.45,
                        background: kind === k ? "currentColor" : "transparent",
                        color: kind === k ? "var(--background, #000)" : "inherit",
                      }}
                    >
                      <span style={{ color: kind === k ? "var(--background, #fff)" : "inherit" }}>{KIND_LABELS[k]}</span>
                    </button>
                  ))}
                </div>
                <textarea
                  className={champ}
                  rows={4}
                  placeholder="Que voulez-vous produire ? Par exemple : « une convention de formation pour la session Bureautique de septembre »."
                  value={brief}
                  onChange={(e) => setBrief(e.target.value)}
                />
                <details>
                  <summary className="cursor-pointer text-xs text-text-secondary">Texte source à respecter (facultatif)</summary>
                  <textarea
                    className={`${champ} mt-2`}
                    rows={3}
                    placeholder="Collez le contrat, le programme ou les notes que le document doit citer."
                    value={grounding}
                    onChange={(e) => setGrounding(e.target.value)}
                  />
                </details>
                <Button onClick={() => void runBrainstorm()} disabled={thinking || !brief.trim()} className="w-full">
                  {thinking ? "L'assistant réfléchit…" : "Réfléchir d'abord →"}
                </Button>
                {error && <p className="text-xs" role="alert" style={{ color: "#e11d48" }}>{error}</p>}
              </CardContent>
            </Card>
          )}

          {plan && (
            <Card>
              <CardHeader>
                <CardTitle>
                  Approches possibles
                  {planStub && <span className="ml-2 text-xs font-normal text-text-secondary">(démonstration : aucun modèle configuré)</span>}
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {plan.understanding && <p className="text-sm">{plan.understanding}</p>}
                {plan.clarifying_questions?.length > 0 && (
                  <div className="text-xs text-text-secondary">
                    <p className="mb-1 font-semibold uppercase tracking-wide">À clarifier</p>
                    <ul className="list-disc pl-4">{plan.clarifying_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
                  </div>
                )}
                {plan.approaches?.map((a, i) => (
                  <div key={i} className="rounded-md border border-current/15 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold">{a.name}</span>
                      {a.recommended && <span className="rounded px-2 py-0.5 text-[10px] uppercase" style={{ background: "#059669", color: "#fff" }}>Recommandée</span>}
                    </div>
                    <p className="mt-1 text-sm">{a.summary}</p>
                    {a.tradeoffs && <p className="mt-1 text-xs text-text-secondary">Compromis : {a.tradeoffs}</p>}
                    <Button ghost className="mt-2" disabled={drafting} onClick={() => void draftFrom(`${a.name}: ${a.summary}\n\nDesign: ${plan.recommended_design}`)}>
                      {drafting ? "Rédaction…" : "Rédiger avec cette approche →"}
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <div className="flex flex-wrap gap-1" role="tablist">
                {([
                  ["miens", `Mes documents${miens ? ` · ${miens.length}` : ""}`],
                  ["partages", `Partagés avec moi${partages.length ? ` · ${partages.length}` : ""}`],
                  ...(estAdmin ? [["organisme", "Organisme"]] : []),
                ] as [Onglet, string][]).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    role="tab"
                    aria-selected={onglet === id}
                    onClick={() => setOnglet(id)}
                    className="rounded-md px-3 py-1.5 text-sm"
                    style={{ background: onglet === id ? "rgba(127,127,127,0.15)" : "transparent", fontWeight: onglet === id ? 600 : 400 }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {erreurListe && <p className="text-sm" style={{ color: "#f59e0b" }}>{erreurListe}</p>}
              {liste === null ? (
                <Squelette />
              ) : liste.length === 0 ? (
                <p className="py-4 text-sm text-text-secondary">{vide}</p>
              ) : (
                liste.map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center justify-between gap-2 rounded-md border px-3 py-2"
                    style={{ borderColor: active?.id === a.id ? "currentColor" : "rgba(127,127,127,0.2)" }}
                  >
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => void open(a.id)}>
                      <span className="block truncate text-sm font-medium">{a.title}</span>
                      <span className="text-xs text-text-secondary">
                        {a.tldraw || a.canvas ? "Tableau" : KIND_LABELS[a.kind] ?? a.kind}
                        {a.owner_name ? ` · de ${a.owner_name}` : ""} · {dateRelative(a.updated_at)}
                        {a.access !== "owner" ? ` · ${ACCESS_LABELS[a.access]}` : ""}
                      </span>
                    </button>
                    {a.access === "owner" && (
                      confirmerSuppression === a.id ? (
                        <span className="flex shrink-0 gap-2 text-xs">
                          <button type="button" style={{ color: "#e11d48" }} onClick={() => void remove(a.id)}>Supprimer définitivement</button>
                          <button type="button" className="text-text-secondary" onClick={() => setConfirmerSuppression(null)}>Garder</button>
                        </span>
                      ) : (
                        <button type="button" className="shrink-0 text-xs text-text-secondary hover:text-foreground" onClick={() => setConfirmerSuppression(a.id)}>Supprimer</button>
                      )
                    )}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        <div>
          {active ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 truncate">{active.title}</span>
                  <span className="flex shrink-0 items-center gap-3 text-xs font-normal">
                    {active.access !== "owner" && (
                      <span className="rounded-full border border-current/20 px-2 py-0.5 text-text-secondary">{ACCESS_LABELS[active.access]}</span>
                    )}
                    {active.access === "owner" && (
                      <button type="button" className="hover:underline" onClick={() => setPartager((v) => !v)}>Partager</button>
                    )}
                    <button type="button" className="text-text-secondary hover:text-foreground" onClick={() => { setActive(null); setPartager(false); }}>Fermer</button>
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                {partager && active.access === "owner" && <PartagerArtefact artifactId={active.id} onClose={() => setPartager(false)} />}
                {estTableau ? (
                  <Suspense fallback={<div className="p-6 text-center text-sm text-text-secondary">Ouverture du tableau…</div>}>
                    <ArtifactCanvas key={`${active.id}:${active.updated_at}`} artifact={active} lectureSeule={!peutEcrire} />
                  </Suspense>
                ) : (
                  <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap rounded-md border border-current/10 bg-current/5 p-3 font-sans text-sm leading-relaxed">
                    {active.content || "Ce document est vide."}
                  </pre>
                )}
                {peutEcrire ? (
                  <AssistantArtefact artifact={active} onUpdated={(a) => { setActive(a); void refresh(); }} />
                ) : (
                  <p className="text-xs text-text-secondary">
                    Vous consultez ce document en lecture seule. Pour le modifier, demandez à son auteur de vous le partager en modification.
                  </p>
                )}
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="flex min-h-[220px] flex-col items-center justify-center gap-2 text-center text-sm text-text-secondary">
                <p>Ouvrez un document ou un tableau.</p>
                <p className="text-xs">L'assistant peut y écrire avec vous : idées, risques, prochaines étapes, révisions.</p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
