import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@nous-research/ui/ui/components/button";

/**
 * Une adresse qui n'existe pas.
 *
 * Avant, l'application redirigeait silencieusement vers /learn : la personne cliquait un
 * lien périmé, atterrissait sur son tableau de bord, et croyait avoir mal cliqué. Dire
 * « cette adresse n'existe pas » et montrer l'adresse en question coûte une seconde de
 * lecture et évite dix minutes de doute — surtout quand le lien vient d'un e-mail.
 */
export default function PageIntrouvable() {
  const { pathname } = useLocation();
  const naviguer = useNavigate();
  return (
    <div className="flex min-h-0 flex-1 items-center justify-center px-4 py-10">
      <div className="w-full max-w-lg rounded-2xl border border-current/15 p-6">
        <div className="text-xs uppercase tracking-[0.18em] text-text-secondary">Adresse inconnue</div>
        <h1 className="mt-3 text-lg font-semibold">Il n'y a rien à cette adresse</h1>
        <p className="mt-2 break-all font-mono text-xs text-text-secondary">{pathname}</p>
        <p className="mt-3 text-sm">
          Le lien est peut-être périmé, ou l'écran demandé n'est pas ouvert à votre rôle. Rien n'a
          été modifié.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => naviguer("/accueil")}>
            Retour à l'accueil
          </Button>
          <Button size="sm" outlined onClick={() => naviguer("/aide")}>
            Aide et support
          </Button>
        </div>
      </div>
    </div>
  );
}
