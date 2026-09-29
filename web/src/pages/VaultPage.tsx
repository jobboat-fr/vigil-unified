import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FilePlus2, FolderKanban, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Refus } from "@/components/Refus";
import { useLearnRole } from "@/lib/supabase";
import { vigil, type Artifact } from "@/lib/vigil";
import { ww } from "@/lib/ww";

/**
 * Artéfacts — ce que l'on a produit, au même endroit.
 *
 * La page s'appelait « Artéfacts » dans le menu mais affichait le coffre documentaire hérité
 * de VIGIL (« Document Vault · 0 »), vide et sans moyen d'y déposer quoi que ce soit (capture
 * d'Azer, 29/09). Les artéfacts réels — documents du Studio, synthèses de réunion, travaux
 * d'agent — n'y figuraient pas. Ils sont ici désormais : les miens, ceux partagés avec moi,
 * et, pour l'administration, ceux de l'organisme. Chacun s'ouvre dans le Studio.
 */

const TYPE: Record<string, string> = {
  proposal: "Proposition",
  brief: "Cahier des charges",
  contract: "Contrat",
  memo: "Note de décision",
  report: "Rapport",
};

type Onglet = "moi" | "partages" | "organisme";

const quand = (iso: string) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const jours = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (jours <= 0) return `aujourd'hui, ${d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`;
  if (jours === 1) return "hier";
  if (jours < 7) return `il y a ${jours} jours`;
  return d.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
};

interface VaultDoc {
  id?: string;
  filename?: string;
  title?: string;
  category?: string;
  summary?: string;
}

