import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Refus } from "@/components/Refus";
import { AGENTS } from "@/lib/agentique";
import { vigil, type CleEtape, type EtapeProjet } from "@/lib/vigil";

/**
 * L'assistant de création d'un projet : les six étapes, une par écran.
 *
 * Chaque étape est enregistrée à part (PATCH …/etapes/{cle}) au moment où l'on passe à la
 * suivante : quitter à mi-chemin ne perd rien, et revenir sur une étape reprend ce qui a été
 * saisi. La forme de chaque étape est vérifiée par la passerelle ; ce qu'elle refuse revient
 * ici, champ par champ.
 */

const champ =
  "w-full min-w-0 rounded-md border border-border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
const etiquette = "flex flex-col gap-1 text-sm";

type Ligne = Record<string, string>;
type Valeurs = Record<string, unknown>;

/** Ce que l'étape contient déjà, ou un point de départ vide. */
function depart(etape: EtapeProjet): Valeurs {
  const d = etape.donnees ?? {};
  switch (etape.cle) {
    case "nom_objectif":
      return { nom: d.nom ?? "", objectif: d.objectif ?? "" };
    case "perimetre_livrables":
      return { perimetre: d.perimetre ?? "", livrables: ((d.livrables as string[]) ?? []).join("\n") };
    case "equipe":
      return { membres: (d.membres as Ligne[]) ?? [] };
    case "jalons":
      return { jalons: (d.jalons as Ligne[]) ?? [] };
    case "ressources":
      return { ressources: (d.ressources as Ligne[]) ?? [] };
    case "validation":
      return { valideur: d.valideur ?? "", statut: d.statut ?? "brouillon" };
  }
}

/** La forme attendue par la passerelle. Les lignes vides sont écartées, pas envoyées. */
function versServeur(cle: CleEtape, v: Valeurs): Record<string, unknown> {
  const lignes = (k: string) => ((v[k] as Ligne[]) ?? []).filter((l) => Object.values(l).some((x) => String(x ?? "").trim()));
  switch (cle) {
    case "nom_objectif":
      return { nom: String(v.nom ?? "").trim(), objectif: String(v.objectif ?? "").trim() };
    case "perimetre_livrables":
      return {
        perimetre: String(v.perimetre ?? "").trim(),
        livrables: String(v.livrables ?? "").split("\n").map((s) => s.trim()).filter(Boolean),
      };
    case "equipe":
      return {
        membres: lignes("membres").map((m) => ({
          kind: m.kind === "agent" ? "agent" : "personne",
          id: (m.id ?? "").trim(),
          role: (m.role ?? "").trim(),
          ...(m.kind !== "agent" && m.id ? { nom: m.id.trim() } : {}),
        })),
      };
    case "jalons":
      return { jalons: lignes("jalons").map((j) => ({ titre: (j.titre ?? "").trim(), echeance: j.echeance ?? "" })) };
    case "ressources":
      return {
        ressources: lignes("ressources").map((r) => ({
          titre: (r.titre ?? "").trim(),
          url: (r.url ?? "").trim() || null,
          note: (r.note ?? "").trim() || null,
        })),
      };
    case "validation":
      return { valideur: String(v.valideur ?? "").trim(), statut: v.statut ?? "brouillon" };
  }
}

