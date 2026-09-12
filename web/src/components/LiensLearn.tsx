import { Link, useLocation } from "react-router-dom";

/**
 * Le maillage entre les écrans de formation.
 *
 * Il existe parce qu'il n'y en avait aucun : les sept pages LEARN ne comportaient pas un
 * seul lien interne. On y circulait uniquement par la barre latérale — depuis son
 * calendrier on ne pouvait pas ouvrir sa session, depuis ses acquis on ne pouvait pas
 * atteindre son attestation. Chaque écran était une impasse, et le parcours qu'il décrit
 * ne se parcourait pas.
 *
 * Une seule table de destinations, partagée. Quatre variantes écrites à la main auraient
 * divergé dès la première page renommée.
 *
 * La page courante est retirée de la liste — un lien vers soi-même est du bruit, et il
 * fait douter de là où l'on se trouve.
 */

const DESTINATIONS = [
  { to: "/learn", libelle: "Tableau de bord" },
  { to: "/learn/calendar", libelle: "Mon calendrier" },
  { to: "/learn/emargement", libelle: "Émargement" },
  { to: "/learn/parcours", libelle: "Mon parcours" },
  { to: "/learn/formations", libelle: "Programmes" },
  { to: "/learn/acquis", libelle: "Mes acquis" },
  { to: "/learn/coffre", libelle: "Mes documents" },
] as const;

export function LiensLearn({ sauf }: { sauf?: string[] }) {
  const { pathname } = useLocation();
  const courant = pathname.replace(/\/$/, "") || "/";
  const exclus = new Set([courant, ...(sauf ?? [])]);
  const liens = DESTINATIONS.filter((d) => !exclus.has(d.to));

  return (
    <nav aria-label="Autres écrans de ma formation" className="flex flex-wrap gap-x-4 gap-y-2">
      {liens.map((d) => (
        <Link
          key={d.to}
          to={d.to}
          className="text-sm underline-offset-4 opacity-75 hover:underline hover:opacity-100"
        >
          {d.libelle}
        </Link>
      ))}
    </nav>
  );
}
