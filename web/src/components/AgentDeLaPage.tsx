import { Link, useLocation } from "react-router-dom";
import { agentsPourPage, useAbonnementAgents } from "@/lib/agentique";

/**
 * L'encart qui dit, sur une page métier, quel agent la couvre.
 *
 * Monté une seule fois dans la mise en page : il se tait partout où aucun agent n'intervient.
 * Tant que l'abonnement n'est pas ouvert, il présente l'agent et renvoie vers la page
 * d'abonnement ; ensuite, il ouvrira son tableau de bord. Un bandeau discret, jamais un
 * bloc qui pousse la page vers le bas.
 */
export default function AgentDeLaPage() {
  const { pathname } = useLocation();
  const { abonne } = useAbonnementAgents();
  const agents = agentsPourPage(pathname);
  if (agents.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-current/10 px-4 py-2 text-xs">
      {agents.map((a) => (
        <span key={a.id} className="flex items-center gap-2">
          <img src={a.logo} alt="" style={{ height: 20, width: "auto", borderRadius: 3 }} />
          <span>
            <b style={{ color: a.accent }}>{a.nom}</b>
            <span className="text-text-secondary"> — {a.accroche.toLowerCase()}</span>
          </span>
          {abonne ? (
            <a
              href={a.tableauDeBord}
              target="_blank"
              rel="noopener noreferrer"
              className="underline"
            >
              ouvrir
            </a>
          ) : (
            <Link to="/abonnement" className="underline opacity-75">
              🔒 s&apos;abonner
            </Link>
          )}
        </span>
      ))}
    </div>
  );
}
