/**
 * L'avis de création d'une formation — la pièce qui dit **qui a décidé** de l'ouvrir.
 *
 * Demandé par Azer en même temps que les thèmes : « l'administration téléverse l'avis émis
 * par sa hiérarchie, as a tracability ». La colonne existait depuis la migration 0059 et le
 * dépôt l'acceptait déjà ; il manquait l'écran, et la lecture — `GET /vault` ne savait
 * filtrer que par session, donc une pièce rattachée à un programme entrait au coffre sans
 * jamais pouvoir en ressortir autrement qu'en parcourant tout.
 *
 * Ce n'est pas une pièce jointe décorative. Elle relève de la même logique de preuve que
 * l'émargement : produite pendant le travail, relue en audit. D'où deux partis pris.
 *
 * **On ne remplace pas, on ajoute.** Un avis rectificatif ne fait pas disparaître celui
 * qu'il corrige — c'est la succession des décisions qui se relit, pas la dernière. Le plus
 * récent se lit en premier, les autres restent.
 *
 * **On n'écrit rien tant que le fichier n'est pas parti.** Pas de ligne optimiste : un
 * coffre qui affirme détenir une pièce qu'il n'a pas est pire qu'un coffre vide.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { getVault, getVaultUrl, uploadVault, type VaultObject } from "@/lib/learn";
import { Refus } from "@/components/Refus";

/** Le `kind` sous lequel la pièce vit au coffre. Une constante : il sert au dépôt **et**
 *  au filtre de lecture, et les voir diverger ferait disparaître la liste sans erreur. */
const GENRE = "avis_creation";

const poids = (o: number | null) =>
  o == null ? "" : o < 1024 ? `${o} o` : o < 1024 * 1024 ? `${Math.round(o / 1024)} ko` : `${(o / (1024 * 1024)).toFixed(1)} Mo`;

const jour = (iso: string) =>
  new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });

export function AvisCreation({ programId, peutDeposer }: { programId: string; peutDeposer: boolean }) {
  const [pieces, setPieces] = useState<VaultObject[] | null>(null);
  const [erreur, setErreur] = useState<unknown>(null);
  const [envoi, setEnvoi] = useState(false);
  const champ = useRef<HTMLInputElement>(null);

  const charger = useCallback(async () => {
    try {
      const r = await getVault({ kind: GENRE, program_id: programId });
      setPieces(r.items);
      setErreur(null);
    } catch (e) {
      setPieces([]);
      setErreur(e);
    }
  }, [programId]);

  useEffect(() => {
    void charger();
  }, [charger]);

  const deposer = async (f: File) => {
    setEnvoi(true);
    setErreur(null);
    try {
      await uploadVault(f, { kind: GENRE, program_id: programId, visibility: "tenant" });
      await charger();
      if (champ.current) champ.current.value = "";
    } catch (e) {
      setErreur(e);
    } finally {
      setEnvoi(false);
    }
  };

  const ouvrir = async (o: VaultObject) => {
    try {
      const { url } = await getVaultUrl(o.id);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setErreur(e);
    }
  };

  return (
    <div className="space-y-2">
      {pieces === null ? (
        <div className="h-8 animate-pulse rounded bg-current/5" aria-label="Chargement" />
      ) : pieces.length === 0 ? (
        <p className="text-xs opacity-70">
          Aucun avis déposé. C&apos;est la pièce qui atteste de la décision d&apos;ouvrir cette formation.
        </p>
      ) : (
        <ul className="space-y-1">
          {pieces.map((o) => (
            <li key={o.id} className="flex items-center justify-between gap-2 text-xs">
              <button
                type="button"
                onClick={() => void ouvrir(o)}
                className="min-w-0 flex-1 truncate text-left underline-offset-2 hover:underline"
                title={o.filename ?? "Avis de création"}
              >
                {o.filename ?? "Avis de création"}
              </button>
              <span className="shrink-0 opacity-60">
                {jour(o.created_at)}
                {o.size_bytes ? ` · ${poids(o.size_bytes)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      {peutDeposer && (
        <label className="flex flex-col gap-1">
          <span className="text-[11px] opacity-70">
            {pieces && pieces.length > 0 ? "Déposer un avis rectificatif" : "Déposer l'avis"}
          </span>
          <input
            ref={champ}
            type="file"
            disabled={envoi}
            accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.odt"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void deposer(f);
            }}
            aria-label="Avis de création"
            className="text-xs file:mr-2 file:rounded file:border file:border-current/20 file:bg-transparent file:px-2 file:py-1 file:text-xs"
          />
        </label>
      )}

      {erreur != null && <Refus erreur={erreur} quoi="l'avis de création" compact />}
    </div>
  );
}
