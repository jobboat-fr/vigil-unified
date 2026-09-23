import { useCallback, useEffect, useState } from "react";
import { Button } from "@nous-research/ui/ui/components/button";
import { vigil, type ArtifactShare } from "@/lib/vigil";
import { dateLongue, dateRelative } from "@/lib/studio";
import { expliquerCourt } from "@/lib/refus";

const champ = "rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50";

/**
 * Qui a accès à ce document. Deux façons de partager : à une personne de l'organisme (lecture ou
 * modification), ou par un lien public en lecture seule, qui expire. Le lien n'est montré qu'une
 * fois — la plateforme n'en garde que l'empreinte.
 */
export function PartagerArtefact({ artifactId, onClose }: { artifactId: string; onClose: () => void }) {
  const [people, setPeople] = useState<ArtifactShare[]>([]);
  const [link, setLink] = useState<ArtifactShare | null>(null);
  const [email, setEmail] = useState("");
  const [access, setAccess] = useState<"view" | "edit">("view");
  const [days, setDays] = useState(7);
  const [nouveauLien, setNouveauLien] = useState<string | null>(null);
  const [copie, setCopie] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ton: "ok" | "erreur"; texte: string } | null>(null);

  const charger = useCallback(async () => {
    try {
      const r = await vigil.studio.shares(artifactId);
      setPeople(r.people);
      setLink(r.link);
    } catch (e) {
      setMessage({ ton: "erreur", texte: expliquerCourt(e) });
    }
  }, [artifactId]);

  useEffect(() => {
    void charger();
  }, [charger]);

  const partager = async () => {
    if (!email.trim()) return;
    setBusy(true);
    setMessage(null);
    try {
      const s = await vigil.studio.share(artifactId, email.trim(), access);
      setEmail("");
      setMessage({ ton: "ok", texte: `${s.person?.full_name || s.person?.email} ${access === "edit" ? "peut maintenant modifier" : "peut maintenant lire"} ce document.` });
      await charger();
    } catch (e) {
      setMessage({ ton: "erreur", texte: expliquerCourt(e) });
    } finally {
      setBusy(false);
    }
  };

  const changerAcces = async (s: ArtifactShare, a: "view" | "edit") => {
    if (!s.person) return;
    await vigil.studio.share(artifactId, s.person.email, a).catch((e) => setMessage({ ton: "erreur", texte: expliquerCourt(e) }));
    await charger();
  };

  const retirer = async (s: ArtifactShare) => {
    await vigil.studio.revokeShare(artifactId, s.id).catch((e) => setMessage({ ton: "erreur", texte: expliquerCourt(e) }));
    if (!s.person) setNouveauLien(null);
    await charger();
  };

  const creerLien = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const r = await vigil.studio.createLink(artifactId, days);
      setNouveauLien(`${window.location.origin}${r.path}`);
      setCopie(false);
      await charger();
    } catch (e) {
      setMessage({ ton: "erreur", texte: expliquerCourt(e) });
    } finally {
      setBusy(false);
    }
  };

  const copier = async () => {
    if (!nouveauLien) return;
    try {
      await navigator.clipboard.writeText(nouveauLien);
      setCopie(true);
    } catch {
      setMessage({ ton: "erreur", texte: "Copie impossible depuis ce navigateur : sélectionnez le lien à la main." });
    }
  };

  return (
    <div className="flex flex-col gap-4 rounded-md border border-current/15 p-4" role="dialog" aria-label="Partager le document">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Partager</h3>
        <button type="button" className="text-xs text-text-secondary hover:text-foreground" onClick={onClose}>Fermer</button>
      </div>

      <section className="flex flex-col gap-2">
        <p className="text-xs text-text-secondary">Avec une personne de votre organisme</p>
        <div className="flex flex-wrap gap-2">
          <input
            className={`${champ} min-w-0 flex-1`}
            type="email"
            placeholder="adresse@organisme.fr"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void partager(); }}
            aria-label="Adresse e-mail"
          />
          <select className={champ} value={access} onChange={(e) => setAccess(e.target.value as "view" | "edit")} aria-label="Accès">
            <option value="view">Lecture</option>
            <option value="edit">Modification</option>
          </select>
          <Button onClick={() => void partager()} disabled={busy || !email.trim()}>Partager</Button>
        </div>
        {people.length > 0 && (
          <ul className="flex flex-col gap-1">
            {people.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-2 rounded px-2 py-1.5 text-sm hover:bg-current/5">
                <span className="min-w-0 truncate">
                  {s.person?.full_name || s.person?.email}
                  <span className="ml-2 text-xs text-text-secondary">depuis {dateRelative(s.created_at)}</span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <select className={`${champ} py-1 text-xs`} value={s.access} onChange={(e) => void changerAcces(s, e.target.value as "view" | "edit")} aria-label="Modifier l'accès">
                    <option value="view">Lecture</option>
                    <option value="edit">Modification</option>
                  </select>
                  <button type="button" className="text-xs text-text-secondary hover:text-foreground" onClick={() => void retirer(s)}>Retirer</button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-2 border-t border-current/10 pt-3">
        <p className="text-xs text-text-secondary">Par lien, en lecture seule, sans compte</p>
        {nouveauLien ? (
          <div className="flex flex-col gap-2">
            <div className="flex gap-2">
              <input className={`${champ} min-w-0 flex-1 font-mono text-xs`} readOnly value={nouveauLien} onFocus={(e) => e.target.select()} aria-label="Lien de partage" />
              <Button onClick={() => void copier()}>{copie ? "Copié" : "Copier"}</Button>
            </div>
            <p className="text-xs text-text-secondary">Ce lien ne sera plus affiché : copiez-le maintenant. Créer un nouveau lien désactive celui-ci.</p>
          </div>
        ) : link ? (
          <p className="text-sm">
            Un lien est actif jusqu'au {dateLongue(link.expires_at)}
            {link.last_opened_at ? `, ouvert pour la dernière fois ${dateRelative(link.last_opened_at)}` : ", jamais ouvert pour l'instant"}.
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <select className={champ} value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Durée du lien">
            <option value={1}>Valable 1 jour</option>
            <option value={7}>Valable 7 jours</option>
            <option value={30}>Valable 30 jours</option>
          </select>
          <Button ghost onClick={() => void creerLien()} disabled={busy}>{link ? "Remplacer le lien" : "Créer un lien"}</Button>
          {link && <button type="button" className="text-xs text-text-secondary hover:text-foreground" onClick={() => void retirer(link)}>Désactiver le lien</button>}
        </div>
      </section>

      {message && (
        <p className="text-xs" role="status" style={{ color: message.ton === "ok" ? "var(--color-success)" : "var(--color-destructive)" }}>{message.texte}</p>
      )}
    </div>
  );
}
