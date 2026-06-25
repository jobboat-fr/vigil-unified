import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { Send } from "lucide-react";
import { streamAssistantChat } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";

/**
 * VIGIL assistant chat. Talks to the gateway's /v1/assistant/chat (HTTP SSE,
 * Railway → Hermes) — NOT the embedded TUI PTY, which can't run through the
 * Vercel proxy (no WebSocket support). Branded as VIGIL; streams tokens live.
 */
type Msg = { role: "user" | "assistant"; text: string; error?: boolean };

function newSession(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `s-${Date.now().toString(36)}`;
}

export default function AssistantChatPage() {
  const { pathname } = useLocation();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const sessionRef = useRef<string>(newSession());
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", text }, { role: "assistant", text: "" }]);
    const appendToLast = (chunk: string, asError = false) =>
      setMessages((m) => {
        const next = [...m];
        const last = next[next.length - 1];
        if (last?.role === "assistant") next[next.length - 1] = { role: "assistant", text: last.text + chunk, error: asError || last.error };
        return next;
      });
    try {
      for await (const evt of streamAssistantChat(text, sessionRef.current, { page: pathname })) {
        if (evt.event === "text_delta") appendToLast(String((evt.data as { content?: string }).content ?? ""));
        else if (evt.event === "error") appendToLast(`\n\n⚠️ ${(evt.data as { message?: string }).message ?? "assistant error"}`, true);
        else if (evt.event === "done") break;
      }
    } catch (e) {
      const msg = e instanceof GatewayError && e.code === "NO_SESSION" ? "Sign in to VIGIL to use the assistant." : (e as Error).message;
      appendToLast(`\n\n⚠️ ${msg}`, true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-3xl flex-col gap-4 px-1 py-4">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center gap-3 pt-[12vh] text-center">
              <img src="/vigil-mark.svg" alt="VIGIL" width={48} height={48} />
              <h1 className="font-mondwest text-display text-2xl tracking-wide text-midground">VIGIL Assistant</h1>
              <p className="max-w-sm text-sm text-text-secondary">
                Ask anything — it reasons over your Vault, books, and live data, and thinks before it acts.
              </p>
            </div>
          ) : (
            messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div
                  className="max-w-[85%] whitespace-pre-wrap rounded-lg px-3.5 py-2.5 text-sm leading-relaxed"
                  style={
                    m.role === "user"
                      ? { background: "color-mix(in srgb, currentColor 12%, transparent)", color: "var(--color-foreground)" }
                      : { border: "1px solid var(--color-border)", color: m.error ? "#fb7185" : "var(--color-foreground)" }
                  }
                >
                  {m.text || (m.role === "assistant" && busy ? "…" : "")}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-current/10 py-3">
        <div className="mx-auto flex max-w-3xl items-end gap-2 px-1">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
            rows={1}
            placeholder="Message the VIGIL assistant…"
            aria-label="Message the VIGIL assistant"
            className="max-h-40 min-h-[2.5rem] flex-1 resize-none rounded-lg border border-current/20 bg-transparent px-3 py-2 text-sm outline-none focus:border-current/50"
          />
          <button
            onClick={() => void send()}
            disabled={busy || !input.trim()}
            aria-label="Send"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg disabled:opacity-40"
            style={{ background: "var(--color-foreground)", color: "var(--background-base)" }}
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
