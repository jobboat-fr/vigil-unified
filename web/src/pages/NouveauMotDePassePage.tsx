import { useEffect, useState } from "react";
import { BoutonPublic, CadreOrganisme, champPublic } from "@/components/CadreOrganisme";
import { supabase } from "@/lib/supabase";

/**
 * Arrivée depuis l'e-mail « Réinitialisation de votre mot de passe » (famille sécurité).
 * Le lien de récupération Supabase ouvre une session temporaire ; la personne choisit ici son
 * nouveau mot de passe, puis rejoint son espace.
 */
export default function NouveauMotDePassePage() {
  const [pret, setPret] = useState(false);
  const [mdp, setMdp] = useState("");
  const [mdp2, setMdp2] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [attente, setAttente] = useState(false);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => setPret(Boolean(data.session)));
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setPret(Boolean(s)));
    return () => data.subscription.unsubscribe();
  }, []);

  const solide = mdp.length >= 10 && /[a-z]/.test(mdp) && /[A-Z]/.test(mdp) && /\d/.test(mdp);

  const enregistrer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!supabase || !solide || mdp !== mdp2) return;
    setAttente(true);
    setErreur(null);
    const { error } = await supabase.auth.updateUser({ password: mdp });
    if (error) {
      setErreur("Le mot de passe n'a pas pu être changé. Le lien a peut-être expiré : refaites la demande.");
      setAttente(false);
      return;
    }
    window.location.assign("/");
  };

  return (
    <CadreOrganisme>
      <h1 className="text-xl font-bold">Nouveau mot de passe</h1>
      {!pret ? (
        <p className="mt-3 text-sm">
          Ouverture du lien… S'il a expiré, refaites une demande depuis la page de connexion.
        </p>
      ) : (
        <form className="mt-5 flex flex-col gap-3" onSubmit={enregistrer}>
          <input
            className={champPublic}
            type="password"
            autoComplete="new-password"
            placeholder="Nouveau mot de passe"
            value={mdp}
            onChange={(e) => setMdp(e.target.value)}
          />
          <p className="text-[11px]" style={{ color: solide ? "var(--color-success)" : "var(--color-muted-foreground)" }}>
            10 caractères au moins, dont une minuscule, une majuscule et un chiffre.
          </p>
          <input
            className={champPublic}
            type="password"
            autoComplete="new-password"
            placeholder="Confirmer"
            value={mdp2}
            onChange={(e) => setMdp2(e.target.value)}
          />
          {erreur && <p className="text-xs text-red-600">{erreur}</p>}
          <BoutonPublic disabled={!solide || mdp !== mdp2 || attente}>
            {attente ? "Enregistrement…" : "Enregistrer"}
          </BoutonPublic>
        </form>
      )}
    </CadreOrganisme>
  );
}
