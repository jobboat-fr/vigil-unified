import { useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Button } from "@nous-research/ui/ui/components/button";
import { useLearnRole } from "@/lib/supabase";
import { LIENS_LEGAUX, support } from "@/lib/compte";
import { expliquerCourt } from "@/lib/refus";

type QR = { q: string; r: string; roles?: string[] };

/** Les réponses décrivent l'application telle qu'elle fonctionne — pas des promesses. */
const FAQ: QR[] = [
  { q: "Je ne vois pas mon planning ou mes sessions.", r: "Vous voyez les sessions liées à votre rôle : l'apprenant ses inscriptions, le formateur les sessions qu'il anime, la direction tout son organisme. Si une session manque, c'est souvent que l'inscription n'est pas encore faite : la direction de votre organisme peut la vérifier." },
  { q: "Pourquoi l'application me demande de signer des documents avant tout ?", r: "Certains documents (règlement intérieur, convention, protocole individuel) doivent être signés avant d'entrer en formation. Tant qu'ils ne le sont pas, seul votre accueil est ouvert. La signature électronique est horodatée et scellée : elle vaut preuve pour l'organisme.", roles: ["apprenant", "formateur", "entreprise"] },
  { q: "Comment émarger ?", r: "Ouvrez « Émargement » pendant le créneau et signez à votre arrivée, puis à votre départ. L'heure vient du serveur, pas de votre téléphone. Une signature ne se modifie plus ensuite, par personne.", roles: ["apprenant", "formateur"] },
  { q: "Quand puis-je utiliser l'assistant ?", r: "Pendant vos créneaux de formation (du quart d'heure avant le début au quart d'heure après la fin). En dehors, il est accessible avec l'abonnement proposé par votre organisme.", roles: ["apprenant"] },
  { q: "L'assistant peut-il voir les données des autres ?", r: "Non. Il lit vos données avec vos propres droits, exactement ce que vous voyez dans l'application. Seules la direction de l'organisme et l'éditeur de la plateforme voient au-delà de leurs propres données." },
  { q: "Comment partager un document du studio ?", r: "Ouvrez le document puis « Partager » : avec une personne de votre organisme (lecture ou modification), ou par un lien public en lecture seule qui expire après 1, 7 ou 30 jours. Vous pouvez retirer un accès à tout moment." },
  { q: "Comment faire rejoindre une salle de réunion à un invité externe ?", r: "Depuis la salle, créez le lien d'invitation. Il expire après la séance et ne donne accès qu'à cette salle.", roles: ["super_admin", "admin", "formateur"] },
  { q: "Comment ajouter une action requise à quelqu'un ?", r: "Ouvrez « Actions requises », choisissez une personne, un rôle ou les inscrits d'une session, et une échéance. Les rappels partent à J0, J+2 et J+5 ; la direction est alertée à J+7.", roles: ["super_admin", "admin"] },
  { q: "Mes e-mails partent-ils au nom de mon organisme ?", r: "Oui, dès que le domaine d'envoi de l'organisme est vérifié dans « Identité & e-mails ». Chaque modèle d'e-mail est validé une fois avant le premier envoi.", roles: ["super_admin", "admin"] },
  { q: "Que devient mon compte si je le supprime ?", r: "Vos informations personnelles et vos documents disparaissent, l'accès est fermé. Les preuves de formation que la loi oblige à garder (émargements, signatures, évaluations) restent, sans votre nom. Tout se fait depuis « Mon compte », où vous pouvez aussi télécharger toutes vos données." },
  { q: "J'ai oublié mon mot de passe.", r: "Sur l'écran de connexion, « Mot de passe oublié ». Le lien arrive au nom de votre organisme et expire rapidement." },
];

const LIENS = [
  { titre: "Académie", texte: "L'application écran par écran, selon votre rôle.", href: "https://vtlvsacademy.vtlvs.com" },
  { titre: "Documentation", texte: "Architecture, API, rôles et sécurité.", href: "https://docs.vtlvs.com" },
  { titre: "État des services", texte: "Chaque service, en direct.", href: "https://status.vtlvs.com" },
];

