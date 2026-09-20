import { BlocMarqueVtlvs } from "@/components/MarqueVtlvs";
import { Button } from "@nous-research/ui/ui/components/button";
import { supabase } from "@/lib/supabase";

/**
 * Le compte existe, mais il n'est rattaché à rien.
 *
 * `learn_role` vit dans `app_metadata` du compte d'authentification — jamais dans
 * `user_metadata`, que son propriétaire peut écrire. Quand il manque, LEARN refuse chaque
 * appel en `no_learn_role` (routes/roles.py), et c'est la bonne réponse côté serveur.
 *
 * Côté écran, ça ne l'était pas : la connexion réussissait, puis l'application s'ouvrait
 * sur une coquille où chaque requête échouait en silence — menu presque vide, écrans
 * blancs, aucune explication. Trois comptes de la base sont dans cet état, dont un qui
 * s'est déjà connecté (06/09/2026).
 *
 * Une personne dans ce cas ne peut rien y faire elle-même : c'est son organisme qui la
 * rattache. L'écran le dit, et propose la seule action qui lui reste.
 */
export default function CompteSansRole({ email }: { email?: string | null }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-4 py-10">
      <div className="w-full max-w-md rounded-2xl border border-current/15 p-6 text-center">
        <div className="mb-5 flex justify-center">
          <BlocMarqueVtlvs hauteur={26} />
        </div>
        <h1 className="text-lg font-semibold">Votre compte n&apos;est rattaché à aucun organisme</h1>
        <p className="mt-3 text-sm text-text-secondary">
          La connexion a réussi{email ? ` (${email})` : ""}, mais aucun organisme de formation ne vous
          a encore ouvert d&apos;accès. Tant que c&apos;est le cas, il n&apos;y a rien à afficher ici —
          ce n&apos;est pas une panne.
        </p>
        <p className="mt-3 text-sm text-text-secondary">
          Le rattachement se fait par votre organisme, pas depuis cet écran. Si vous attendez une
          invitation, elle arrive par e-mail ; si vous pensez qu&apos;il y a une erreur, adressez-vous
          à la personne qui vous a inscrit.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button size="sm" outlined onClick={() => void supabase?.auth.signOut().then(() => window.location.assign("/"))}>
            Se déconnecter
          </Button>
          <Button size="sm" ghost onClick={() => window.location.assign("https://vtlvs.com/aide")}>
            Aide et contact
          </Button>
        </div>
      </div>
    </div>
  );
}
