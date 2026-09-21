import { useCallback, useEffect, useState } from "react";
import { vigil, type Breakout, type LiveKitJoin } from "@/lib/vigil";
import { expliquerCourt } from "@/lib/refus";

type Props = {
  roomId: string;
  role: "host" | "participant";
  /** Sous-salle affichée, ou null en plénière. */
  groupeActuel: string | null;
  /** Bascule la vidéo vers la sous-salle `gid` avec ce jeton. */
  onEntrer: (join: LiveKitJoin, gid: string, nom: string) => void;
  /** Revient en plénière (nouveau jeton de la salle principale). */
  onPleniere: () => void;
};

/**
 * Sous-salles d'une séance de formation.
 *
 * Animateur : crée N groupes (répartition automatique des inscrits), entre dans n'importe
 * lequel, ferme tout. Participant : voit son groupe quand il existe, y entre, revient en
 * plénière. L'état est relu toutes les 10 s — pas de temps réel à maintenir.
 */
export function SousSalles({ roomId, role, groupeActuel, onEntrer, onPleniere }: Props) {
  const [groupes, setGroupes] = useState<Breakout[]>([]);
  const [nombre, setNombre] = useState(3);
  const [erreur, setErreur] = useState<string | null>(null);
  const [attente, setAttente] = useState(false);

  const relire = useCallback(async () => {
    try {
      setGroupes((await vigil.rooms.breakouts(roomId)).breakouts);
      setErreur(null);
    } catch (e) {
      setErreur(expliquerCourt(e));
    }
  }, [roomId]);

  useEffect(() => {
    void relire();
    const id = window.setInterval(() => void relire(), 10_000);
    return () => window.clearInterval(id);
  }, [relire]);

  // Groupes fermés par l'animateur pendant qu'on y est : retour en plénière.
  useEffect(() => {
    if (groupeActuel && !groupes.some((g) => g.id === groupeActuel)) onPleniere();
  }, [groupes, groupeActuel, onPleniere]);

  const agir = async (f: () => Promise<void>) => {
    setAttente(true);
    setErreur(null);
    try {
      await f();
    } catch (e) {
      setErreur(expliquerCourt(e));
    } finally {
      setAttente(false);
    }
  };

  const entrer = (g: Breakout) =>
    agir(async () => {
      const join = await vigil.rooms.joinBreakout(roomId, g.id);
      onEntrer(join, g.id, g.name);
    });

  const bouton = "rounded border border-white/25 px-2 py-1 text-xs disabled:opacity-50 hover:bg-white/10";

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-white/80">
      {groupeActuel && (
        <button className={bouton} disabled={attente} onClick={onPleniere}>
          ← Retour en plénière
        </button>
      )}
      {role === "host" ? (
        groupes.length === 0 ? (
          <>
            <span>Sous-salles :</span>
            <input
              type="number"
              min={1}
              max={20}
              value={nombre}
              onChange={(e) => setNombre(Number(e.target.value) || 1)}
              className="w-12 rounded border border-white/25 bg-transparent px-1 py-0.5"
              aria-label="Nombre de groupes"
            />
            <button className={bouton} disabled={attente} onClick={() => void agir(async () => {
              setGroupes((await vigil.rooms.createBreakouts(roomId, nombre)).breakouts);
            })}>
              Créer les groupes
            </button>
          </>
        ) : (
          <>
            {groupes.map((g) => (
              <button
                key={g.id}
                className={bouton}
                disabled={attente || g.id === groupeActuel}
                title={(g.member_names ?? g.members).join(", ")}
                onClick={() => void entrer(g)}
              >
                {g.name} ({g.members.length})
              </button>
            ))}
            <button className={bouton} disabled={attente} onClick={() => void agir(async () => {
              await vigil.rooms.closeBreakouts(roomId);
              setGroupes([]);
              if (groupeActuel) onPleniere();
            })}>
              Fermer les sous-salles
            </button>
          </>
        )
      ) : (
        groupes[0] &&
        groupes[0].id !== groupeActuel && (
          <button className={bouton} disabled={attente} onClick={() => void entrer(groupes[0])}>
            Rejoindre mon groupe : {groupes[0].name}
          </button>
        )
      )}
      {erreur && <span className="text-amber-400">{erreur}</span>}
    </div>
  );
}
