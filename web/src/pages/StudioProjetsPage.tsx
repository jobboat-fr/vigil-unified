import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { usePageHeader } from "@/contexts/usePageHeader";
import { Refus } from "@/components/Refus";
import { AssistantProjet } from "@/components/studio/AssistantProjet";
import { useLearnRole } from "@/lib/supabase";
import { dateRelative } from "@/lib/studio";
import { vigil, type EtapeProjet, type ProjetComplet, type ProjetResume } from "@/lib/vigil";

// Le canevas embarque @xyflow/react : chargé seulement quand on ouvre un projet.
const ProjetCanevas = lazy(() => import("@/components/studio/ProjetCanevas"));

/**
 * Projets du Studio : la liste, l'assistant en six étapes, puis le canevas du projet.
 *
 * L'état tient dans l'adresse — `?projet=<id>` ouvre un projet, `&etape=<1-6>` l'assistant
 * sur cette étape — pour qu'un rechargement ou un lien partagé retombe au même endroit.
 */

const STATUTS: Record<ProjetResume["statut"], string> = {
  brouillon: "Brouillon",
  en_validation: "En validation",
  valide: "Validé",
};

function Squelette() {
  return (
    <div className="flex animate-pulse flex-col gap-2" aria-label="Chargement">
      {[0, 1, 2].map((i) => <div key={i} className="h-12 rounded-md bg-muted" />)}
    </div>
  );
}

