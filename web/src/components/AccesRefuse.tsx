import type { ComponentType } from "react";
import { Refus } from "@/components/Refus";

/**
 * L'écran d'une page que le rôle n'ouvre pas.
 *
 * Avant, ces routes étaient branchées sur `RootRedirect` : la personne cliquait, l'adresse
 * changeait, et elle se retrouvait sur le tableau de bord sans un mot. Vu du siège, c'est
 * indiscernable d'un bouton cassé — et c'est exactement ce qui a été rapporté : « certains
 * boutons ne marchent pas du tout, la page visée ne charge même pas ».
 *
 * Le refus était pourtant délibéré. Ce qui manquait, ce n'est pas le contrôle d'accès,
 * c'est la phrase. On garde donc le refus, et on le dit : quelle page, et qui peut
 * l'ouvrir.
 *
 * On ne redirige plus : l'adresse demandée reste dans la barre. Quelqu'un qui a suivi un
 * lien reçu par message doit pouvoir le transmettre à qui a le droit, pas découvrir que
 * son navigateur affiche autre chose que ce qu'il a tapé.
 */
export function ecranAccesRefuse(libelle: string): ComponentType {
  function AccesRefuse() {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-4 py-10">
        <Refus erreur={{ status: 403 }} quoi={`« ${libelle} »`} />
      </div>
    );
  }
  AccesRefuse.displayName = `AccesRefuse(${libelle})`;
  return AccesRefuse;
}
