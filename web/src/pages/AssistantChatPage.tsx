import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { accesAssistant, streamAssistantChat, type AccesAssistant } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";
import { useLearnRole } from "@/lib/supabase";
import { Refus } from "@/components/Refus";
import { expliquerCourt } from "@/lib/refus";

/**
 * Assistant de l'application — une conversation, pensée d'abord pour le téléphone.
 *
 * La passerelle décide qui peut parler à l'assistant (winny_gateway/assistant_vtlvs.py) ; la page
 * le demande avant la saisie et l'explique au lieu d'afficher une erreur au premier envoi.
 */
type Msg = { role: "user" | "assistant"; text: string; error?: boolean };

const SUGGESTIONS: Record<string, string[]> = {
  apprenant: ["Qu'est-ce que je dois faire aujourd'hui ?", "Où signer mes documents ?", "Quand est mon prochain créneau ?"],
  formateur: ["Mes créneaux de la semaine", "Comment faire émarger ma session ?", "Ouvrir une salle pour mon cours"],
  admin: ["Qu'est-ce qui est en retard ?", "Inviter un apprenant", "Où voir les documents non signés ?"],
  super_admin: ["Qu'est-ce qui demande mon attention ?", "Ajouter une action requise", "Vérifier l'identité e-mail d'un organisme"],
  entreprise: ["Où en sont mes salariés ?", "Où trouver les attestations ?", "Prochaines sessions"],
  auditeur: ["Où sont les preuves Qualiopi ?", "Voir les émargements", "Documents du coffre"],
};

function newSession(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `s-${Date.now().toString(36)}`;
}

const heure = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "";

/** Rendu sûr d'un texte court : puces « - », gras **…** ; aucun HTML interprété. */
function Texte({ texte }: { texte: string }) {
  const gras = (s: string): ReactNode[] =>
    s.split(/(\*\*[^*]+\*\*)/g).map((p, i) => (p.startsWith("**") && p.endsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong> : <Fragment key={i}>{p}</Fragment>));
  const lignes = texte.split("\n");
  const blocs: ReactNode[] = [];
  let puces: string[] = [];
  const vider = () => {
    if (puces.length) blocs.push(<ul key={`u${blocs.length}`} className="my-1 list-disc space-y-1 pl-5">{puces.map((p, i) => <li key={i}>{gras(p)}</li>)}</ul>);
    puces = [];
  };
  for (const l of lignes) {
    const m = l.match(/^\s*[-•*]\s+(.*)$/);
    if (m) puces.push(m[1]);
    else {
      vider();
      if (l.trim()) blocs.push(<p key={`p${blocs.length}`} className="my-1">{gras(l)}</p>);
    }
  }
  vider();
  return <>{blocs}</>;
}

