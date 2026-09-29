import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  useNodesState,
  type AriaLabelConfig,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Archive, Bot, FileText, Lock, Video } from "lucide-react";
import { Button } from "@nous-research/ui/ui/components/button";
import { useBelowBreakpoint } from "@nous-research/ui/hooks/use-below-breakpoint";
import { Refus } from "@/components/Refus";
import { AGENTS } from "@/lib/agentique";
import { dateRelative } from "@/lib/studio";
import {
  vigil,
  type AgentProjet,
  type Artifact,
  type CarteProjet,
  type ProjetComplet,
  type Room,
  type TravailAgent,
} from "@/lib/vigil";

/**
 * Le canevas d'un projet, dans l'esprit de Railway : chaque carte est un service du projet —
 * une salle, un artefact, un agent, un élément du coffre — et les arêtes disent d'où vient
 * quoi (un compte rendu vient de sa salle et de l'agent qui l'a rédigé).
 *
 * Sur grand écran, les cartes se déplacent à la souris et leur place est enregistrée. Sur
 * petit écran (et pour qui le préfère), le même contenu devient une liste verticale : le
 * canevas n'est jamais le seul moyen d'atteindre une carte.
 *
 * L'aperçu d'un agent non abonné est coupé par la passerelle : ce composant n'a jamais la
 * suite en main, il ne peut donc pas la « cacher » mal.
 */

const NOM_TYPE: Record<CarteProjet["kind"], string> = {
  salle: "Salle de réunion",
  artefact: "Artefact",
  agent: "Agent",
  coffre: "Coffre",
};
const SOUS_TYPE: Record<string, string> = { document: "Document", session: "Session", personne: "Personne" };
const COLONNE: Record<CarteProjet["kind"], number> = { salle: 0, artefact: 1, agent: 2, coffre: 3 };
const LARGEUR = 300;
const champ =
  "w-full min-w-0 rounded-md border border-border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Icone({ kind }: { kind: CarteProjet["kind"] }) {
  const P = { salle: Video, artefact: FileText, agent: Bot, coffre: Archive }[kind];
  return <P className="h-4 w-4 shrink-0" aria-hidden />;
}

// ── Ce que les cartes partagent : le projet, les travaux, les gestes ────────
type Contexte = {
  projetId: string;
  estAdmin: boolean;
  peutModifier: boolean;
  travaux: TravailAgent[];
  onTravail: (t: TravailAgent) => void;
  onRetirer: (carteId: string) => void;
};
const ContexteCanevas = createContext<Contexte | null>(null);
const useCanevas = () => {
  const c = useContext(ContexteCanevas);
  if (!c) throw new Error("ContexteCanevas manquant");
  return c;
};

