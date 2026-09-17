import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { BoutonPublic, CadreOrganisme } from "@/components/CadreOrganisme";
import { confirmerDesinscription, lireDesinscription, messageAccueil } from "@/lib/accueil";

/** Désinscription d'une famille d'e-mails, par le lien signé présent dans l'e-mail. */
export default function DesinscriptionPage() {
  const [params] = useSearchParams();
  const j = params.get("j") ?? "";
  const [info, setInfo] = useState<{ organisme: string; email: string; libelle: string } | null>(null);
  const [fait, setFait] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    lireDesinscription(j).then(setInfo).catch((e) => setErreur(messageAccueil(e)));
  }, [j]);

  return (
    <CadreOrganisme organisme={info?.organisme}>
      {erreur ? (
        <p className="text-sm">{erreur}</p>
      ) : !info ? (
        <p className="text-sm">Chargement…</p>
      ) : fait ? (
        <>
          <h1 className="text-xl font-bold">C'est noté</h1>
          <p className="mt-3 text-sm">
            {info.email} ne recevra plus les e-mails « {info.libelle} » de {info.organisme}. Les messages indispensables
            (compte, sécurité, formation) continuent d'arriver.
          </p>
        </>
      ) : (
        <>
          <h1 className="text-xl font-bold">Se désinscrire</h1>
          <p className="mt-3 text-sm">
            Ne plus recevoir les e-mails « {info.libelle} » de {info.organisme} à l'adresse {info.email} ?
          </p>
          <div className="mt-5">
            <BoutonPublic
              type="button"
              onClick={() =>
                void confirmerDesinscription(j)
                  .then(() => setFait(true))
                  .catch((e) => setErreur(messageAccueil(e)))
              }
            >
              Confirmer la désinscription
            </BoutonPublic>
          </div>
        </>
      )}
    </CadreOrganisme>
  );
}
