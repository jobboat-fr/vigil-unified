import { useEffect, useRef, useState } from "react";
import { Skeleton } from "@/components/EmptyState";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { getDocumentALire, messageAccueil, signerDocument, type DocumentALire } from "@/lib/accueil";

/**
 * Lire, puis signer. Le document s'affiche dans un cadre isolé (le HTML vient de l'organisme,
 * il n'a pas accès à la page). La signature n'est possible qu'après avoir fait défiler le
 * document jusqu'au bout, en saisissant son nom et en cochant le consentement. L'empreinte du
 * document lu part avec la signature : si le document a changé entretemps, le serveur refuse.
 */
export default function SignerDocumentPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState<DocumentALire | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [luJusquauBout, setLu] = useState(false);
  const [nom, setNom] = useState("");
  const [accord, setAccord] = useState(false);
  const [attente, setAttente] = useState(false);
  const cadre = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    getDocumentALire(id).then(setDoc).catch((e) => setErreur(messageAccueil(e)));
  }, [id]);

  const surChargement = () => {
    const f = cadre.current;
    const d = f?.contentDocument;
    if (!f || !d) {
      setLu(true);
      return;
    }
    const verifier = () => {
      const el = d.scrollingElement ?? d.documentElement;
      if (el.scrollHeight - el.scrollTop - el.clientHeight < 40) setLu(true);
    };
    verifier();
    d.addEventListener("scroll", verifier, { passive: true });
  };

  const signer = async () => {
    if (!doc) return;
    setAttente(true);
    setErreur(null);
    try {
      const r = await signerDocument(doc.id, nom.trim(), doc.empreinte);
      navigate(r.restants > 0 ? "/accueil" : "/", { replace: true });
      if (r.restants === 0) window.location.reload();
    } catch (e) {
      setErreur(messageAccueil(e));
      setAttente(false);
    }
  };

  if (erreur && !doc) return <p className="p-6 text-sm text-red-500">{erreur}</p>;
  if (!doc)
    return (
      <div className="flex flex-col gap-3 p-6" role="status" aria-busy="true" aria-label="Chargement du document à signer">
        <Skeleton className="h-6 w-56 max-w-full" />
        <Skeleton className="h-4 w-72 max-w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );

  const srcDoc = `<!doctype html><html lang="fr"><head><meta charset="utf-8"><style>body{font-family:Georgia,serif;line-height:1.6;color:#0B2239;padding:24px 28px;max-width:760px;margin:0 auto}h1,h2,h3{font-family:Arial,sans-serif}</style></head><body>${doc.contenu_html}</body></html>`;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
      <Link to="/accueil" className="text-sm underline underline-offset-4">
        ← Retour
      </Link>
      <Card>
        <CardHeader>
          <CardTitle>
            {doc.titre} <span className="text-text-secondary text-xs font-normal">version {doc.version}</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <iframe
            ref={cadre}
            title={doc.titre}
            srcDoc={srcDoc}
            sandbox="allow-same-origin"
            onLoad={surChargement}
            className="h-[60vh] w-full rounded-md border border-current/15 bg-white"
          />

          {doc.deja_signe ? (
            <p className="text-sm">
              ✓ Signé par {doc.deja_signe.signed_name} le{" "}
              {new Date(doc.deja_signe.signed_at).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" })}.
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {!luJusquauBout && (
                <p className="text-text-secondary text-xs">Faites défiler le document jusqu'à la fin pour pouvoir le signer.</p>
              )}
              <label className="text-sm">
                Votre nom complet
                <input
                  className="mt-1 w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm"
                  value={nom}
                  onChange={(e) => setNom(e.target.value)}
                  autoComplete="name"
                  disabled={!luJusquauBout}
                />
              </label>
              <label className="flex items-start gap-2 text-xs leading-relaxed">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={accord}
                  onChange={(e) => setAccord(e.target.checked)}
                  disabled={!luJusquauBout}
                />
                <span>{doc.consentement}</span>
              </label>
              {erreur && <p className="text-xs text-red-500">{erreur}</p>}
              <button
                className="self-start rounded-md border border-current/30 px-5 py-2 text-sm font-medium hover:bg-current/10 disabled:opacity-40"
                disabled={!luJusquauBout || !accord || nom.trim().length < 2 || attente}
                onClick={() => void signer()}
              >
                {attente ? "Signature…" : "Signer le document"}
              </button>
              <p className="text-text-secondary text-[11px]">
                Empreinte du document : <code className="break-all">{doc.empreinte}</code>
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
