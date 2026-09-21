import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { BoutonPublic, CadreOrganisme } from "@/components/CadreOrganisme";
import { confirmerInscription, lireConfirmation, messageAccueil } from "@/lib/accueil";

/**
 * Le second pas du double opt-in : la personne confirme depuis sa propre boîte.
 *
 * Ce que cette page fait de particulier — et qui est la raison d'être du double opt-in —
 * c'est de **demander un geste**. Le lien seul ne vaut pas consentement : les passerelles
 * antivirus et les aperçus de messagerie ouvrent les liens d'un e-mail avant que le
 * destinataire ne le lise. Si le clic suffisait, c'est l'antivirus de l'entreprise qui
 * consentirait à la place de la personne, et la preuve qu'on garde ne prouverait rien.
 *
 * La page réaffiche donc **la phrase exacte** à laquelle elle s'apprête à consentir. C'est
 * la même chaîne que celle enregistrée dans `consent_preuve` : ce qui est montré et ce qui
 * est conservé ne peuvent pas diverger.
 */
export default function ConfirmationPage() {
  const [params] = useSearchParams();
  const j = params.get("j") ?? "";
  const [info, setInfo] = useState<
    { organisme: string; email: string; categorie: string; phrase: string } | null
  >(null);
  const [fait, setFait] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    lireConfirmation(j)
      .then(setInfo)
      .catch((e) => setErreur(messageAccueil(e)));
  }, [j]);

  return (
    <CadreOrganisme organisme={info?.organisme}>
      {erreur ? (
        <>
          <h1 className="text-xl font-bold">Ce lien n&apos;est plus valable</h1>
          <p className="mt-3 text-sm">{erreur}</p>
          <p className="mt-2 text-sm">
            Un lien de confirmation expire au bout de quelques jours. Vous pouvez en
            redemander un depuis le formulaire d&apos;inscription.
          </p>
        </>
      ) : !info ? (
        <p className="text-sm">Chargement…</p>
      ) : fait ? (
        <>
          <h1 className="text-xl font-bold">C&apos;est confirmé</h1>
          <p className="mt-3 text-sm">
            {info.email} est inscrite à {info.phrase}.
          </p>
          <p className="mt-2 text-sm">
            Chaque message porte un lien de désinscription : un clic suffit pour revenir sur
            ce choix, sans avoir à écrire à qui que ce soit.
          </p>
        </>
      ) : (
        <>
          <h1 className="text-xl font-bold">Confirmez votre inscription</h1>
          <p className="mt-3 text-sm">
            Vous vous apprêtez à inscrire <b>{info.email}</b> à {info.phrase}.
          </p>
          <p className="mt-2 text-sm">
            Tant que vous n&apos;avez pas confirmé, rien n&apos;est enregistré et vous ne
            recevez rien.
          </p>
          <div className="mt-5">
            <BoutonPublic
              type="button"
              disabled={busy}
              onClick={() => {
                setBusy(true);
                void confirmerInscription(j)
                  .then(() => setFait(true))
                  .catch((e) => setErreur(messageAccueil(e)))
                  .finally(() => setBusy(false));
              }}
            >
              {busy ? "Enregistrement…" : "Confirmer mon inscription"}
            </BoutonPublic>
          </div>
        </>
      )}
    </CadreOrganisme>
  );
}