export default function AssistantChatPage() {
  const { pathname } = useLocation();
  const { role } = useLearnRole();
  const [acces, setAcces] = useState<AccesAssistant | null>(null);
  const [erreurAcces, setErreurAcces] = useState<unknown>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<string>(newSession());
  const finRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    accesAssistant()
      .then((a) => {
        setAcces(a);
        setErreurAcces(null);
      })
      // On garde l'erreur, on ne la recopie pas dans `message` : `e.message` est souvent
      // un code (« HTTP 503 »), et il finissait affiché tel quel sous un titre qui
      // annonçait une indisponibilité alors qu'il s'agissait d'une session expirée.
      .catch((e: unknown) => {
        setAcces({ ouvert: false });
        setErreurAcces(e);
      });
  }, []);

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const send = async (texte?: string) => {
    const text = (texte ?? input).trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text }, { role: "assistant", text: "" }]);
    const ajouter = (chunk: string, erreur = false) =>
      setMessages((m) => {
        const next = [...m];
        const last = next[next.length - 1];
        if (last?.role === "assistant") next[next.length - 1] = { role: "assistant", text: last.text + chunk, error: erreur || last.error };
        return next;
      });
    try {
      for await (const evt of streamAssistantChat(text, sessionRef.current, { page: pathname })) {
        if (evt.event === "text_delta") ajouter(String((evt.data as { content?: string }).content ?? ""));
        else if (evt.event === "error") ajouter((evt.data as { message?: string }).message ?? "L'assistant a rencontré un problème.", true);
        else if (evt.event === "done") break;
      }
    } catch (e) {
      const err = e as GatewayError;
      if (err.status === 402 || err.status === 403) {
        // Une limite d'offre n'est pas une réponse ratée. On retire la bulle vide et on
        // relit l'accès : le bandeau au-dessus dira ce qui est fermé et proposera le
        // geste. Écrire en rouge « il faut payer » dans le fil de la conversation donne
        // à une limite prévue l'allure d'une panne — c'est exactement ce qu'on corrige.
        setMessages((m) => m.slice(0, -1));
        accesAssistant()
          .then((a) => {
            setAcces(a);
            setErreurAcces(null);
          })
          .catch(() => setErreurAcces(e));
        return;
      }
      ajouter(
        err.code === "NO_SESSION"
          ? "Votre session a expiré : reconnectez-vous pour continuer."
          : `${expliquerCourt(e, "l'assistant")} Votre message est gardé ci-dessus.`,
        true,
      );
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  const suggestions = SUGGESTIONS[role ?? ""] ?? SUGGESTIONS.apprenant;
  const ferme = Boolean(acces && !acces.ouvert);

  /**
   * Pourquoi c'est fermé, sous la forme que le traducteur commun sait lire.
   *
   * `/acces` répond 200 avec `{ouvert:false, raison}` là où `/chat` lève le refus HTTP
   * correspondant — mêmes codes, deux formes. On ramène la première à la seconde plutôt
   * que d'écrire ici un second jeu de phrases : deux textes pour un même refus finissent
   * toujours par ne plus dire la même chose.
   *
   * `assistant_hors_formation` est une limite d'offre (402) et se lit comme telle, avec
   * le lien vers l'abonnement. Tout autre motif est un refus de rôle (403).
   */
  const motifFerme = useMemo(() => {
    if (erreurAcces) return erreurAcces;
    if (!ferme) return null;
    return {
      status: acces?.raison === "assistant_hors_formation" ? 402 : 403,
      code: acces?.raison,
      detail: {
        error: acces?.raison,
        detail: acces?.message,
        prochain_creneau: acces?.prochain_creneau,
      },
    };
  }, [ferme, acces, erreurAcces]);

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-current/10 px-1 pb-2">
        <p className="min-w-0 text-xs text-text-secondary">Il répond avec vos données, jamais celles des autres.</p>
        {acces?.ouvert && acces.motif === "creneau" && (
          <span className="rounded-full border border-current/20 px-2.5 py-0.5 text-xs">Pendant votre formation · jusqu'à {heure(acces.fin_creneau)}</span>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-6" aria-live="polite">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-3">
          {acces === null && <div className="h-16 animate-pulse rounded-xl bg-current/5" aria-label="Chargement" />}

          {motifFerme != null && <Refus erreur={motifFerme} quoi="l'assistant" compact className="my-2" />}

          {acces?.ouvert && messages.length === 0 && (
            <div className="flex flex-col gap-3 py-6 text-center">
              <p className="text-base">Bonjour. Que puis-je faire pour vous ?</p>
              <div className="flex flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button key={s} type="button" onClick={() => void send(s)} className="rounded-full border border-current/20 px-3 py-1.5 text-sm hover:border-current/50">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[88%] break-words rounded-2xl px-3.5 py-2 text-[15px] leading-relaxed sm:max-w-[80%] ${
                  m.role === "user" ? "rounded-br-md bg-current/10" : "rounded-bl-md border border-current/10"
                }`}
                style={m.error ? { color: "var(--color-destructive)" } : undefined}
              >
                {m.role === "assistant" && !m.text && busy && i === messages.length - 1 ? (
                  <span className="inline-flex gap-1" aria-label="L'assistant écrit">
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current/60" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current/60 [animation-delay:120ms]" />
                    <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-current/60 [animation-delay:240ms]" />
                  </span>
                ) : m.role === "assistant" ? (
                  <Texte texte={m.text} />
                ) : (
                  <span className="whitespace-pre-wrap">{m.text}</span>
                )}
              </div>
            </div>
          ))}
          <div ref={finRef} />
        </div>
      </div>

      <form
        className="border-t border-current/10 px-3 pt-2 sm:px-6"
        style={{ paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))" }}
        onSubmit={(e) => { e.preventDefault(); void send(); }}
      >
        <div className="mx-auto flex w-full max-w-2xl items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
            rows={1}
            disabled={busy || !acces?.ouvert}
            aria-label="Écrire à l'assistant"
            placeholder={
              acces?.ouvert
                ? "Écrivez votre question…"
                : ferme || erreurAcces
                  ? "Fermé pour l'instant — la raison est indiquée ci-dessus"
                  : "Vérification de l'accès…"
            }
            className="max-h-40 min-h-[44px] min-w-0 flex-1 resize-none rounded-xl border border-current/20 bg-transparent px-3 py-2.5 text-base outline-none focus:border-current/50"
          />
          <button
            type="submit"
            disabled={busy || !input.trim() || !acces?.ouvert}
            className="h-11 shrink-0 rounded-xl px-4 text-sm font-medium disabled:opacity-40"
            style={{ background: "currentColor" }}
          >
            <span style={{ color: "var(--background, #fff)" }}>{busy ? "…" : "Envoyer"}</span>
          </button>
        </div>
      </form>
    </div>
  );
}