/** Le résultat d'un travail. Verrouillé : l'aperçu que la passerelle a bien voulu envoyer. */
function ResultatTravail({ t }: { t: TravailAgent }) {
  const { estAdmin } = useCanevas();
  if (!t.verrouille) {
    return (
      <div className="nowheel max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted p-2 text-xs leading-relaxed">
        {t.sortie}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border p-2 text-xs">
      {t.apercu && <p className="break-words leading-relaxed">{t.apercu}</p>}
      {t.points.length > 0 && (
        <div>
          <p className="font-semibold text-text-secondary">Points traités</p>
          <ul className="mt-1 list-disc pl-4">
            {t.points.map((p) => <li key={p} className="break-words">{p}</li>)}
          </ul>
        </div>
      )}
      <p className="flex items-center gap-1.5 font-medium text-warning">
        <Lock className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {t.message}
      </p>
      {estAdmin ? (
        <Link to="/abonnement" className="nodrag self-start underline">Voir l'abonnement</Link>
      ) : (
        <p className="text-text-secondary">L'abonnement se souscrit par l'administration de votre organisme.</p>
      )}
    </div>
  );
}

function CorpsAgent({ carte }: { carte: CarteProjet }) {
  const { projetId, peutModifier, travaux, onTravail } = useCanevas();
  const agent = AGENTS.find((a) => a.id === carte.agent);
  const id = useId();
  const [consigne, setConsigne] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<unknown>(null);
  const siens = travaux.filter((t) => t.agent === carte.agent);
  const dernier = siens[0];

  const lancer = async () => {
    if (!carte.agent || consigne.trim().length < 3) return;
    setEnvoi(true);
    setErreur(null);
    try {
      onTravail(await vigil.projets.travail(projetId, carte.agent as AgentProjet, consigne.trim()));
      setConsigne("");
    } catch (e) {
      setErreur(e);
    } finally {
      setEnvoi(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-2 text-xs">
      {agent && <p className="text-text-secondary">{agent.accroche}</p>}
      <p className={carte.abonne ? "text-success" : "flex items-center gap-1 text-warning"}>
        {carte.abonne ? "✓ Abonnement actif" : (<><Lock className="h-3.5 w-3.5" aria-hidden /> Non abonné : aperçu seulement</>)}
      </p>
      {peutModifier && (
        <form
          className="flex flex-col gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            void lancer();
          }}
        >
          <label htmlFor={`${id}-consigne`} className="font-medium">Demander un travail à {carte.titre}</label>
          <textarea
            id={`${id}-consigne`}
            className={`${champ} nodrag nowheel text-xs`}
            rows={3}
            maxLength={2000}
            value={consigne}
            onChange={(e) => setConsigne(e.target.value)}
            placeholder="Par exemple : « prépare le calendrier des jalons et les risques »."
          />
          <Button type="submit" size="sm" className="nodrag self-start" disabled={envoi || consigne.trim().length < 3}>
            {envoi ? "L'agent travaille…" : "Lancer"}
          </Button>
        </form>
      )}
      {erreur != null && <Refus erreur={erreur} quoi="le travail de l'agent" compact />}
      <div aria-live="polite" className="flex flex-col gap-1.5">
        {dernier && (
          <>
            <p className="text-text-secondary">
              Dernier travail · {dateRelative(dernier.created_at)}
              {dernier.stub ? " · démonstration (aucun modèle configuré)" : ""}
            </p>
            <ResultatTravail t={dernier} />
          </>
        )}
      </div>
      {siens.length > 1 && (
        <details className="nodrag">
          <summary className="cursor-pointer text-text-secondary">Travaux précédents ({siens.length - 1})</summary>
          <div className="mt-1.5 flex flex-col gap-2">
            {siens.slice(1).map((t) => (
              <div key={t.id} className="flex flex-col gap-1">
                <p className="break-words text-text-secondary">« {t.brief} » · {dateRelative(t.created_at)}</p>
                <ResultatTravail t={t} />
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

/** Le contenu d'une carte, identique dans le canevas et dans la liste. */
function ContenuCarte({ carte }: { carte: CarteProjet }) {
  const { peutModifier, onRetirer } = useCanevas();
  const [confirmer, setConfirmer] = useState(false);
  const nomAgent = (a?: string | null) => AGENTS.find((x) => x.id === a)?.nom ?? a;

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex min-w-0 items-start gap-2">
        <Icone kind={carte.kind} />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-wide text-text-secondary">
            {carte.kind === "coffre" && carte.sous_type ? `Coffre · ${SOUS_TYPE[carte.sous_type]}` : NOM_TYPE[carte.kind]}
          </p>
          <p className="break-words text-sm font-semibold">{carte.titre}</p>
        </div>
      </div>

      {carte.manquant ? (
        <p className="text-xs text-text-secondary">Cette cible n'existe plus, ou ne vous est plus accessible.</p>
      ) : carte.kind === "agent" ? (
        <CorpsAgent carte={carte} />
      ) : (
        <div className="flex flex-col gap-1 text-xs">
          {carte.kind === "salle" && carte.statut && (
            <p className="text-text-secondary">{carte.statut === "closed" ? "Séance close" : "Salle ouverte"}</p>
          )}
          {carte.kind === "artefact" && (
            <>
              <p className="text-text-secondary">
                Version {carte.version ?? 1}{carte.maj ? ` · mise à jour ${dateRelative(carte.maj)}` : ""}
              </p>
              {carte.salle_source && (
                <p>
                  Issu de la salle{" "}
                  <Link className="nodrag underline" to={carte.salle_source.lien}>{carte.salle_source.titre || "sans titre"}</Link>
                </p>
              )}
              {carte.agent_source && <p>Rédigé par {nomAgent(carte.agent_source)}</p>}
            </>
          )}
          {carte.lien && (
            <Link className="nodrag self-start font-medium underline" to={carte.lien}>
              {carte.kind === "artefact" ? "Ouvrir la dernière version" : carte.kind === "salle" ? "Ouvrir la salle" : "Ouvrir"}
            </Link>
          )}
        </div>
      )}

      {peutModifier && (
        <div className="flex gap-3 border-t border-border pt-1.5 text-xs">
          {confirmer ? (
            <>
              <button type="button" className="nodrag text-destructive" onClick={() => onRetirer(carte.id)}>Retirer du projet</button>
              <button type="button" className="nodrag text-text-secondary" onClick={() => setConfirmer(false)}>Garder</button>
            </>
          ) : (
            <button type="button" className="nodrag text-text-secondary hover:text-foreground" onClick={() => setConfirmer(true)}>
              Retirer
            </button>
          )}
        </div>
      )}
    </div>
  );
}

type NoeudCarte = Node<{ carte: CarteProjet }, "carte">;

function NoeudCarteVue({ data }: NodeProps<NoeudCarte>) {
  return (
    <div
      className="rounded-lg border border-border bg-card p-3 text-card-foreground shadow-sm"
      style={{ width: LARGEUR }}
      role="group"
      aria-label={`${NOM_TYPE[data.carte.kind]} : ${data.carte.titre}`}
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <ContenuCarte carte={data.carte} />
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}
const typesDeNoeuds = { carte: NoeudCarteVue };

const ETIQUETTES_ARIA: Partial<AriaLabelConfig> = {
  "node.a11yDescription.default": "Carte du projet. Entrée ou Espace pour la sélectionner, puis les flèches pour la déplacer.",
  "node.a11yDescription.keyboardDisabled": "Carte du projet.",
  "node.a11yDescription.ariaLiveMessage": ({ direction, x, y }) =>
    `Carte déplacée vers ${({ up: "le haut", down: "le bas", left: "la gauche", right: "la droite" } as Record<string, string>)[direction] ?? direction}, position ${Math.round(x)}, ${Math.round(y)}.`,
  "edge.a11yDescription.default": "Lien entre deux cartes.",
  "controls.ariaLabel": "Commandes du canevas",
  "controls.zoomIn.ariaLabel": "Agrandir",
  "controls.zoomOut.ariaLabel": "Réduire",
  "controls.fitView.ariaLabel": "Tout afficher",
  "controls.interactive.ariaLabel": "Verrouiller le canevas",
  "minimap.ariaLabel": "Vue d'ensemble",
  "handle.ariaLabel": "Point d'attache",
};

function versNoeuds(cartes: CarteProjet[]): NoeudCarte[] {
  return cartes.map((c) => ({ id: c.id, type: "carte", position: { x: c.x, y: c.y }, data: { carte: c } }));
}

// ── Ajouter une carte ───────────────────────────────────────────────────────
function AjoutCarte({ projet, onAjout }: { projet: ProjetComplet; onAjout: () => void }) {
  const id = useId();
  const [kind, setKind] = useState<CarteProjet["kind"]>("artefact");
  const [ref, setRef] = useState("");
  const [sousType, setSousType] = useState<"document" | "session" | "personne">("document");
  const [libelle, setLibelle] = useState("");
  const [salles, setSalles] = useState<Room[] | null>(null);
  const [artefacts, setArtefacts] = useState<Artifact[] | null>(null);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<unknown>(null);

  useEffect(() => {
    if (kind === "salle" && salles === null) {
      vigil.rooms.list().then((r) => setSalles(r.rooms)).catch((e) => { setSalles([]); setErreur(e); });
    }
    if (kind === "artefact" && artefacts === null) {
      vigil.studio.list()
        .then((r) => setArtefacts([...r.artifacts, ...(r.shared_with_me ?? [])]))
        .catch((e) => { setArtefacts([]); setErreur(e); });
    }
  }, [kind, salles, artefacts]);

  const ajouter = async () => {
    const refId = kind === "coffre" ? (ref.trim() || libelle.trim()) : ref;
    if (!refId) return;
    // Rangées par nature, les unes sous les autres : le canevas reste lisible sans rien déplacer.
    const colonne = COLONNE[kind];
    const deLaColonne = projet.cartes.filter((c) => COLONNE[c.kind] === colonne);
    const y = deLaColonne.length ? Math.max(...deLaColonne.map((c) => c.y)) + 260 : 0;
    setEnvoi(true);
    setErreur(null);
    try {
      await vigil.projets.addCarte(projet.id, {
        kind,
        ref_id: refId,
        x: colonne * (LARGEUR + 60),
        y,
        ...(kind === "coffre" ? { sous_type: sousType, libelle: libelle.trim() || undefined } : {}),
      });
      setRef("");
      setLibelle("");
      onAjout();
    } catch (e) {
      setErreur(e);
    } finally {
      setEnvoi(false);
    }
  };

  const dejaPosees = new Set(projet.cartes.filter((c) => c.kind === kind).map((c) => c.ref_id));

  return (
    <form
      className="flex min-w-0 flex-col gap-2 rounded-md border border-border p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void ajouter();
      }}
    >
      <p className="text-sm font-medium">Ajouter une carte</p>
      <div className="grid min-w-0 gap-2 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-end">
        <label className="flex flex-col gap-1 text-xs">
          Nature
          <select className={champ} value={kind} onChange={(e) => { setKind(e.target.value as CarteProjet["kind"]); setRef(""); }}>
            <option value="artefact">Artefact du Studio</option>
            <option value="salle">Salle de réunion</option>
            <option value="agent">Agent</option>
            <option value="coffre">Élément du coffre</option>
          </select>
        </label>

        {kind === "agent" && (
          <label className="flex min-w-0 flex-col gap-1 text-xs" htmlFor={`${id}-ref`}>
            Agent
            <select id={`${id}-ref`} className={champ} value={ref} onChange={(e) => setRef(e.target.value)}>
              <option value="">Choisir…</option>
              {AGENTS.filter((a) => !dejaPosees.has(a.id)).map((a) => <option key={a.id} value={a.id}>{a.nom} — {a.accroche}</option>)}
            </select>
          </label>
        )}
        {kind === "salle" && (
          <label className="flex min-w-0 flex-col gap-1 text-xs" htmlFor={`${id}-ref`}>
            Salle
            <select id={`${id}-ref`} className={champ} value={ref} onChange={(e) => setRef(e.target.value)} disabled={salles === null}>
              <option value="">{salles === null ? "Chargement…" : salles.length ? "Choisir…" : "Aucune salle"}</option>
              {(salles ?? []).filter((s) => !dejaPosees.has(s.id)).map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
            </select>
          </label>
        )}
        {kind === "artefact" && (
          <label className="flex min-w-0 flex-col gap-1 text-xs" htmlFor={`${id}-ref`}>
            Artefact
            <select id={`${id}-ref`} className={champ} value={ref} onChange={(e) => setRef(e.target.value)} disabled={artefacts === null}>
              <option value="">{artefacts === null ? "Chargement…" : artefacts.length ? "Choisir…" : "Aucun artefact"}</option>
              {(artefacts ?? []).filter((a) => !dejaPosees.has(a.id)).map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
            </select>
          </label>
        )}
        {kind === "coffre" && (
          <div className="grid min-w-0 gap-2 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-xs">
              Ce que c'est
              <select className={champ} value={sousType} onChange={(e) => setSousType(e.target.value as typeof sousType)}>
                <option value="document">Document</option>
                <option value="session">Session</option>
                <option value="personne">Personne</option>
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-xs">
              Intitulé
              <input className={champ} value={libelle} onChange={(e) => setLibelle(e.target.value)} maxLength={200} required />
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-xs">
              Référence <span className="text-text-secondary">(facultatif)</span>
              <input className={champ} value={ref} onChange={(e) => setRef(e.target.value)} maxLength={200} />
            </label>
          </div>
        )}
        <Button type="submit" disabled={envoi || (kind === "coffre" ? !libelle.trim() : !ref)}>
          {envoi ? "Ajout…" : "Ajouter"}
        </Button>
      </div>
      {erreur != null && <Refus erreur={erreur} quoi="cette carte" compact />}
    </form>
  );
}

// ── Le canevas ──────────────────────────────────────────────────────────────
export function ProjetCanevas({
  projet,
  estAdmin,
  peutModifier,
  onRecharger,
}: {
  projet: ProjetComplet;
  estAdmin: boolean;
  peutModifier: boolean;
  onRecharger: () => void;
}) {
  const petitEcran = useBelowBreakpoint(768);
  const [enListe, setEnListe] = useState(false);
  const liste = petitEcran || enListe;
  const [travaux, setTravaux] = useState<TravailAgent[]>([]);
  const [erreur, setErreur] = useState<unknown>(null);
  const [noeuds, setNoeuds, onNodesChange] = useNodesState<NoeudCarte>(versNoeuds(projet.cartes));

  useEffect(() => {
    // Le projet rechargé fait foi (carte ajoutée ou retirée).
    setNoeuds(versNoeuds(projet.cartes));
  }, [projet.cartes, setNoeuds]);

  useEffect(() => {
    let vivant = true;
    vigil.projets.travaux(projet.id).then((r) => vivant && setTravaux(r.travaux)).catch((e) => vivant && setErreur(e));
    return () => { vivant = false; };
  }, [projet.id]);

  const aretes = useMemo<Edge[]>(
    () =>
      projet.liens.map((l) => ({
        id: `${l.de}-${l.vers}`,
        source: l.de,
        target: l.vers,
        animated: true,
        label: l.nature === "salle_source" ? "issu de la salle" : "rédigé par",
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "var(--color-ring)" },
        style: { stroke: "var(--color-ring)", strokeWidth: 1.5 },
      })),
    [projet.liens],
  );

  // Une place se garde quand la carte s'est posée : après un glisser, mais aussi après un
  // déplacement au clavier (flèches), qui ne déclenche aucun « fin de glisser ».
  const minuteries = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  useEffect(() => {
    const m = minuteries.current;
    return () => m.forEach(clearTimeout);
  }, []);
  const changer = useCallback((changements: NodeChange<NoeudCarte>[]) => {
    onNodesChange(changements);
    if (!peutModifier) return;
    for (const c of changements) {
      if (c.type !== "position" || !c.position) continue;
      const { id, position } = c;
      clearTimeout(minuteries.current.get(id));
      minuteries.current.set(id, setTimeout(() => {
        minuteries.current.delete(id);
        void vigil.projets.moveCarte(projet.id, id, Math.round(position.x), Math.round(position.y)).catch(setErreur);
      }, 400));
    }
  }, [onNodesChange, peutModifier, projet.id]);

  const retirer = useCallback(async (carteId: string) => {
    try {
      await vigil.projets.removeCarte(projet.id, carteId);
      onRecharger();
    } catch (e) {
      setErreur(e);
    }
  }, [projet.id, onRecharger]);

  const contexte = useMemo<Contexte>(() => ({
    projetId: projet.id,
    estAdmin,
    peutModifier,
    travaux,
    onTravail: (t) => setTravaux((prev) => [t, ...prev]),
    onRetirer: (id) => void retirer(id),
  }), [projet.id, estAdmin, peutModifier, travaux, retirer]);

  // Dans la liste : l'ordre du canevas, de haut en bas puis de gauche à droite.
  const ordonnees = useMemo(
    () => [...projet.cartes].sort((a, b) => a.y - b.y || a.x - b.x),
    [projet.cartes],
  );

  return (
    <ContexteCanevas.Provider value={contexte}>
      <div className="flex min-w-0 flex-col gap-3">
        {peutModifier && <AjoutCarte projet={projet} onAjout={onRecharger} />}
        {erreur != null && <Refus erreur={erreur} quoi="le canevas" compact />}
        {!petitEcran && (
          <div className="flex justify-end">
            <button
              type="button"
              className="text-xs text-text-secondary underline hover:text-foreground"
              aria-pressed={enListe}
              onClick={() => setEnListe((v) => !v)}
            >
              {enListe ? "Afficher le canevas" : "Afficher en liste"}
            </button>
          </div>
        )}

        {projet.cartes.length === 0 ? (
          <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-text-secondary">
            Aucune carte pour l'instant. Posez une salle, un artefact, un agent ou un élément du coffre.
          </p>
        ) : liste ? (
          <ul className="flex min-w-0 flex-col gap-3" aria-label="Cartes du projet">
            {ordonnees.map((c) => {
              const lies = projet.liens.filter((l) => l.de === c.id)
                .map((l) => projet.cartes.find((x) => x.id === l.vers)?.titre)
                .filter(Boolean);
              return (
                <li key={c.id} className="min-w-0 rounded-lg border border-border bg-card p-3">
                  <ContenuCarte carte={c} />
                  {lies.length > 0 && <p className="mt-2 text-xs text-text-secondary">Relié à : {lies.join(", ")}</p>}
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="h-[70vh] min-h-[420px] w-full overflow-hidden rounded-lg border border-border" style={{ background: "var(--color-background, transparent)" }}>
            <ReactFlow<NoeudCarte, Edge>
              nodes={noeuds}
              edges={aretes}
              nodeTypes={typesDeNoeuds}
              onNodesChange={changer}
              nodesDraggable={peutModifier}
              nodesConnectable={false}
              elementsSelectable
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.3}
              maxZoom={1.5}
              proOptions={{ hideAttribution: true }}
              ariaLabelConfig={ETIQUETTES_ARIA}
            >
              <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>
        )}
      </div>
    </ContexteCanevas.Provider>
  );
}

export default ProjetCanevas;
