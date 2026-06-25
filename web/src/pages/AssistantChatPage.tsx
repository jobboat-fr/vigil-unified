import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { streamAssistantChat } from "@/lib/vigil";
import { GatewayError } from "@/lib/ww";

/**
 * VIGIL assistant chat, styled like the original embedded TERMINAL (monospace,
 * dark canvas, shell prompts, blinking cursor) — but backed by the gateway's
 * /v1/assistant/chat (HTTP SSE: browser → Railway → Hermes /chat/stream). The
 * PTY-over-WebSocket terminal can't run through the Vercel proxy, so this gives
 * the same look with a transport that actually works.
 */
type Msg = { role: "user" | "assistant"; text: string; error?: boolean };

const BG = "#04201d";       // terminal canvas (deep teal-black)
const FG = "#f0e6d2";       // cream foreground (xterm theme)
const GOLD = "#ffbd38";     // prompt accent
const EMER = "#34d399";
const MONO = "'JetBrains Mono', ui-monospace, 'Cascadia Mono', Menlo, Consolas, monospace";

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
  const inputRef = useRef<HTMLTextAreaElement>(null);

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
        else if (evt.event === "error") appendToLast(`\n[error] ${(evt.data as { message?: string }).message ?? "assistant error"}`, true);
        else if (evt.event === "done") break;
      }
    } catch (e) {
      const msg = e instanceof GatewayError && e.code === "NO_SESSION" ? "sign in to VIGIL to use the assistant" : (e as Error).message;
      appendToLast(`\n[error] ${msg}`, true);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col p-2 sm:p-3">
      <style>{`
        @keyframes vt-blink{0%,49%{opacity:1}50%,100%{opacity:0}}
        .vt-cursor{display:inline-block;width:.55ch;background:${EMER};animation:vt-blink 1.1s step-end infinite}
        .vt-scroll::-webkit-scrollbar{width:9px}
        .vt-scroll::-webkit-scrollbar-thumb{background:${FG}22;border-radius:9px}
      `}</style>
      <div
        ref={scrollRef}
        onClick={() => inputRef.current?.focus()}
        className="vt-scroll min-h-0 flex-1 overflow-y-auto rounded-lg p-3 sm:p-4"
        style={{ background: BG, color: FG, fontFamily: MONO, fontSize: 13.5, lineHeight: 1.5, boxShadow: "0 8px 32px rgba(0,0,0,.4)" }}
      >
        {/* Boot banner — our logo, terminal-style (replaces the Hermes ASCII) */}
        <div style={{ color: GOLD, whiteSpace: "pre" }}>{
`██╗   ██╗██╗ ██████╗ ██╗██╗
██║   ██║██║██╔════╝ ██║██║
██║   ██║██║██║  ███╗██║██║
╚██╗ ██╔╝██║██║   ██║██║██║
 ╚████╔╝ ██║╚██████╔╝██║███████╗
  ╚═══╝  ╚═╝ ╚═════╝ ╚═╝╚══════╝`}</div>
        <div style={{ opacity: 0.6 }}>VIGIL assistant · thinks before it acts · type below ↵</div>
        <div style={{ opacity: 0.45, marginBottom: 12 }}>grounded in your vault, books & live data · human-in-the-loop</div>

        {messages.map((m, i) => {
          const isLastAssistant = i === messages.length - 1 && m.role === "assistant";
          if (m.role === "user") {
            return (
              <div key={i} style={{ marginTop: 8, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                <span style={{ color: GOLD }}>you ❯ </span>{m.text}
              </div>
            );
          }
          return (
            <div key={i} style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", color: m.error ? "#fb7185" : FG }}>
              <span style={{ color: EMER }}>vigil ❯ </span>{m.text}
              {isLastAssistant && busy && <span className="vt-cursor">&nbsp;</span>}
            </div>
          );
        })}

        {/* Live prompt line */}
        <div style={{ marginTop: 8, display: "flex" }}>
          <span style={{ color: GOLD, flexShrink: 0 }}>you ❯&nbsp;</span>
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(); } }}
            rows={1}
            autoFocus
            aria-label="Message the VIGIL assistant"
            placeholder={busy ? "…working" : "ask anything"}
            disabled={busy}
            className="flex-1 resize-none bg-transparent outline-none placeholder:opacity-40"
            style={{ color: FG, fontFamily: MONO, fontSize: 13.5, lineHeight: 1.5, border: "none", caretColor: EMER }}
          />
        </div>
      </div>
    </div>
  );
}
