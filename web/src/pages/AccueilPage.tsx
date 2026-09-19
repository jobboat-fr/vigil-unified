import { useCallback, useEffect, useState } from "react";
import { SqueletteEcran } from "@/components/EmptyState";
import { EcranErreur } from "@/components/ErreurEcran";
import { Link } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { declarerFait, getAccueil, messageAccueil, type EtatAccueil } from "@/lib/accueil";

const dateCourte = (s: string) =>
  new Date(s).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });

/**
 * « À faire » : ce que la personne doit faire, dans l'ordre. D'abord les documents à signer —
 * tant qu'il en reste, le reste de l'espace est fermé —, puis les actions requises avec leur
 * échéance. Une action système (signer, émarger) se ferme d'elle-même une fois faite ; seules
 * les actions « autre » se déclarent ici.
 */
export default function AccueilPage() {
  const [etat, setEtat] = useState<EtatAccueil | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const charger = useCallback(() => {
    getAccueil().then(setEtat).catch((e) => setErreur(messageAccueil(e)));
  }, []);
  useEffect(() => charger(), [charger]);

  // L'accueil est le premier écran après la connexion : s'il échoue, une ligne rouge ne
  // suffit pas — il faut la raison, la référence, et un bouton pour réessayer.
  if (erreur)
    return <EcranErreur titre="Votre accueil n'a pas pu se charger" cause={erreur} onReessayer={() => { setErreur(""); charger(); }} />;
  if (!etat) return <SqueletteEcran lignes={4} />;

  const prenom = etat.profil?.full_name?.split(" ")[0] ?? "";
  const autres = etat.actions.filter((a) => a.kind !== "signer_document");

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Bonjour{prenom ? `, ${prenom}` : ""}</h1>
        <p className="text-text-secondary mt-1 text-sm">
          {etat.statut === "a_signer"
            ? `Pour finaliser votre inscription auprès de ${etat.organisme?.name ?? "votre organisme"}, signez les documents ci-dessous. Votre espace s'ouvrira ensuite en entier.`
            : etat.actions.length
              ? "Voici ce qui vous attend."
              : "Vous êtes à jour : rien ne vous attend pour le moment."}
        </p>
      </div>

      {etat.documents_a_signer.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Documents à signer ({etat.documents_a_signer.length})</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-current/10">
              {etat.documents_a_signer.map((d) => (
                <li key={d.template_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                  <span className="text-sm font-medium">{d.title}</span>
                  <Link
                    to={`/accueil/documents/${d.template_id}`}
                    className="rounded-md border border-current/30 px-3 py-1.5 text-sm font-medium hover:bg-current/10"
                  >
                    Lire et signer
                  </Link>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {autres.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>À faire ({autres.length})</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-current/10">
              {autres.map((a) => {
                const retard = new Date(a.due_at) < new Date();
                return (
                  <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{a.title}</div>
                      {a.detail && <div className="text-text-secondary text-xs">{a.detail}</div>}
                      <div className={`text-xs ${retard ? "text-amber-500" : "text-text-secondary"}`}>
                        {retard ? "En retard — échéance" : "Échéance"} : {dateCourte(a.due_at)}
                      </div>
                    </div>
                    <div className="flex gap-2">
                      {a.link_path && a.link_path !== "/accueil" && (
                        <Link to={a.link_path} className="rounded-md border border-current/30 px-3 py-1.5 text-sm hover:bg-current/10">
                          Y aller
                        </Link>
                      )}
                      {a.kind === "autre" && (
                        <button
                          className="rounded-md border border-current/30 px-3 py-1.5 text-sm hover:bg-current/10"
                          onClick={() => void declarerFait(a.id).then(charger, (e) => setErreur(messageAccueil(e)))}
                        >
                          C'est fait
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
