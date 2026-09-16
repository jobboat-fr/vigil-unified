import { useEffect, useState } from "react";
import { vigil, type AttendanceCheck } from "@/lib/vigil";

const LIBELLE: Record<string, string> = {
  present_non_signe: "présent en visio, n'a pas émargé",
  signe_non_present: "a émargé, absent de la visio",
  presence_courte: "a émargé, présence en visio courte",
};

/**
 * Écarts entre la présence en visio et l'émargement, après une séance de formation.
 * Un signalement pour le formateur : rien n'est signé ni corrigé ici — l'émargement se
 * règle dans LEARN.
 */
export function EcartsEmargement({ roomId }: { roomId: string }) {
  const [data, setData] = useState<AttendanceCheck | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    vigil.rooms
      .attendanceCheck(roomId)
      .then((d) => alive && setData(d))
      .catch((e: Error) => alive && setErreur(e.message));
    return () => {
      alive = false;
    };
  }, [roomId]);

  if (erreur) return <p className="text-xs text-amber-500">Rapprochement avec l'émargement indisponible : {erreur}</p>;
  if (!data) return null;
  if (data.learners.length === 0) return <p className="text-text-secondary text-xs">Aucun apprenant inscrit à rapprocher.</p>;
  if (data.ecarts.length === 0)
    return <p className="text-xs">✓ Présence en visio et émargement concordent pour les {data.learners.length} apprenants.</p>;
  return (
    <div className="text-xs">
      <div className="text-text-secondary">Écarts avec l'émargement (à vérifier dans LEARN) :</div>
      <ul className="list-disc pl-4">
        {data.ecarts.map((r) => (
          <li key={r.apprenant_id}>
            {r.nom} — {LIBELLE[r.ecart ?? ""] ?? r.ecart} ({Math.round(r.presence_ratio * 100)} % du créneau)
          </li>
        ))}
      </ul>
    </div>
  );
}
