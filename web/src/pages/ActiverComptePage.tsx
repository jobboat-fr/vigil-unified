import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { BoutonPublic, CadreOrganisme, champPublic } from "@/components/CadreOrganisme";
import { activerCompte, demanderNouveauLien, lireActivation, messageAccueil, type Activation } from "@/lib/accueil";
import { supabase } from "@/lib/supabase";

const ROLE: Record<string, string> = {
  apprenant: "apprenant",
  formateur: "formateur",
  entreprise: "entreprise cliente",
  auditeur: "auditeur",
  admin: "administrateur",
};

const REGLES = [
  { test: (m: string) => m.length >= 10, texte: "10 caractères au moins" },
  { test: (m: string) => /[a-z]/.test(m), texte: "une minuscule" },
  { test: (m: string) => /[A-Z]/.test(m), texte: "une majuscule" },
  { test: (m: string) => /\d/.test(m), texte: "un chiffre" },
];

/**
 * Activation d'un compte invité : l'adresse est celle de l'invitation (non modifiable), la
 * personne choisit son mot de passe et accepte CGU et politique de confidentialité. Puis
 * connexion immédiate et arrivée sur l'accueil — où l'attendent ses documents à signer.
 */
export default function ActiverComptePage() {
  const [params] = useSearchParams();
  const jeton = params.get("t") ?? "";
  const [info, setInfo] = useState<Activation | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [mdp, setMdp] = useState("");
  const [mdp2, setMdp2] = useState("");
  const [cgu, setCgu] = useState(false);
  const [confidentialite, setConfidentialite] = useState(false);
  const [attente, setAttente] = useState(false);
  const [renvoye, setRenvoye] = useState(false);

  useEffect(() => {
    if (!jeton) {
      setErreur("Ce lien d'activation n'est pas complet.");
      return;
    }
    lireActivation(jeton).then(setInfo).catch((e) => setErreur(messageAccueil(e)));
  }, [jeton]);

  const regles = useMemo(() => REGLES.map((r) => ({ ...r, ok: r.test(mdp) })), [mdp]);
  const valide = regles.every((r) => r.ok) && mdp === mdp2 && cgu && confidentialite;

  const activer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!info || !valide) return;
    setAttente(true);
    setErreur(null);
    try {
      await activerCompte(jeton, mdp);
      if (supabase) {
        const { error } = await supabase.auth.signInWithPassword({ email: info.email, password: mdp });
        if (error) throw error;
      }
      window.location.assign("/accueil");
    } catch (err) {
      setErreur(messageAccueil(err));
      setAttente(false);
    }
  };

  const cadre = { organisme: info?.organisme, logoUrl: info?.logo_url, couleur: info?.couleur };

  if (!info) {
    return (
      <CadreOrganisme {...cadre}>
        <p className="text-sm">{erreur ?? "Chargement…"}</p>
      </CadreOrganisme>
    );
  }

  if (info.etat !== "valide") {
    return (
      <CadreOrganisme {...cadre}>
        <h1 className="text-xl font-bold">
          {info.etat === "utilise" ? "Compte déjà activé" : "Ce lien n'est plus valable"}
        </h1>
        <p className="mt-3 text-sm leading-relaxed">
          {info.etat === "utilise"
            ? "Votre compte est actif. Connectez-vous avec votre adresse e-mail et votre mot de passe."
            : info.etat === "remplace"
              ? "Un lien plus récent vous a été envoyé. Utilisez le dernier e-mail reçu, ou demandez un nouveau lien."
              : "Le lien a expiré. Recevez un nouveau lien à votre adresse e-mail."}
        </p>
        <div className="mt-5">
          {info.etat === "utilise" ? (
            <BoutonPublic couleur={info.couleur} type="button" onClick={() => window.location.assign("/")}>
              Se connecter
            </BoutonPublic>
          ) : renvoye ? (
            <p className="text-sm">Si votre compte est en attente d'activation, un nouveau lien vient de partir à {info.email}.</p>
          ) : (
            <BoutonPublic
              couleur={info.couleur}
              type="button"
              onClick={() => void demanderNouveauLien(jeton).then(() => setRenvoye(true))}
            >
              Recevoir un nouveau lien
            </BoutonPublic>
          )}
        </div>
      </CadreOrganisme>
    );
  }

  return (
    <CadreOrganisme {...cadre}>
      <h1 className="text-xl font-bold">Bienvenue{info.nom ? `, ${info.nom.split(" ")[0]}` : ""}</h1>
      <p className="mt-2 text-sm leading-relaxed">
        {info.organisme} vous a ajouté en tant que {ROLE[info.role] ?? info.role}. Choisissez votre mot de passe pour
        activer votre compte.
      </p>
      <form className="mt-5 flex flex-col gap-3" onSubmit={activer}>
        <label className="text-xs font-medium">
          Adresse e-mail (votre identifiant)
          <input className={`${champPublic} mt-1 bg-slate-50`} value={info.email} readOnly />
        </label>
        <label className="text-xs font-medium">
          Mot de passe
          <input
            className={`${champPublic} mt-1`}
            type="password"
            autoComplete="new-password"
            value={mdp}
            onChange={(e) => setMdp(e.target.value)}
            required
          />
        </label>
        <ul className="grid grid-cols-2 gap-x-3 text-[11px]">
          {regles.map((r) => (
            <li key={r.texte} style={{ color: r.ok ? "var(--color-success)" : "var(--color-muted-foreground)" }}>
              {r.ok ? "✓" : "○"} {r.texte}
            </li>
          ))}
        </ul>
        <label className="text-xs font-medium">
          Confirmer le mot de passe
          <input
            className={`${champPublic} mt-1`}
            type="password"
            autoComplete="new-password"
            value={mdp2}
            onChange={(e) => setMdp2(e.target.value)}
            required
          />
        </label>
        {mdp2 && mdp !== mdp2 && <p className="text-[11px] text-red-600">Les deux mots de passe diffèrent.</p>}
        <label className="flex items-start gap-2 text-xs">
          <input type="checkbox" checked={cgu} onChange={(e) => setCgu(e.target.checked)} className="mt-0.5" />
          <span>
            J'accepte les{" "}
            <a href="https://vtlvs.com/cgu" target="_blank" rel="noreferrer" className="underline">
              conditions d'utilisation
            </a>
            .
          </span>
        </label>
        <label className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            checked={confidentialite}
            onChange={(e) => setConfidentialite(e.target.checked)}
            className="mt-0.5"
          />
          <span>
            J'ai lu la{" "}
            <a href="https://vtlvs.com/confidentialite" target="_blank" rel="noreferrer" className="underline">
              politique de confidentialité
            </a>
            .
          </span>
        </label>
        {erreur && <p className="text-xs text-red-600">{erreur}</p>}
        <BoutonPublic couleur={info.couleur} disabled={!valide || attente}>
          {attente ? "Activation…" : "Activer mon compte"}
        </BoutonPublic>
        <p className="text-center text-[11px]" style={{ color: "var(--color-muted-foreground)" }}>
          Lien valable jusqu'au{" "}
          {new Date(info.expire_le).toLocaleString("fr-FR", { dateStyle: "long", timeStyle: "short" })}.
        </p>
      </form>
    </CadreOrganisme>
  );
}
