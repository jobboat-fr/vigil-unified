import { lazy, Suspense, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { openSharedArtifact, type SharedArtifactPublic } from "@/lib/vigil";
import type { GatewayError } from "@/lib/ww";
import { KIND_LABELS, dateLongue } from "@/lib/studio";
import { BlocMarqueVtlvs } from "@/components/MarqueVtlvs";
import { expliquerCourt } from "@/lib/refus";

const ArtifactCanvas = lazy(() => import("@/components/ArtifactCanvas").then((m) => ({ default: m.ArtifactCanvas })));

/**
 * Un document du studio ouvert par son lien de partage. Sans compte, en lecture seule.
 * La page dit ce qu'elle est (un partage, jusqu'à quand) et ne propose rien qu'on ne puisse faire.
 */
export default function PartageArtefactPage() {
  const { token = "" } = useParams();
  const [art, setArt] = useState<SharedArtifactPublic | null>(null);
  const [erreur, setErreur] = useState<{ titre: string; texte: string } | null>(null);

  useEffect(() => {
    openSharedArtifact(token)
      .then((a) => {
        setArt(a);
        document.title = `${a.title} — partagé via VTLVS`;
      })
      .catch((e: GatewayError) => {
        const code = (e.detail as { error?: string } | undefined)?.error;
        if (code === "lien_expire")
          setErreur({ titre: "Ce lien a expiré", texte: "Les liens de partage ont une durée de vie limitée. Demandez un nouveau lien à la personne qui vous l'a envoyé." });
        else if (code === "lien_invalide" || e.status === 404)
          setErreur({ titre: "Ce lien ne mène nulle part", texte: "Il a peut-être été remplacé par un lien plus récent, ou retiré par son auteur." });
        // `e.message` vaut le plus souvent « HTTP 502 » : un code de journal, montré à
        // quelqu'un qui a seulement cliqué sur un lien reçu. Les deux cas au-dessus
        // gardent leur texte — cette page est publique, et son vocabulaire lui est
        // propre ; seul le cas restant passe par le traducteur commun.
        else setErreur({ titre: "Le document ne s'ouvre pas", texte: expliquerCourt(e, "ce document") });
      });
  }, [token]);

  const aTableau = !!art && !!(art.canvas || art.tldraw);

  return (
    <div className="min-h-dvh px-4 py-8" style={{ background: "#F4F6FA", color: "#0B2239" }}>
      <div className="mx-auto w-full max-w-4xl">
        <div className="mb-4 flex items-center justify-between gap-3 text-xs" style={{ color: "#5B6B7F" }}>
          <span className="rounded-full border px-2.5 py-1" style={{ borderColor: "#CBD5E1" }}>Lecture seule</span>
          {art?.expires_at && <span>Lien valable jusqu'au {dateLongue(art.expires_at)}</span>}
        </div>
        <div className="overflow-hidden rounded-xl bg-white shadow-sm">
          {erreur ? (
            <div className="px-6 py-10 text-center">
              <h1 className="text-xl font-bold">{erreur.titre}</h1>
              <p className="mx-auto mt-3 max-w-md text-sm" style={{ color: "#40526A" }}>{erreur.texte}</p>
            </div>
          ) : !art ? (
            <div className="animate-pulse space-y-3 px-6 py-8" aria-label="Chargement du document">
              <div className="h-6 w-2/3 rounded bg-slate-200" />
              <div className="h-3 w-1/4 rounded bg-slate-100" />
              <div className="h-3 w-full rounded bg-slate-100" />
              <div className="h-3 w-5/6 rounded bg-slate-100" />
            </div>
          ) : (
            <>
              <div className="px-6 pt-6 pb-4" style={{ borderBottom: "3px solid #1D3FAE" }}>
                <p className="text-xs uppercase tracking-wide" style={{ color: "#5B6B7F" }}>
                  {KIND_LABELS[art.kind] ?? "Document"} · mis à jour le {dateLongue(art.updated_at)}
                </p>
                <h1 className="mt-1 text-2xl font-bold">{art.title}</h1>
              </div>
              {aTableau ? (
                <Suspense fallback={<div className="p-10 text-center text-sm">Ouverture du tableau…</div>}>
                  <ArtifactCanvas artifact={{ id: token, title: art.title, canvas: art.canvas, tldraw: art.tldraw }} lectureSeule />
                </Suspense>
              ) : (
                <article className="whitespace-pre-wrap px-6 py-6 text-[15px] leading-relaxed">{art.content || "Ce document est vide."}</article>
              )}
            </>
          )}
        </div>
        <a href="https://vtlvs.com" className="mt-6 flex flex-col items-center gap-1 text-[11px]" style={{ color: "#5B6B7F" }}>
          <BlocMarqueVtlvs hauteur={14} />
          Partagé via VTLVS
        </a>
      </div>
    </div>
  );
}
