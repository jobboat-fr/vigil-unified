import { useCallback, useEffect, useState } from "react";
import { Button } from "@nous-research/ui/ui/components/button";
import { support, type Demande } from "@/lib/compte";

const STATUTS: Record<Demande["status"], string> = { open: "À traiter", answered: "Répondu", closed: "Clos" };

/** Les demandes d'aide de l'organisme (l'éditeur voit toutes les demandes, y compris celles du site). */
export default function SupportBoitePage() {
  const [filtre, setFiltre] = useState<Demande["status"] | "">("open");
  const [demandes, setDemandes] = useState<Demande[] | null>(null);
  const [ouverte, setOuverte] = useState<string | null>(null);
  const [reponse, setReponse] = useState("");
  const [erreur, setErreur] = useState("");

  const charger = useCallback(async () => {
    try {
      setDemandes((await support.boite(filtre || undefined)).demandes);
      setErreur("");
    } catch (e) {
      setDemandes([]);
      setErreur((e as Error).message);
    }
  }, [filtre]);

  useEffect(() => { void charger(); }, [charger]);

  const repondre = async (d: Demande) => {
    try {
      await support.repondre(d.id, reponse.trim());
      setReponse("");
      await charger();
    } catch (e) {
      setErreur((e as Error).message);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 pb-10">
      <div className="flex flex-wrap gap-1" role="tablist">
        {(["open", "answered", "closed", ""] as const).map((s) => (
          <button key={s || "tout"} type="button" role="tab" aria-selected={filtre === s} onClick={() => setFiltre(s)}
            className="rounded-md px-3 py-1.5 text-sm" style={{ background: filtre === s ? "rgba(127,127,127,.15)" : "transparent" }}>
            {s ? STATUTS[s] : "Toutes"}
          </button>
        ))}
      </div>
      {erreur && <p className="text-sm" style={{ color: "#e11d48" }}>{erreur}</p>}
      {demandes === null ? (
        <div className="h-24 animate-pulse rounded-xl bg-current/5" />
      ) : demandes.length === 0 ? (
        <p className="py-8 text-center text-sm text-text-secondary">Aucune demande {filtre ? `« ${STATUTS[filtre as Demande["status"]].toLowerCase()} »` : ""}. Tout est à jour.</p>
      ) : (
        demandes.map((d) => (
          <article key={d.id} className="rounded-xl border border-current/15">
            <button type="button" onClick={() => setOuverte(ouverte === d.id ? null : d.id)} className="flex w-full flex-wrap items-center justify-between gap-2 p-4 text-left">
              <span className="min-w-0">
                <span className="block font-medium">{d.subject}</span>
                <span className="text-xs text-text-secondary">{d.email} · {d.source === "site" ? "site public" : "application"} · {new Date(d.created_at).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" })}</span>
              </span>
              <span className="rounded-full border border-current/20 px-2 py-0.5 text-xs">{STATUTS[d.status] ?? d.status}</span>
            </button>
            {ouverte === d.id && (
              <div className="flex flex-col gap-3 border-t border-current/10 p-4">
                {d.messages.map((m, i) => (
                  <div key={i} className={`rounded-lg p-3 text-sm ${m.auteur === "staff" ? "ml-6 bg-current/5" : "mr-6 border border-current/10"}`}>
                    <p className="mb-1 text-xs text-text-secondary">{m.auteur === "staff" ? "Réponse" : m.email} · {new Date(m.le).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</p>
                    <p className="whitespace-pre-wrap">{m.texte}</p>
                  </div>
                ))}
                <textarea rows={3} value={reponse} onChange={(e) => setReponse(e.target.value)} placeholder="Votre réponse"
                  className="rounded-md border border-current/20 bg-transparent px-3 py-2 text-base outline-none" />
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => void repondre(d)} disabled={!reponse.trim()}>Répondre</Button>
                  {d.status !== "closed" && <Button ghost onClick={() => void support.statut(d.id, "closed").then(charger)}>Clore</Button>}
                </div>
              </div>
            )}
          </article>
        ))
      )}
    </div>
  );
}
