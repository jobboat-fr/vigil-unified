import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import { Archive, ArrowLeft, Bot, FileText, LayoutList, Lock, Network, Plus, Settings2, Video, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBelowBreakpoint } from "@nous-research/ui/hooks/use-below-breakpoint";
import { Markdown } from "@/components/Markdown";
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
 * L'espace de travail d'un projet, sur le modèle de Railway.
 *
 * Le canevas occupe tout l'écran ; chaque carte est un « service » du projet (une salle, un
 * artefact, un agent, un élément du coffre), réduite à l'essentiel : son icône, son nom, un
 * point d'état. Tout le reste — le travail d'un agent, ses réponses, les liens, le retrait —
 * s'ouvre dans un panneau latéral quand on clique la carte. Les six étapes du projet sont
 * dans « Réglages », comme les réglages d'un projet Railway : elles ne barrent plus l'accès
 * au canevas.
 *
 * Avant le 29/09, chaque carte faisait 300 px et portait tout son formulaire : le canevas
 * n'était qu'une colonne de formulaires (capture d'Azer). Sur téléphone, les mêmes cartes
 * deviennent une liste et le panneau une feuille plein écran : le canevas n'est jamais le
 * seul moyen d'atteindre une carte.
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
const LARGEUR = 248;
const champ =
  "w-full min-w-0 rounded-md border border-border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Icone({ kind, className = "h-4 w-4" }: { kind: CarteProjet["kind"]; className?: string }) {
  const P = { salle: Video, artefact: FileText, agent: Bot, coffre: Archive }[kind];
  return <P className={`${className} shrink-0`} aria-hidden />;
}

const libelleType = (c: CarteProjet) =>
  c.kind === "coffre" && c.sous_type ? `Coffre · ${SOUS_TYPE[c.sous_type]}` : NOM_TYPE[c.kind];

// ── L'état d'une carte : un point de couleur et quelques mots, comme un service Railway ──
type Ton = "ok" | "attente" | "alerte" | "neutre";
const POINT: Record<Ton, string> = {
  ok: "bg-success",
  attente: "bg-warning",
  alerte: "bg-destructive",
  neutre: "bg-midground/40",
};

function etatCarte(c: CarteProjet, travaux: TravailAgent[]): { ton: Ton; texte: string } {
  if (c.manquant) return { ton: "alerte", texte: "Introuvable" };
  if (c.kind === "agent") {
    const dernier = travaux.find((t) => t.agent === c.agent);
    const quand = dernier ? ` · ${dateRelative(dernier.created_at)}` : "";
    return c.abonne ? { ton: "ok", texte: `Abonné${quand}` } : { ton: "attente", texte: `Aperçu seulement${quand}` };
  }
  if (c.kind === "salle") return c.statut === "closed" ? { ton: "neutre", texte: "Séance close" } : { ton: "ok", texte: "Salle ouverte" };
  if (c.kind === "artefact") return { ton: "ok", texte: `Version ${c.version ?? 1}${c.maj ? ` · ${dateRelative(c.maj)}` : ""}` };
  return { ton: "neutre", texte: c.sous_type ? SOUS_TYPE[c.sous_type] : "Élément du coffre" };
}

function Etat({ carte }: { carte: CarteProjet }) {
  const { travaux } = useCanevas();
  const e = etatCarte(carte, travaux);
  return (
    <span className="flex min-w-0 items-center gap-2 text-xs text-text-secondary">
      <span className={`size-2 shrink-0 rounded-full ${POINT[e.ton]}`} aria-hidden />
      <span className="truncate">{e.texte}</span>
    </span>
  );
}

// ── Ce que les cartes partagent : le projet, les travaux, les gestes ────────
type Contexte = {
  projetId: string;
  estAdmin: boolean;
  peutModifier: boolean;
  travaux: TravailAgent[];
  selection: string | null;
  onTravail: (t: TravailAgent) => void;
  onRetirer: (carteId: string) => void;
  onOuvrir: (carteId: string) => void;
};
const ContexteCanevas = createContext<Contexte | null>(null);
const useCanevas = () => {
  const c = useContext(ContexteCanevas);
  if (!c) throw new Error("ContexteCanevas manquant");
  return c;
};