function Ligne({ a, onOuvrir }: { a: Artifact; onOuvrir: () => void }) {
  return (
    <li>
      <button
        type="button"
        onClick={onOuvrir}
        className="flex w-full flex-col gap-1 rounded-lg border border-midground/15 p-3 text-left transition-colors hover:bg-midground/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-current"
      >
        <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="min-w-0 break-words font-medium">{a.title || "Sans titre"}</span>
          <span className="shrink-0 text-xs text-text-secondary">{quand(a.updated_at)}</span>
        </span>
        <span className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-text-secondary">
          <span>{TYPE[a.kind] ?? "Document"}</span>
          {a.revisions > 1 && <span>{a.revisions} versions</span>}
          {a.owner_name && <span>de {a.owner_name}</span>}
          {a.access === "view" && <span>lecture seule</span>}
          {a.stub && <span className="text-warning">brouillon — l'assistant était indisponible</span>}
        </span>
        {a.brief && <span className="line-clamp-2 text-sm text-text-secondary">{a.brief}</span>}
      </button>
    </li>
  );
}

export default function VaultPage() {
  const navigate = useNavigate();
  const { role } = useLearnRole();
  const admin = role === "admin" || role === "super_admin";
  const [onglet, setOnglet] = useState<Onglet>("moi");
  const [miens, setMiens] = useState<Artifact[]>([]);
  const [partages, setPartages] = useState<Artifact[]>([]);
  const [organisme, setOrganisme] = useState<Artifact[] | null>(null);
  const [docs, setDocs] = useState<VaultDoc[]>([]);
  const [erreur, setErreur] = useState<unknown>(null);
  const [charge, setCharge] = useState(false);
  const [filtre, setFiltre] = useState("");

  const charger = async () => {
    setErreur(null);
    try {
      const r = await vigil.studio.list();
      setMiens(r.artifacts);
      setPartages(r.shared_with_me);
    } catch (e) {
      setErreur(e);
    } finally {
      setCharge(true);
    }
    // Le coffre documentaire hérité : affiché seulement s'il contient quelque chose.
    try {
      const d = (await ww.vault.list()) as VaultDoc[];
      setDocs(Array.isArray(d) ? d : []);
    } catch {
      setDocs([]);
    }
  };

  useEffect(() => { void charger(); }, []);

  useEffect(() => {
    if (onglet !== "organisme" || organisme !== null) return;
    vigil.studio.listOrganisme().then((r) => setOrganisme(r.artifacts)).catch((e) => setErreur(e));
  }, [onglet, organisme]);

  const liste = onglet === "moi" ? miens : onglet === "partages" ? partages : (organisme ?? []);
  const visibles = useMemo(() => {
    const f = filtre.trim().toLowerCase();
    if (!f) return liste;
    return liste.filter((a) => [a.title, a.brief, TYPE[a.kind]].some((x) => (x ?? "").toLowerCase().includes(f)));
  }, [liste, filtre]);

  const ONGLETS: { id: Onglet; libelle: string; n: number | null }[] = [
    { id: "moi", libelle: "Les miens", n: miens.length },
    { id: "partages", libelle: "Partagés avec moi", n: partages.length },
    ...(admin ? [{ id: "organisme" as const, libelle: "L'organisme", n: organisme?.length ?? null }] : []),
  ];

  return (
    <div className="flex w-full min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-prose text-sm text-text-secondary">
          Ce qui a été produit : documents du Studio, synthèses de réunion, travaux des agents dans vos projets.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" outlined prefix={<FolderKanban />} onClick={() => navigate("/studio/projets")}>Projets</Button>
          <Button size="sm" prefix={<FilePlus2 />} onClick={() => navigate("/studio")}>Nouveau document</Button>
        </div>
      </div>

      <div role="tablist" aria-label="Quels artéfacts" className="flex flex-wrap gap-1 border-b border-midground/15">
        {ONGLETS.map((o) => (
          <button
            key={o.id}
            role="tab"
            type="button"
            aria-selected={onglet === o.id}
            onClick={() => setOnglet(o.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${onglet === o.id ? "border-midground text-midground" : "border-transparent text-text-secondary hover:text-midground"}`}
          >
            {o.libelle}{o.n !== null && <span className="ml-1.5 text-text-secondary">{o.n}</span>}
          </button>
        ))}
      </div>

      <label className="relative block">
        <span className="sr-only">Chercher un artéfact</span>
        <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-text-secondary" />
        <input
          value={filtre}
          onChange={(e) => setFiltre(e.target.value)}
          placeholder="Chercher par titre, type ou objet…"
          className="w-full rounded-md border border-midground/20 bg-transparent py-2.5 pl-9 pr-3 text-sm"
        />
      </label>

      {erreur != null ? (
        <Refus erreur={erreur} quoi="les artéfacts" onReessayer={() => void charger()} />
      ) : !charge ? (
        <p className="py-8 text-center text-sm text-text-secondary">Chargement…</p>
      ) : visibles.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
            <p className="max-w-md text-sm text-text-secondary">
              {filtre
                ? "Aucun artéfact ne correspond à cette recherche."
                : onglet === "partages"
                  ? "Personne n'a encore partagé de document avec vous."
                  : "Rien ici pour l'instant. Un artéfact naît au Studio, à la clôture d'une réunion (sa synthèse), ou quand un agent travaille dans un projet."}
            </p>
            {!filtre && onglet === "moi" && (
              <div className="flex flex-wrap justify-center gap-2">
                <Button size="sm" onClick={() => navigate("/studio")}>Créer un document</Button>
                <Button size="sm" outlined onClick={() => navigate("/studio/projets")}>Ouvrir un projet</Button>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <ul className="flex flex-col gap-2">
          {visibles.map((a) => <Ligne key={a.id} a={a} onOuvrir={() => navigate(`/studio?artifact=${a.id}`)} />)}
        </ul>
      )}

      {docs.length > 0 && (
        <section className="flex flex-col gap-2 pt-2">
          <h2 className="text-sm font-semibold text-midground/80">Documents déposés · {docs.length}</h2>
          <ul className="flex flex-col gap-2">
            {docs.map((d, i) => (
              <li key={d.id ?? i} className="rounded-lg border border-midground/15 p-3">
                <span className="break-words font-medium">{d.title || d.filename || "Sans titre"}</span>
                {d.category && <span className="ml-2 text-xs text-text-secondary">{d.category}</span>}
                {d.summary && <p className="mt-1 line-clamp-2 text-xs text-text-secondary">{d.summary}</p>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