function Liste({ peutCreer }: { peutCreer: boolean }) {
  const [, setParams] = useSearchParams();
  const [projets, setProjets] = useState<ProjetResume[] | null>(null);
  const [erreur, setErreur] = useState<unknown>(null);
  const [creation, setCreation] = useState(false);

  useEffect(() => {
    vigil.projets.list().then((r) => setProjets(r.projets)).catch((e) => { setProjets([]); setErreur(e); });
  }, []);

  const nouveau = async () => {
    setCreation(true);
    setErreur(null);
    try {
      const p = await vigil.projets.create();
      setParams({ projet: p.id, etape: "1" });
    } catch (e) {
      setErreur(e);
    } finally {
      setCreation(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h1 className="text-xl font-bold tracking-tight">Projets</h1>
          <p className="text-sm text-text-secondary">
            Un projet se pose en six étapes, puis vit sur un canevas qui relie vos salles, vos artefacts, vos agents et votre coffre.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/studio"><Button ghost>← Studio</Button></Link>
          {peutCreer && <Button onClick={() => void nouveau()} disabled={creation}>{creation ? "Création…" : "+ Nouveau projet"}</Button>}
        </div>
      </header>
      {erreur != null && <Refus erreur={erreur} quoi="vos projets" compact />}
      {projets === null ? (
        <Squelette />
      ) : projets.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-text-secondary">
            Aucun projet pour l'instant.{peutCreer ? " Commencez par « Nouveau projet » : l'assistant vous guide étape par étape." : ""}
          </CardContent>
        </Card>
      ) : (
        <ul className="grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {projets.map((p) => (
            <li key={p.id} className="min-w-0">
              <Link
                to={`?projet=${p.id}`}
                className="block rounded-lg border border-border bg-card p-4 hover:border-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="block break-words font-semibold">{p.titre}</span>
                <span className="mt-1 block text-xs text-text-secondary">
                  {p.etapes_completes}/{p.etapes_total} étapes · {STATUTS[p.statut] ?? p.statut} · {dateRelative(p.updated_at)}
                </span>
                <span className="mt-2 block h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
                  <span className="block h-full bg-success" style={{ width: `${(100 * p.etapes_completes) / p.etapes_total}%` }} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Projet({ id, etape, peutModifier, estAdmin }: { id: string; etape: number | null; peutModifier: boolean; estAdmin: boolean }) {
  const [, setParams] = useSearchParams();
  const [projet, setProjet] = useState<ProjetComplet | null>(null);
  const [erreur, setErreur] = useState<unknown>(null);
  const [supprimer, setSupprimer] = useState(false);
  const { setTitle } = usePageHeader();

  const charger = useCallback(async () => {
    try {
      setProjet(await vigil.projets.get(id));
      setErreur(null);
    } catch (e) {
      setErreur(e);
    }
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- chargement du projet ouvert
    void charger();
  }, [charger]);

  useEffect(() => {
    setTitle(projet ? `${projet.titre} — Projets` : null);
    return () => setTitle(null);
  }, [projet, setTitle]);

  const allerEtape = (n: number) => setParams({ projet: id, etape: String(n) });
  const allerCanevas = () => {
    setParams({ projet: id });
    void charger();
  };
  const majEtapes = (etapes: EtapeProjet[]) =>
    setProjet((p) => (p ? { ...p, etapes, etapes_completes: etapes.filter((e) => e.complete).length,
      titre: (etapes[0].donnees?.nom as string | undefined) ?? p.titre } : p));

  const effacer = async () => {
    try {
      await vigil.projets.remove(id);
      setParams({});
    } catch (e) {
      setErreur(e);
    }
  };

  if (erreur != null && !projet) return <Refus erreur={erreur} quoi="ce projet" onReessayer={() => void charger()} />;
  if (!projet) return <Squelette />;

  const objectif = projet.etapes[0].donnees?.objectif as string | undefined;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <Link to="/studio/projets" className="text-xs text-text-secondary underline hover:text-foreground">← Tous les projets</Link>
          <h1 className="break-words text-xl font-bold tracking-tight">{projet.titre}</h1>
          {objectif && <p className="break-words text-sm text-text-secondary">{objectif}</p>}
        </div>
        {peutModifier && etape === null && (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {supprimer ? (
              <>
                <button type="button" className="text-destructive underline" onClick={() => void effacer()}>Supprimer le projet</button>
                <button type="button" className="text-text-secondary underline" onClick={() => setSupprimer(false)}>Garder</button>
              </>
            ) : (
              <button type="button" className="text-text-secondary underline hover:text-foreground" onClick={() => setSupprimer(true)}>Supprimer…</button>
            )}
          </div>
        )}
      </header>

      {etape !== null && peutModifier ? (
        <AssistantProjet
          key={etape}
          projetId={id}
          etapes={projet.etapes}
          numero={Math.min(Math.max(etape, 1), projet.etapes.length)}
          onEtape={allerEtape}
          onEnregistre={majEtapes}
          onTerminer={allerCanevas}
        />
      ) : (
        <>
          <Card className="min-w-0">
            <CardHeader className="pb-2"><CardTitle className="text-sm">Étapes</CardTitle></CardHeader>
            <CardContent>
              <ol className="flex flex-wrap gap-1.5">
                {projet.etapes.map((e) => (
                  <li key={e.cle}>
                    {peutModifier ? (
                      <button
                        type="button"
                        onClick={() => allerEtape(e.numero)}
                        className="rounded-full border border-border px-2.5 py-0.5 text-xs hover:border-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        {e.numero}. {e.titre} {e.complete ? <span className="text-success">✓</span> : <span className="text-text-secondary">— à remplir</span>}
                      </button>
                    ) : (
                      <span className="rounded-full border border-border px-2.5 py-0.5 text-xs">{e.numero}. {e.titre} {e.complete ? "✓" : ""}</span>
                    )}
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
          {erreur != null && <Refus erreur={erreur} quoi="ce projet" compact />}
          <Suspense fallback={<div className="p-6 text-center text-sm text-text-secondary">Ouverture du canevas…</div>}>
            <ProjetCanevas projet={projet} estAdmin={estAdmin} peutModifier={peutModifier} onRecharger={() => void charger()} />
          </Suspense>
        </>
      )}
    </div>
  );
}

export default function StudioProjetsPage() {
  const { role } = useLearnRole();
  const estAdmin = role === "admin" || role === "super_admin";
  // Même règle que le Studio : l'auditeur regarde, il ne crée rien.
  const peutModifier = role !== "auditeur";
  const [params] = useSearchParams();
  const projetId = params.get("projet");
  const etapeBrute = Number(params.get("etape"));
  const etape = Number.isInteger(etapeBrute) && etapeBrute >= 1 ? etapeBrute : null;

  return (
    <div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
      {projetId ? (
        <Projet key={projetId} id={projetId} etape={etape} peutModifier={peutModifier} estAdmin={estAdmin} />
      ) : (
        <Liste peutCreer={peutModifier} />
      )}
    </div>
  );
}
