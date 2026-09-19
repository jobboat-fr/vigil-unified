/**
 * La marque VTLVS — un seul endroit, pour qu'il n'y en ait plus trois.
 *
 * Avant ce fichier, l'application montrait trois identités différentes selon l'écran :
 * l'en-tête affichait le chevron marine suivi du mot « VTLVS » ; l'écran de connexion et
 * les pages publiques affichaient `logo-lockup.png`, dont le mot dessiné est **ATLAS**,
 * avec `alt="VTLVS"` ; et l'onglet du navigateur portait encore l'œil VIGIL hérité du
 * projet d'origine. La première chose que voyait un nouveau client était donc un nom qui
 * n'est pas le nôtre.
 *
 * Le dessin est en SVG (`/vtlvs-mark.svg`, recopié ici pour hériter de `currentColor`) :
 * net à toute taille, marine sur fond clair, blanc sur fond sombre, sans second fichier.
 */

/** La police du mot « VTLVS » — la même que sur vtlvs.com, docs, status et l'Académie. */
export const MOT = "'Space Grotesk', 'Poppins', system-ui, sans-serif";

/** Le chevron seul. Prend la couleur du texte environnant. */
export function MarqueVtlvs({ hauteur = 28, className, titre }: { hauteur?: number; className?: string; titre?: string }) {
  return (
    <svg
      viewBox="0 0 88.64 91.2"
      height={hauteur}
      width={(hauteur * 88.64) / 91.2}
      className={className}
      role={titre ? "img" : undefined}
      aria-label={titre}
      aria-hidden={titre ? undefined : true}
      focusable="false"
    >
      <path fill="currentColor" d="M44.3 0 88.64 91.2 87.72 91.2 44.3 54.3 .88 91.2 0 91.2Z" />
      <path fill="currentColor" d="M44.3 63.5 87.78 91.2 86.24 91.2 44.3 71.5 1.36 91.2 .82 91.2Z" />
    </svg>
  );
}

/**
 * Le bloc-marque : chevron + mot. Composé ici plutôt que dessiné dans une image, pour que
 * le mot reste du texte — sélectionnable, lisible par un lecteur d'écran, net partout, et
 * impossible à confondre avec celui d'une autre marque.
 */
export function BlocMarqueVtlvs({
  hauteur = 28,
  vertical = false,
  className,
}: {
  hauteur?: number;
  vertical?: boolean;
  className?: string;
}) {
  return (
    <span
      className={className}
      style={{
        display: "inline-flex",
        flexDirection: vertical ? "column" : "row",
        alignItems: "center",
        gap: vertical ? hauteur * 0.32 : hauteur * 0.42,
      }}
    >
      <MarqueVtlvs hauteur={hauteur} />
      <span
        style={{
          fontFamily: MOT,
          fontWeight: 700,
          fontSize: hauteur * (vertical ? 0.62 : 0.78),
          letterSpacing: ".09em",
          lineHeight: 1,
        }}
      >
        VTLVS
      </span>
    </span>
  );
}
