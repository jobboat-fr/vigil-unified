import { useCallback, useEffect, useRef, useState } from "react";
import { Skeleton } from "@/components/EmptyState";
import {
  getNoyauMeta,
  lienNoyau,
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
 *   * l'iframe charge une **URL**, et non un document injecté en `srcdoc`. C'est le point
 *     qui a changé le 2026-09-20 : un document `srcdoc` hérite de la politique de sécurité
 *     de l'application (`script-src 'self'`), et comme le bac à sable lui donne une origine
 *     opaque, `'self'` ne désignait plus rien — **aucun** script ne s'exécutait. Le
 *     document s'affichait, « Commencer la visite » ne faisait rien, et rien ne le
 *     signalait. Chargé par son URL, il porte sa propre politique (routes/noyau.py).
 *     Une iframe ne pouvant pas envoyer d'en-tête `Authorization`, l'accès passe par un
 *     laissez-passer signé de cinq minutes, lié à la personne et au document.
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

export default function NoyauPage() {
  const [url, setUrl] = useState<string | null>(null);
  const [meta, setMeta] = useState<NoyauMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const frame = useRef<HTMLIFrameElement>(null);

  const charger = useCallback(async () => {
    const [m, lien] = await Promise.all([getNoyauMeta().catch(() => null), lienNoyau()]);
    setMeta(m);
    // Le modèle enregistré est posé par le serveur au moment de servir le document :
    // la page n'a plus à le réinjecter dans une chaîne de 110 Ko.
    setUrl(lien.url);
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

  if (url === null) {
    // Le document occupe toute la hauteur : une ligne de texte puis une iframe plein
    // cadre, c'est un saut d'écran entier. On réserve la place.
    return (
      <div className="flex flex-col gap-3 p-4 sm:p-6" style={{ height: "calc(100dvh - 5.5rem)" }}
           role="status" aria-busy="true" aria-label="Chargement du document">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="w-full flex-1" />
      </div>
    );
  }

  // Le document se dimensionne en `100dvh` : dans une iframe, cela vaut la hauteur de
  // l'iframe, pas celle de la fenêtre. Sans hauteur explicite ici, le conteneur de route
  // se réduit au contenu et l'iframe faisait cent pixels de haut.
  return (
    <div className="flex flex-col" style={{ height: "calc(100dvh - 5.5rem)" }}>
      <iframe
        ref={frame}
        title="Le Noyau"
        src={url}
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