export default function AidePage() {
  const { role } = useLearnRole();
  const { pathname } = useLocation();
  const [ouverte, setOuverte] = useState<number | null>(null);
  const [recherche, setRecherche] = useState("");
  const [sujet, setSujet] = useState("");
  const [message, setMessage] = useState("");
  const [envoi, setEnvoi] = useState<{ etat: "repos" | "cours" | "ok" | "erreur"; texte?: string }>({ etat: "repos" });

  const questions = useMemo(() => {
    const r = recherche.trim().toLowerCase();
    return FAQ.filter((f) => (!f.roles || (role && f.roles.includes(role))) && (!r || (f.q + f.r).toLowerCase().includes(r)));
  }, [role, recherche]);

  const envoyer = async () => {
    setEnvoi({ etat: "cours" });
    try {
      const res = await support.demander(sujet.trim(), message.trim(), pathname);
      setEnvoi({ etat: "ok", texte: `Demande enregistrée — référence ${res.reference}. La réponse arrivera par e-mail et ici.` });
      setSujet("");
      setMessage("");
    } catch (e) {
      setEnvoi({ etat: "erreur", texte: `${expliquerCourt(e)} Votre message est gardé.` });
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 pb-10">
      <section className="grid gap-3 sm:grid-cols-3">
        <Link to="/chat" className="rounded-xl border border-current/15 p-4 transition hover:border-current/40">
          <p className="font-semibold">Demander à l'assistant</p>
          <p className="mt-1 text-sm text-text-secondary">Une réponse en quelques secondes, avec vos données.</p>
        </Link>
        <a href="#demande" className="rounded-xl border border-current/15 p-4 transition hover:border-current/40">
          <p className="font-semibold">Écrire au support</p>
          <p className="mt-1 text-sm text-text-secondary">Une personne vous répond, par e-mail et ici.</p>
        </a>
        <Link to="/compte" className="rounded-xl border border-current/15 p-4 transition hover:border-current/40">
          <p className="font-semibold">Mon compte</p>
          <p className="mt-1 text-sm text-text-secondary">Mes données, leur export, la suppression.</p>
        </Link>
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <h2 className="text-lg font-semibold">Questions fréquentes</h2>
          <input value={recherche} onChange={(e) => setRecherche(e.target.value)} placeholder="Chercher…" aria-label="Chercher dans les questions"
            className="w-full rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none sm:w-60" />
        </div>
        <div className="divide-y divide-current/10 rounded-xl border border-current/15">
          {questions.length === 0 && <p className="p-4 text-sm text-text-secondary">Aucune question ne correspond. Écrivez-nous plus bas.</p>}
          {questions.map((f, i) => (
            <div key={f.q}>
              <button type="button" aria-expanded={ouverte === i} onClick={() => setOuverte(ouverte === i ? null : i)}
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-medium">
                <span>{f.q}</span>
                <span aria-hidden className="shrink-0 text-lg leading-none opacity-50">{ouverte === i ? "−" : "+"}</span>
              </button>
              {ouverte === i && <p className="px-4 pb-4 text-sm leading-relaxed text-text-secondary">{f.r}</p>}
            </div>
          ))}
        </div>
      </section>

      <section id="demande" className="flex flex-col gap-3 rounded-xl border border-current/15 p-4">
        <h2 className="text-lg font-semibold">Écrire au support</h2>
        <input value={sujet} onChange={(e) => setSujet(e.target.value)} placeholder="Sujet — par exemple : je ne peux pas signer ma convention"
          className="rounded-md border border-current/20 bg-transparent px-3 py-2 text-base outline-none" maxLength={160} />
        <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={5} maxLength={5000}
          placeholder="Ce que vous faisiez, ce qui s'est passé, ce que vous attendiez."
          className="rounded-md border border-current/20 bg-transparent px-3 py-2 text-base outline-none" />
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void envoyer()} disabled={envoi.etat === "cours" || sujet.trim().length < 3 || message.trim().length < 10}>
            {envoi.etat === "cours" ? "Envoi…" : "Envoyer"}
          </Button>
          {envoi.texte && <span className="text-xs" role="status" style={{ color: envoi.etat === "ok" ? "var(--color-success)" : "var(--color-destructive)" }}>{envoi.texte}</span>}
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-3">
        {LIENS.map((l) => (
          <a key={l.href} href={l.href} target="_blank" rel="noreferrer" className="rounded-xl border border-current/10 p-4 text-sm hover:border-current/30">
            <p className="font-medium">{l.titre} ↗</p>
            <p className="mt-1 text-text-secondary">{l.texte}</p>
          </a>
        ))}
      </section>

      <nav className="flex flex-wrap gap-x-4 gap-y-1 px-1 text-xs text-text-secondary" aria-label="Documents légaux">
        {LIENS_LEGAUX.map((l) => <a key={l.href} href={l.href} target="_blank" rel="noreferrer" className="hover:underline">{l.label}</a>)}
      </nav>
    </div>
  );
}
