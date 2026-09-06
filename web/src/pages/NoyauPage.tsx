import { useCallback, useEffect, useRef, useState } from "react";
import {
  getNoyauHtml,
  getNoyauMeta,
  putNoyauModel,
  LearnError,
  type NoyauMeta,
} from "@/lib/learn";

/**
 * Le Noyau — la description de l'installation, servie depuis la base.
 *
 * La page n'écrit pas la doctrine : elle la va chercher. Le document vit dans
 * `learn_noyau_docs` (migrations 0024 et 0025) et se corrige sans redéployer
 * l'application, ce qui est la seule façon qu'une description d'architecture reste vraie
 * plus de quelques semaines. L'assistant lit la même ligne, ce qui lui évite de deviner.
 *
 * Le document est posé en `srcdoc` dans une iframe en bac à sable. Trois raisons, dans cet
 * ordre :
 *
 *   * c'est un document autonome — styles, scène 3D, éditeur — et l'insérer dans le DOM de
 *     l'application ferait entrer en collision deux feuilles de style qui s'ignorent ;
 *   * `sandbox` sans `allow-same-origin` le prive de la session : il ne peut ni lire le
 *     jeton, ni appeler l'API en votre nom. C'est le point important — c'est du contenu
 *     stocké, pas du code de l'application ;
 *   * `srcdoc` plutôt qu'un `src` : une iframe ne porte pas d'en-tête `Authorization`, si
 *     bien qu'un `src` obligerait à faire voyager le jeton dans l'URL.
 *
 * Ce bac à sable a un corollaire : le document ne peut rien enregistrer lui-même. Son
 * éditeur envoie donc le modèle ici, et c'est cette page qui écrit — en base, pour tout le
 * monde, plutôt que dans le `localStorage` d'un seul navigateur. La base refuse si
 * l'appelant n'est pas super_admin, et le refus repart vers le document tel quel.
 *
 * L'accès est décidé par la base, pas ici. Un profil qui n'y a pas droit reçoit 404, et
 * cette page l'affiche tel quel : « ce document n'existe pas pour vous » est la bonne
 * réponse à donner à quelqu'un qui n'a pas à savoir qu'il existe.
 */

/** Le marqueur que le document réserve pour le modèle enregistré en base. */
const MARQUEUR = "/*MODEL_OVERRIDE*/null";

function injecter(html: string, model: unknown): string {
  if (!model) return html;
  // `JSON.stringify` ne protège pas contre `</script>` dans une chaîne : le parseur HTML
  // fermerait le bloc avant que le JS ne soit lu. On échappe la barre oblique, ce qui est
  // sans effet en JSON et neutralise la fermeture prématurée.
  const json = JSON.stringify(model).replace(/<\//g, "<\\/");
  return html.replace(MARQUEUR, json);
}

export default function NoyauPage() {
  const [html, setHtml] = useState<string | null>(null);
  const [meta, setMeta] = useState<NoyauMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const frame = useRef<HTMLIFrameElement>(null);

  const charger = useCallback(async () => {
    const [m, h] = await Promise.all([getNoyauMeta().catch(() => null), getNoyauHtml()]);
    setMeta(m);
    setHtml(injecter(h, m?.model ?? null));
  }, []);

  useEffect(() => {
    let vivant = true;
    void (async () => {
      try {
        await charger();
      } catch (e) {
        if (!vivant) return;
        setError(
          e instanceof LearnError ? e.message : "Le document n'a pas pu être chargé.",
        );
      }
    })();
    return () => { vivant = false; };
  }, [charger]);

  // L'éditeur du document parle par messages, faute de pouvoir écrire lui-même.
  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      // L'iframe est en origine opaque : son `ev.origin` vaut "null". On ne peut donc pas
      // filtrer sur l'origine — on filtre sur la fenêtre émettrice, qui est la seule chose
      // qu'un tiers ne peut pas usurper.
      if (!frame.current || ev.source !== frame.current.contentWindow) return;
      const d = ev.data as { type?: string; model?: Record<string, unknown> | null };
      if (!d || d.type !== "vtlvs:noyau:model") return;

      const repondre = (ok: boolean, err?: string) =>
        frame.current?.contentWindow?.postMessage(
          { type: "vtlvs:noyau:saved", ok, error: err }, "*",
        );

      void (async () => {
        try {
          // `null` demande le retour à la version du fichier : on écrit un modèle vide,
          // que le document interprète comme « pas d'injection ».
          await putNoyauModel(d.model ?? ({} as Record<string, unknown>));
          repondre(true);
          await charger();
        } catch (e) {
          repondre(false, e instanceof LearnError ? e.message : "écriture refusée");
        }
      })();
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [charger]);

  if (error) {
    return (
      <div className="p-6">
        <div className="max-w-lg rounded-xl border border-current/15 p-5">
          <h1 className="text-lg font-semibold">Le Noyau</h1>
          <p className="mt-2 text-sm opacity-70">{error}</p>
          <p className="mt-3 text-xs leading-relaxed opacity-55">
            Ce document est réservé à l&apos;éditeur de la plateforme, aux formateurs et à
            l&apos;assistant. Le refus vient de la base de données, pas de cet écran.
          </p>
        </div>
      </div>
    );
  }

  if (html === null) {
    return <p className="p-6 text-sm opacity-60">Chargement du document…</p>;
  }

  // Le document se dimensionne en `100dvh` : dans une iframe, cela vaut la hauteur de
  // l'iframe, pas celle de la fenêtre. Sans hauteur explicite ici, le conteneur de route
  // se réduit au contenu et l'iframe faisait cent pixels de haut.
  return (
    <div className="flex flex-col" style={{ height: "calc(100dvh - 5.5rem)" }}>
      <iframe
        ref={frame}
        title="Le Noyau"
        srcDoc={html}
        // Ni `allow-same-origin` ni `allow-forms` : le document a besoin d'exécuter son
        // propre script — la scène et l'éditeur — et de rien d'autre.
        sandbox="allow-scripts"
        className="w-full flex-1 border-0"
        style={{ background: "var(--color-card)" }}
      />
      {meta && (
        <p className="shrink-0 px-4 py-1.5 text-[11px] opacity-45">
          Version {meta.version} · {Math.round(meta.bytes / 1024)} Ko · mis à jour le{" "}
          {new Date(meta.updated_at).toLocaleDateString("fr-FR")}
          {meta.model ? " · modèle édité en base" : " · modèle du fichier"} · servi depuis
          la base, pas depuis le bundle
        </p>
      )}
    </div>
  );
}