/** Une liste de lignes éditables (équipe, jalons, ressources). */
function Lignes({
  legende,
  lignes,
  vide,
  onChange,
  rendu,
}: {
  legende: string;
  lignes: Ligne[];
  vide: Ligne;
  onChange: (l: Ligne[]) => void;
  rendu: (l: Ligne, maj: (patch: Ligne) => void, i: number) => React.ReactNode;
}) {
  return (
    <fieldset className="flex min-w-0 flex-col gap-3">
      <legend className="mb-1 text-sm font-medium">{legende}</legend>
      {lignes.length === 0 && <p className="text-xs text-text-secondary">Aucune ligne pour l'instant.</p>}
      {lignes.map((l, i) => (
        <div key={i} className="flex min-w-0 flex-col gap-2 rounded-md border border-border p-3">
          {rendu(l, (patch) => onChange(lignes.map((x, j) => (j === i ? { ...x, ...patch } : x))), i)}
          <button
            type="button"
            className="self-start text-xs text-text-secondary underline hover:text-foreground"
            onClick={() => onChange(lignes.filter((_, j) => j !== i))}
          >
            Retirer cette ligne
          </button>
        </div>
      ))}
      <Button type="button" ghost className="self-start" onClick={() => onChange([...lignes, { ...vide }])}>
        + Ajouter une ligne
      </Button>
    </fieldset>
  );
}

function Formulaire({ cle, v, setV }: { cle: CleEtape; v: Valeurs; setV: (v: Valeurs) => void }) {
  const id = useId();
  const set = (k: string) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  switch (cle) {
    case "nom_objectif":
      return (
        <div className="flex flex-col gap-4">
          <label className={etiquette}>
            Nom du projet
            <input className={champ} value={String(v.nom)} onChange={set("nom")} maxLength={200} required autoFocus />
          </label>
          <label className={etiquette}>
            Objectif
            <textarea className={champ} rows={4} value={String(v.objectif)} onChange={set("objectif")} maxLength={4000}
              placeholder="Ce que le projet doit changer, en une ou deux phrases." />
          </label>
        </div>
      );
    case "perimetre_livrables":
      return (
        <div className="flex flex-col gap-4">
          <label className={etiquette}>
            Périmètre
            <textarea className={champ} rows={4} value={String(v.perimetre)} onChange={set("perimetre")} maxLength={4000}
              placeholder="Ce qui est dans le projet, et ce qui n'y est pas." />
          </label>
          <label className={etiquette}>
            Livrables <span className="text-xs text-text-secondary">(un par ligne)</span>
            <textarea className={champ} rows={4} value={String(v.livrables)} onChange={set("livrables")} />
          </label>
        </div>
      );
    case "equipe":
      return (
        <Lignes
          legende="Personnes et agents"
          lignes={v.membres as Ligne[]}
          vide={{ kind: "personne", id: "", role: "" }}
          onChange={(membres) => setV({ ...v, membres })}
          rendu={(m, maj, i) => (
            <div className="grid min-w-0 gap-2 sm:grid-cols-3">
              <label className={etiquette}>
                Qui
                <select className={champ} value={m.kind} onChange={(e) => maj({ kind: e.target.value, id: "" })}>
                  <option value="personne">Une personne</option>
                  <option value="agent">Un agent</option>
                </select>
              </label>
              {m.kind === "agent" ? (
                <label className={etiquette}>
                  Agent
                  <select className={champ} value={m.id} onChange={(e) => maj({ id: e.target.value })} id={`${id}-agent-${i}`}>
                    <option value="">Choisir…</option>
                    {AGENTS.map((a) => <option key={a.id} value={a.id}>{a.nom}</option>)}
                  </select>
                </label>
              ) : (
                <label className={etiquette}>
                  Nom ou adresse e-mail
                  <input className={champ} value={m.id} onChange={(e) => maj({ id: e.target.value })} maxLength={200} />
                </label>
              )}
              <label className={etiquette}>
                Rôle dans le projet
                <input className={champ} value={m.role} onChange={(e) => maj({ role: e.target.value })} maxLength={200} />
              </label>
            </div>
          )}
        />
      );
    case "jalons":
      return (
        <Lignes
          legende="Jalons datés"
          lignes={v.jalons as Ligne[]}
          vide={{ titre: "", echeance: "" }}
          onChange={(jalons) => setV({ ...v, jalons })}
          rendu={(j, maj) => (
            <div className="grid min-w-0 gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
              <label className={etiquette}>
                Jalon
                <input className={champ} value={j.titre} onChange={(e) => maj({ titre: e.target.value })} maxLength={200} />
              </label>
              <label className={etiquette}>
                Échéance
                <input type="date" className={champ} value={j.echeance} onChange={(e) => maj({ echeance: e.target.value })} />
              </label>
            </div>
          )}
        />
      );
    case "ressources":
      return (
        <Lignes
          legende="Liens et documents utiles"
          lignes={v.ressources as Ligne[]}
          vide={{ titre: "", url: "", note: "" }}
          onChange={(ressources) => setV({ ...v, ressources })}
          rendu={(r, maj) => (
            <div className="grid min-w-0 gap-2 sm:grid-cols-2">
              <label className={etiquette}>
                Intitulé
                <input className={champ} value={r.titre} onChange={(e) => maj({ titre: e.target.value })} maxLength={200} />
              </label>
              <label className={etiquette}>
                Lien <span className="text-xs text-text-secondary">(https://… ou /page)</span>
                <input className={champ} value={r.url ?? ""} onChange={(e) => maj({ url: e.target.value })} inputMode="url" />
              </label>
              <label className={`${etiquette} sm:col-span-2`}>
                Note
                <input className={champ} value={r.note ?? ""} onChange={(e) => maj({ note: e.target.value })} maxLength={1000} />
              </label>
            </div>
          )}
        />
      );
    case "validation":
      return (
        <div className="flex flex-col gap-4">
          <label className={etiquette}>
            Qui valide
            <input className={champ} value={String(v.valideur)} onChange={set("valideur")} maxLength={200}
              placeholder="Une personne ou une instance : la direction, le comité pédagogique…" />
          </label>
          <label className={etiquette}>
            Où en est la validation
            <select className={champ} value={String(v.statut)} onChange={set("statut")}>
              <option value="brouillon">Brouillon</option>
              <option value="en_validation">En validation</option>
              <option value="valide">Validé</option>
            </select>
          </label>
        </div>
      );
  }
}

export function AssistantProjet({
  projetId,
  etapes,
  numero,
  onEtape,
  onEnregistre,
  onTerminer,
}: {
  projetId: string;
  etapes: EtapeProjet[];
  /** 1 à 6. */
  numero: number;
  onEtape: (n: number) => void;
  onEnregistre: (etapes: EtapeProjet[]) => void;
  onTerminer: () => void;
}) {
  const etape = etapes[numero - 1];
  const [valeurs, setValeursBrutes] = useState<Valeurs>(() => depart(etape));
  // Une étape qu'on traverse sans rien y changer n'est pas enregistrée : elle serait marquée
  // « faite » alors que personne ne l'a remplie. « Continuer », lui, enregistre toujours.
  const [modifie, setModifie] = useState(false);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<unknown>(null);
  const titreId = useId();
  const setValeurs = (v: Valeurs) => {
    setValeursBrutes(v);
    setModifie(true);
  };

  const aller = (vers: number | "canevas") => (vers === "canevas" ? onTerminer() : onEtape(vers));

  const enregistrer = async (vers: number | "canevas", toujours = false) => {
    if (!toujours && !modifie) {
      aller(vers);
      return;
    }
    setEnvoi(true);
    setErreur(null);
    try {
      const p = await vigil.projets.saveEtape(projetId, etape.cle, versServeur(etape.cle, valeurs));
      onEnregistre(p.etapes);
      aller(vers);
    } catch (e) {
      setErreur(e);
    } finally {
      setEnvoi(false);
    }
  };
  const suivante: number | "canevas" = numero < etapes.length ? numero + 1 : "canevas";

  const champs = (() => {
    const d = (erreur as { detail?: { champs?: { champ: string; message: string }[] } } | null)?.detail?.champs;
    return Array.isArray(d) ? d : [];
  })();

  return (
    <Card className="min-w-0">
      <CardHeader>
        <ol className="mb-3 flex flex-wrap gap-1.5" aria-label="Étapes du projet">
          {etapes.map((e) => (
            <li key={e.cle}>
              <button
                type="button"
                disabled={envoi}
                onClick={() => void enregistrer(e.numero)}
                aria-current={e.numero === numero ? "step" : undefined}
                className={`rounded-full border px-2.5 py-0.5 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                  e.numero === numero ? "border-foreground font-semibold" : "border-border text-text-secondary"
                }`}
              >
                {e.numero}. {e.titre}
                {e.complete && <span className="ml-1 text-success" aria-label="(enregistrée)">✓</span>}
              </button>
            </li>
          ))}
        </ol>
        <CardTitle id={titreId}>
          Étape {numero} sur {etapes.length} — {etape.titre}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <form
          aria-labelledby={titreId}
          className="flex min-w-0 flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault();
            void enregistrer(suivante, true);
          }}
        >
          <Formulaire cle={etape.cle} v={valeurs} setV={setValeurs} />
          {erreur != null && (
            <div aria-live="polite">
              <Refus erreur={erreur} quoi="cette étape" compact />
              {champs.length > 0 && (
                <ul className="mt-2 list-disc pl-5 text-xs text-destructive">
                  {champs.map((c, i) => <li key={i}>{c.champ} : {c.message}</li>)}
                </ul>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button type="button" ghost disabled={numero === 1 || envoi} onClick={() => void enregistrer(numero - 1)}>
              ← Précédent
            </Button>
            <div className="flex flex-wrap gap-2">
              <Button type="button" ghost disabled={envoi} onClick={() => void enregistrer("canevas")}>
                Aller au canevas
              </Button>
              <Button type="submit" disabled={envoi}>
                {envoi ? "Enregistrement…" : numero < etapes.length ? "Enregistrer et continuer →" : "Enregistrer et ouvrir le canevas"}
              </Button>
            </div>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
