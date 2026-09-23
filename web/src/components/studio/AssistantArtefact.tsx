import { useState } from "react";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, type Artifact } from "@/lib/vigil";
import { expliquerCourt } from "@/lib/refus";

const LENSES: { id: string; label: string }[] = [
  { id: "ideas", label: "Des idées" },
  { id: "expand", label: "Approfondir" },
  { id: "risks", label: "Les risques" },
  { id: "missing", label: "Ce qui manque" },
  { id: "next_steps", label: "Prochaines étapes" },
  { id: "critique", label: "Avocat du diable" },
  { id: "summarize", label: "Synthèse" },
  { id: "council", label: "Tour de table" },
];

/**
 * L'assistant écrit dans l'artefact ouvert. Sur un tableau il ajoute des blocs sous l'existant,
 * sans rien effacer ; sur un document il rend la version révisée (l'ancienne reste dans l'historique).
 */
export function AssistantArtefact({
  artifact,
  onUpdated,
}: {
  artifact: Artifact;
  onUpdated: (a: Artifact) => void;
}) {
  const estTableau = !!(artifact.tldraw || (artifact.canvas && !artifact.content.trim()));
  const [consigne, setConsigne] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [retour, setRetour] = useState<{ ton: "ok" | "erreur"; texte: string } | null>(null);

  const lancer = async (lens?: string) => {
    if (!estTableau && !consigne.trim()) return;
    setBusy(lens ?? "consigne");
    setRetour(null);
    try {
      const r = await vigil.studio.agent(artifact.id, { instruction: consigne.trim(), lens });
      onUpdated(r.artifact);
      setConsigne("");
      setRetour({ ton: "ok", texte: r.stub ? `${r.resume} (mode démonstration : aucun modèle configuré)` : r.resume });
    } catch (e) {
      setRetour({ ton: "erreur", texte: `${expliquerCourt(e)} Votre ${estTableau ? "tableau" : "document"} n'a pas été modifié.` });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-2 rounded-md border border-current/10 p-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-text-secondary">
        {estTableau ? "Réfléchir avec l'assistant" : "Faire écrire l'assistant"}
      </p>
      {estTableau && (
        <div className="flex flex-wrap gap-1.5">
          {LENSES.map((l) => (
            <button
              key={l.id}
              type="button"
              disabled={!!busy}
              onClick={() => void lancer(l.id)}
              className="rounded-full border border-current/20 px-2.5 py-1 text-xs hover:border-current/50 disabled:opacity-50"
            >
              {busy === l.id ? "…" : l.label}
            </button>
          ))}
        </div>
      )}
      <textarea
        className="w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50"
        rows={2}
        placeholder={estTableau
          ? "Ou dites-lui quoi chercher : « des activités pour une classe de 12 débutants »"
          : "Ce qu'il doit changer : « raccourcis l'introduction et ajoute un calendrier sur trois semaines »"}
        value={consigne}
        onChange={(e) => setConsigne(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void lancer(estTableau ? "expand" : undefined); }}
      />
      <Button onClick={() => void lancer(estTableau ? "expand" : undefined)} disabled={!!busy || !consigne.trim()} className="w-full">
        {busy === "consigne" || busy === "expand" ? "L'assistant écrit…" : estTableau ? "Ajouter au tableau" : "Réviser le document"}
      </Button>
      {retour && (
        <p className="text-xs" role="status" style={{ color: retour.ton === "ok" ? "var(--color-success)" : "var(--color-destructive)" }}>{retour.texte}</p>
      )}
    </div>
  );
}