/** La vignette d'une carte : identique sur le canevas et dans la liste. */
function Vignette({ carte, active }: { carte: CarteProjet; active: boolean }) {
  return (
    <div
      className={`flex w-full min-w-0 flex-col rounded-xl border bg-card text-card-foreground shadow-sm transition-colors ${
        active ? "border-foreground ring-2 ring-ring/40" : "border-border hover:border-foreground/40"
      }`}
    >
      <div className="flex min-w-0 items-start gap-3 p-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-midground/10">
          <Icone kind={carte.kind} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="line-clamp-2 break-words text-sm font-semibold leading-snug">{carte.titre}</span>
          <span className="text-xs text-text-secondary">{libelleType(carte)}</span>
        </span>
      </div>
      <div className="border-t border-border px-3 py-2">
        <Etat carte={carte} />
      </div>
    </div>
  );
}

type NoeudCarte = Node<{ carte: CarteProjet }, "carte">;

function NoeudCarteVue({ data, selected }: NodeProps<NoeudCarte>) {
  const { selection } = useCanevas();
  return (
    <div style={{ width: LARGEUR }} className="cursor-pointer" aria-label={`${NOM_TYPE[data.carte.kind]} : ${data.carte.titre}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} className="!opacity-0" />
      <Vignette carte={data.carte} active={selected || selection === data.carte.id} />
      <Handle type="source" position={Position.Right} isConnectable={false} className="!opacity-0" />
    </div>
  );
}
const typesDeNoeuds = { carte: NoeudCarteVue };

const ETIQUETTES_ARIA: Partial<AriaLabelConfig> = {
  "node.a11yDescription.default": "Carte du projet. Entrée pour l'ouvrir, puis les flèches pour la déplacer.",
  "node.a11yDescription.keyboardDisabled": "Carte du projet. Entrée pour l'ouvrir.",
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

// ── Le travail d'un agent ───────────────────────────────────────────────────
/** Le résultat d'un travail, mis en forme. Verrouillé : l'aperçu que la passerelle a bien voulu envoyer. */
function ResultatTravail({ t }: { t: TravailAgent }) {
  const { estAdmin } = useCanevas();
  if (!t.verrouille) {
    return (
      <div className="min-w-0 break-words rounded-lg border border-border p-3">
        <Markdown content={t.sortie ?? ""} />
      </div>
    );
  }
  return (
    <div className="flex min-w-0 flex-col gap-3 rounded-lg border border-border p-3 text-sm">
      {t.apercu && <p className="break-words leading-relaxed">{t.apercu}</p>}
      {t.points.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-text-secondary">Ce que la réponse complète traite</p>
          <ul className="mt-1 list-disc pl-5">
            {t.points.map((p) => <li key={p} className="break-words">{p}</li>)}
          </ul>
        </div>
      )}
      <p className="flex items-center gap-1.5 font-medium text-warning">
        <Lock className="h-4 w-4 shrink-0" aria-hidden />
        {t.message}
      </p>
      {estAdmin ? (
        <Link to="/abonnement" className="self-start text-sm font-medium underline">Voir l'abonnement</Link>
      ) : (
        <p className="text-xs text-text-secondary">L'abonnement se souscrit par l'administration de votre organisme.</p>
      )}
    </div>
  );
}

/** Des demandes de départ, tirées de la mission de l'agent — pour ne pas faire face à un champ vide. */
const SUGGESTIONS: Record<string, string[]> = {
  azzmin: ["Liste les comptes et créneaux à ouvrir pour ce projet", "Quels documents le coffre doit-il contenir ?"],
  azzco: ["Construis le planning des jalons avec les risques", "Quelles obligations légales ce projet déclenche-t-il ?"],
  azzcom: ["Rédige le message de lancement aux participants", "Qualifie le besoin client et propose une offre"],
};

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
    <div className="flex min-w-0 flex-col gap-4">
      {agent && <p className="text-sm text-text-secondary">{agent.accroche}</p>}
      {!carte.abonne && (
        <p className="flex items-start gap-2 rounded-lg border border-border p-3 text-sm">
          <Lock className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
          <span>Votre organisme n'est pas abonné à {carte.titre} : l'agent travaille, vous en lisez le début.</span>
        </p>
      )}
      {peutModifier && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void lancer();
          }}
        >
          <label htmlFor={`${id}-consigne`} className="text-sm font-medium">Que doit faire {carte.titre} pour ce projet ?</label>
          <p className="text-xs text-text-secondary">
            L'agent lit les étapes du projet, les artefacts, les salles et le coffre posés sur le canevas, et ses travaux précédents.
          </p>
          <textarea
            id={`${id}-consigne`}
            className={champ}
            rows={4}
            maxLength={2000}
            value={consigne}
            onChange={(e) => setConsigne(e.target.value)}
            placeholder="Décrivez le travail attendu…"
          />
          {!consigne && carte.agent && SUGGESTIONS[carte.agent] && (
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS[carte.agent].map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setConsigne(s)}
                  className="rounded-full border border-border px-3 py-1 text-left text-xs hover:border-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          <Button type="submit" className="self-start" disabled={envoi || consigne.trim().length < 3}>
            {envoi ? "L'agent travaille…" : "Lancer le travail"}
          </Button>
        </form>
      )}
      {erreur != null && <Refus erreur={erreur} quoi="le travail de l'agent" compact />}
      <div aria-live="polite" className="flex min-w-0 flex-col gap-2">
        {dernier && (
          <>
            <h3 className="text-sm font-semibold">Dernier travail</h3>
            <p className="break-words text-xs text-text-secondary">
              « {dernier.brief} » · {dateRelative(dernier.created_at)}
              {dernier.stub ? " · démonstration (aucun modèle configuré)" : ""}
            </p>
            <ResultatTravail t={dernier} />
          </>
        )}
      </div>
      {siens.length > 1 && (
        <details className="min-w-0">
          <summary className="cursor-pointer text-sm font-medium">Travaux précédents ({siens.length - 1})</summary>
          <div className="mt-2 flex flex-col gap-3">
            {siens.slice(1).map((t) => (
              <div key={t.id} className="flex min-w-0 flex-col gap-1">
                <p className="break-words text-xs text-text-secondary">« {t.brief} » · {dateRelative(t.created_at)}</p>
                <ResultatTravail t={t} />
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

// ── Le panneau latéral ──────────────────────────────────────────────────────
type Vue = { type: "carte"; id: string } | { type: "ajout"; kind?: CarteProjet["kind"] } | { type: "reglages" } | null;

function Panneau({ titre, sousTitre, icone, onFermer, petitEcran, children }: {
  titre: string;
  sousTitre?: string;
  icone?: React.ReactNode;
  onFermer: () => void;
  petitEcran: boolean;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => { ref.current?.focus(); }, [titre]);
  useEffect(() => {
    const echap = (e: KeyboardEvent) => { if (e.key === "Escape") onFermer(); };
    window.addEventListener("keydown", echap);
    return () => window.removeEventListener("keydown", echap);
  }, [onFermer]);
  return (
    <aside
      aria-label={titre}
      className={
        petitEcran
          ? "fixed inset-0 z-50 flex flex-col bg-background"
          : "absolute inset-y-0 right-0 z-10 flex w-[min(460px,100%)] flex-col border-l border-border bg-background shadow-xl"
      }
    >
      <header className="flex min-w-0 items-start gap-3 border-b border-border p-4">
        {icone && <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-midground/10">{icone}</span>}
        <div className="min-w-0 flex-1">
          <h2 ref={ref} tabIndex={-1} className="break-words text-base font-semibold leading-snug outline-none">{titre}</h2>
          {sousTitre && <p className="text-xs text-text-secondary">{sousTitre}</p>}
        </div>
        <Button ghost size="icon" onClick={onFermer} aria-label="Fermer le panneau"><X className="h-5 w-5" /></Button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">{children}</div>
    </aside>
  );
}

function DetailCarte({ carte, projet }: { carte: CarteProjet; projet: ProjetComplet }) {
  const { peutModifier, onRetirer, onOuvrir } = useCanevas();
  const navigate = useNavigate();
  const [confirmer, setConfirmer] = useState(false);
  const nomAgent = (a?: string | null) => AGENTS.find((x) => x.id === a)?.nom ?? a;
  const relies = projet.liens
    .filter((l) => l.de === carte.id || l.vers === carte.id)
    .map((l) => projet.cartes.find((x) => x.id === (l.de === carte.id ? l.vers : l.de)))
    .filter((x): x is CarteProjet => Boolean(x));

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <Etat carte={carte} />
      {carte.manquant ? (
        <p className="text-sm text-text-secondary">Cette cible n'existe plus, ou ne vous est plus accessible.</p>
      ) : carte.kind === "agent" ? (
        <CorpsAgent carte={carte} />
      ) : (
        <div className="flex flex-col gap-2 text-sm">
          {carte.kind === "artefact" && carte.salle_source && (
            <p>
              Issu de la salle{" "}
              <Link className="underline" to={carte.salle_source.lien}>{carte.salle_source.titre || "sans titre"}</Link>
            </p>
          )}
          {carte.kind === "artefact" && carte.agent_source && <p>Rédigé par {nomAgent(carte.agent_source)}</p>}
          {carte.lien && (
            <Button className="self-start" onClick={() => navigate(carte.lien!)}>
              {carte.kind === "artefact" ? "Ouvrir la dernière version" : carte.kind === "salle" ? "Entrer dans la salle" : "Ouvrir"}
            </Button>
          )}
        </div>
      )}

      {relies.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">Relié à</h3>
          <ul className="flex flex-col gap-1.5">
            {relies.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => onOuvrir(r.id)}
                  className="flex w-full min-w-0 items-center gap-2 rounded-md border border-border px-3 py-2 text-left text-sm hover:border-foreground"
                >
                  <Icone kind={r.kind} />
                  <span className="min-w-0 truncate">{r.titre}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {peutModifier && (
        <section className="flex flex-col gap-2 border-t border-border pt-4">
          <h3 className="text-sm font-semibold">Réglages de la carte</h3>
          <p className="text-xs text-text-secondary">Retirer la carte ne supprime pas ce qu'elle désigne.</p>
          {confirmer ? (
            <div className="flex flex-wrap gap-2">
              <Button destructive size="sm" onClick={() => onRetirer(carte.id)}>Retirer du projet</Button>
              <Button ghost size="sm" onClick={() => setConfirmer(false)}>Garder</Button>
            </div>
          ) : (
            <Button outlined size="sm" className="self-start" onClick={() => setConfirmer(true)}>Retirer du projet…</Button>
          )}
        </section>
      )}
    </div>
  );
}

// ── Ajouter une carte ───────────────────────────────────────────────────────
const NATURES: { kind: CarteProjet["kind"]; titre: string; aide: string }[] = [
  { kind: "agent", titre: "Agent", aide: "AZZMIN, AZZCO ou AZZCOM, qui travaille sur ce projet" },
  { kind: "artefact", titre: "Artefact du Studio", aide: "Un document, une synthèse, un tableau" },
  { kind: "salle", titre: "Salle de réunion", aide: "Une réunion et sa transcription" },
  { kind: "coffre", titre: "Élément du coffre", aide: "Un document, une session, une personne" },
];

function AjoutCarte({ projet, kindInitial, onAjout }: {
  projet: ProjetComplet;
  kindInitial?: CarteProjet["kind"];
  onAjout: () => void;
}) {
  const id = useId();
  const [kind, setKind] = useState<CarteProjet["kind"] | null>(kindInitial ?? null);
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

  if (kind === null) {
    return (
      <ul className="flex flex-col gap-2" aria-label="Que voulez-vous ajouter ?">
        {NATURES.map((n) => (
          <li key={n.kind}>
            <button
              type="button"
              onClick={() => setKind(n.kind)}
              className="flex w-full min-w-0 items-center gap-3 rounded-lg border border-border p-3 text-left hover:border-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-midground/10"><Icone kind={n.kind} /></span>
              <span className="flex min-w-0 flex-col">
                <span className="text-sm font-semibold">{n.titre}</span>
                <span className="text-xs text-text-secondary">{n.aide}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    );
  }

  const ajouter = async () => {
    const refId = kind === "coffre" ? (ref.trim() || libelle.trim()) : ref;
    if (!refId) return;
    // Rangées par nature, les unes sous les autres : le canevas reste lisible sans rien déplacer.
    const colonne = COLONNE[kind];
    const deLaColonne = projet.cartes.filter((c) => COLONNE[c.kind] === colonne);
    const y = deLaColonne.length ? Math.max(...deLaColonne.map((c) => c.y)) + 150 : 0;
    setEnvoi(true);
    setErreur(null);
    try {
      await vigil.projets.addCarte(projet.id, {
        kind,
        ref_id: refId,
        x: colonne * (LARGEUR + 90),
        y,
        ...(kind === "coffre" ? { sous_type: sousType, libelle: libelle.trim() || undefined } : {}),
      });
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
      className="flex min-w-0 flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void ajouter();
      }}
    >
      <button type="button" className="flex items-center gap-1 self-start text-xs text-text-secondary hover:text-foreground" onClick={() => { setKind(null); setRef(""); }}>
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Autre chose
      </button>

      {kind === "agent" && (
        <label className="flex min-w-0 flex-col gap-1 text-sm" htmlFor={`${id}-ref`}>
          Agent
          <select id={`${id}-ref`} className={champ} value={ref} onChange={(e) => setRef(e.target.value)}>
            <option value="">Choisir…</option>
            {AGENTS.filter((a) => !dejaPosees.has(a.id)).map((a) => <option key={a.id} value={a.id}>{a.nom} — {a.accroche}</option>)}
          </select>
        </label>
      )}
      {kind === "salle" && (
        <label className="flex min-w-0 flex-col gap-1 text-sm" htmlFor={`${id}-ref`}>
          Salle
          <select id={`${id}-ref`} className={champ} value={ref} onChange={(e) => setRef(e.target.value)} disabled={salles === null}>
            <option value="">{salles === null ? "Chargement…" : salles.length ? "Choisir…" : "Aucune salle"}</option>
            {(salles ?? []).filter((s) => !dejaPosees.has(s.id)).map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}
          </select>
        </label>
      )}
      {kind === "artefact" && (
        <label className="flex min-w-0 flex-col gap-1 text-sm" htmlFor={`${id}-ref`}>
          Artefact
          <select id={`${id}-ref`} className={champ} value={ref} onChange={(e) => setRef(e.target.value)} disabled={artefacts === null}>
            <option value="">{artefacts === null ? "Chargement…" : artefacts.length ? "Choisir…" : "Aucun artefact"}</option>
            {(artefacts ?? []).filter((a) => !dejaPosees.has(a.id)).map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
          </select>
        </label>
      )}
      {kind === "coffre" && (
        <>
          <label className="flex flex-col gap-1 text-sm">
            Ce que c'est
            <select className={champ} value={sousType} onChange={(e) => setSousType(e.target.value as typeof sousType)}>
              <option value="document">Document</option>
              <option value="session">Session</option>
              <option value="personne">Personne</option>
            </select>
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-sm">
            Intitulé
            <input className={champ} value={libelle} onChange={(e) => setLibelle(e.target.value)} maxLength={200} required />
          </label>
          <label className="flex min-w-0 flex-col gap-1 text-sm">
            <span>Référence <span className="text-text-secondary">(facultatif)</span></span>
            <input className={champ} value={ref} onChange={(e) => setRef(e.target.value)} maxLength={200} />
          </label>
        </>
      )}
      <Button type="submit" className="self-start" prefix={<Plus />} disabled={envoi || (kind === "coffre" ? !libelle.trim() : !ref)}>
        {envoi ? "Ajout…" : "Ajouter au projet"}
      </Button>
      {erreur != null && <Refus erreur={erreur} quoi="cette carte" compact />}
    </form>
  );
}

// ── Réglages du projet : ses six étapes, et sa suppression ──────────────────
function Reglages({ projet, peutModifier, onEtape, onSupprimer }: {
  projet: ProjetComplet;
  peutModifier: boolean;
  onEtape: (n: number) => void;
  onSupprimer: () => void;
}) {
  const [confirmer, setConfirmer] = useState(false);
  const objectif = projet.etapes[0]?.donnees?.objectif as string | undefined;
  return (
    <div className="flex min-w-0 flex-col gap-5">
      {objectif && <p className="break-words text-sm">{objectif}</p>}
      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold">Étapes · {projet.etapes_completes}/{projet.etapes_total}</h3>
        <p className="text-xs text-text-secondary">Plus les étapes sont remplies, plus les agents répondent au plus près du projet.</p>
        <ol className="flex flex-col gap-1.5">
          {projet.etapes.map((e) => (
            <li key={e.cle}>
              <button
                type="button"
                disabled={!peutModifier}
                onClick={() => onEtape(e.numero)}
                className="flex w-full min-w-0 items-center gap-3 rounded-md border border-border px-3 py-2 text-left text-sm enabled:hover:border-foreground disabled:cursor-default"
              >
                <span className={`size-2 shrink-0 rounded-full ${e.complete ? "bg-success" : "bg-midground/40"}`} aria-hidden />
                <span className="min-w-0 flex-1 break-words">{e.numero}. {e.titre}</span>
                <span className="shrink-0 text-xs text-text-secondary">{e.complete ? "Rempli" : "À remplir"}</span>
              </button>
            </li>
          ))}
        </ol>
      </section>
      {peutModifier && (
        <section className="flex flex-col gap-2 border-t border-border pt-4">
          <h3 className="text-sm font-semibold">Supprimer le projet</h3>
          <p className="text-xs text-text-secondary">Les salles, artefacts et documents liés ne sont pas supprimés.</p>
          {confirmer ? (
            <div className="flex flex-wrap gap-2">
              <Button destructive size="sm" onClick={onSupprimer}>Supprimer définitivement</Button>
              <Button ghost size="sm" onClick={() => setConfirmer(false)}>Garder</Button>
            </div>
          ) : (
            <Button outlined size="sm" className="self-start" onClick={() => setConfirmer(true)}>Supprimer…</Button>
          )}
        </section>
      )}
    </div>
  );
}

// ── L'espace de travail ─────────────────────────────────────────────────────
export function ProjetCanevas({
  projet,
  estAdmin,
  peutModifier,
  onRecharger,
  onEtape,
  onSupprimer,
}: {
  projet: ProjetComplet;
  estAdmin: boolean;
  peutModifier: boolean;
  onRecharger: () => void;
  onEtape: (n: number) => void;
  onSupprimer: () => void;
}) {
  const petitEcran = useBelowBreakpoint(768);
  const [enListe, setEnListe] = useState(false);
  const liste = petitEcran || enListe;
  const [travaux, setTravaux] = useState<TravailAgent[]>([]);
  const [erreur, setErreur] = useState<unknown>(null);
  const [vue, setVue] = useState<Vue>(null);
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
        labelStyle: { fontSize: 11 },
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
      setVue(null);
      onRecharger();
    } catch (e) {
      setErreur(e);
    }
  }, [projet.id, onRecharger]);

  const fermer = useCallback(() => setVue(null), []);
  const selection = vue?.type === "carte" ? vue.id : null;

  const contexte = useMemo<Contexte>(() => ({
    projetId: projet.id,
    estAdmin,
    peutModifier,
    travaux,
    selection,
    onTravail: (t) => setTravaux((prev) => [t, ...prev]),
    onRetirer: (id) => void retirer(id),
    onOuvrir: (id) => setVue({ type: "carte", id }),
  }), [projet.id, estAdmin, peutModifier, travaux, selection, retirer]);

  // Dans la liste : l'ordre du canevas, de haut en bas puis de gauche à droite.
  const ordonnees = useMemo(
    () => [...projet.cartes].sort((a, b) => a.y - b.y || a.x - b.x),
    [projet.cartes],
  );

  const carteOuverte = vue?.type === "carte" ? projet.cartes.find((c) => c.id === vue.id) : undefined;
  const panneau =
    vue?.type === "carte" && carteOuverte ? (
      <Panneau titre={carteOuverte.titre} sousTitre={libelleType(carteOuverte)} icone={<Icone kind={carteOuverte.kind} className="h-5 w-5" />} onFermer={fermer} petitEcran={petitEcran}>
        <DetailCarte key={carteOuverte.id} carte={carteOuverte} projet={projet} />
      </Panneau>
    ) : vue?.type === "ajout" ? (
      <Panneau titre="Ajouter au projet" sousTitre="Ce que vous posez ici, les agents le lisent." icone={<Plus className="h-5 w-5" />} onFermer={fermer} petitEcran={petitEcran}>
        <AjoutCarte projet={projet} kindInitial={vue.kind} onAjout={() => { setVue(null); onRecharger(); }} />
      </Panneau>
    ) : vue?.type === "reglages" ? (
      <Panneau titre="Réglages du projet" sousTitre={projet.titre} icone={<Settings2 className="h-5 w-5" />} onFermer={fermer} petitEcran={petitEcran}>
        <Reglages projet={projet} peutModifier={peutModifier} onEtape={onEtape} onSupprimer={onSupprimer} />
      </Panneau>
    ) : null;

  const vide = projet.cartes.length === 0;

  return (
    <ContexteCanevas.Provider value={contexte}>
      <section
        aria-label={`Projet ${projet.titre}`}
        className={`relative flex min-w-0 flex-col overflow-hidden rounded-xl border border-border ${
          liste ? (petitEcran ? "" : "min-h-[520px]") : "h-[calc(100dvh-9rem)] min-h-[520px]"
        }`}
      >
        {/* La barre du projet : son nom, ses étapes, et l'ajout — en haut à droite, comme sur Railway. */}
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-background/80 px-3 py-2 backdrop-blur">
          <Link to="/studio/projets" className="flex shrink-0 items-center gap-1 text-sm text-text-secondary hover:text-foreground">
            <ArrowLeft className="h-4 w-4" aria-hidden /> <span className="sr-only sm:not-sr-only">Projets</span>
          </Link>
          <h1 className="line-clamp-2 min-w-[8rem] flex-1 break-words text-base font-semibold leading-snug">{projet.titre}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setVue({ type: "reglages" })}
              aria-pressed={vue?.type === "reglages"}
              className="flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm hover:border-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Settings2 className="h-4 w-4" aria-hidden />
              <span>Étapes {projet.etapes_completes}/{projet.etapes_total}</span>
              <span className="hidden h-1.5 w-12 overflow-hidden rounded-full bg-midground/15 sm:block" aria-hidden>
                <span className="block h-full bg-success" style={{ width: `${(100 * projet.etapes_completes) / projet.etapes_total}%` }} />
              </span>
            </button>
            {!petitEcran && (
              <Button
                ghost
                size="icon"
                aria-pressed={enListe}
                aria-label={enListe ? "Afficher le canevas" : "Afficher en liste"}
                title={enListe ? "Afficher le canevas" : "Afficher en liste"}
                onClick={() => setEnListe((v) => !v)}
              >
                {enListe ? <Network className="h-4 w-4" /> : <LayoutList className="h-4 w-4" />}
              </Button>
            )}
            {peutModifier && (
              <Button size="sm" prefix={<Plus />} onClick={() => setVue({ type: "ajout" })}>Ajouter</Button>
            )}
          </div>
        </div>

        {erreur != null && <div className="p-3"><Refus erreur={erreur} quoi="le canevas" compact /></div>}

        {vide ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <div className="flex max-w-md flex-col items-center gap-3 text-center">
              <span className="grid size-12 place-items-center rounded-xl bg-midground/10"><Network className="h-6 w-6" aria-hidden /></span>
              <h2 className="text-base font-semibold">Le canevas est vide</h2>
              <p className="text-sm text-text-secondary">
                Posez un agent pour le faire travailler sur ce projet, et les artefacts, salles ou documents qu'il doit connaître.
              </p>
              {peutModifier && (
                <div className="flex flex-wrap justify-center gap-2">
                  <Button prefix={<Bot />} onClick={() => setVue({ type: "ajout", kind: "agent" })}>Ajouter un agent</Button>
                  <Button outlined prefix={<Plus />} onClick={() => setVue({ type: "ajout" })}>Autre chose</Button>
                </div>
              )}
            </div>
          </div>
        ) : liste ? (
          <ul className="grid min-w-0 gap-3 p-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Cartes du projet">
            {ordonnees.map((c) => (
              <li key={c.id} className="min-w-0">
                <button
                  type="button"
                  onClick={() => setVue({ type: "carte", id: c.id })}
                  className="block w-full min-w-0 rounded-xl text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Vignette carte={c} active={selection === c.id} />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <div className="min-h-0 flex-1">
            <ReactFlow<NoeudCarte, Edge>
              nodes={noeuds}
              edges={aretes}
              nodeTypes={typesDeNoeuds}
              onNodesChange={changer}
              onNodeClick={(_, n) => setVue({ type: "carte", id: n.id })}
              onPaneClick={() => setVue((v) => (v?.type === "carte" ? null : v))}
              onKeyDown={(e) => {
                // Entrée sur une carte au clavier l'ouvre, comme un clic.
                const id = (e.target as HTMLElement).closest?.(".react-flow__node")?.getAttribute("data-id");
                if (e.key === "Enter" && id) setVue({ type: "carte", id });
              }}
              nodesDraggable={peutModifier}
              nodesConnectable={false}
              elementsSelectable
              fitView
              // Lisible d'abord : sous 80 %, on déplace le canevas plutôt que de rétrécir les cartes.
              fitViewOptions={{ padding: 0.2, minZoom: 0.8, maxZoom: 1 }}
              minZoom={0.3}
              maxZoom={1.5}
              proOptions={{ hideAttribution: true }}
              ariaLabelConfig={ETIQUETTES_ARIA}
            >
              <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} />
              <Controls showInteractive={false} position="bottom-left" />
            </ReactFlow>
          </div>
        )}

        {panneau}
      </section>
    </ContexteCanevas.Provider>
  );
}

export default ProjetCanevas;
