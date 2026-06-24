import { BRAND } from "@/lib/brand";

/** Full-screen branded loading state — the VIGIL mark on the teal canvas with a
 *  blinking-cursor caption. Used wherever the app would otherwise show a bare
 *  spinner (auth gate, OAuth callback), so the wait feels on-brand. */
export function BrandLoader({ label = "Loading your workspace" }: { label?: string }) {
  return (
    <div
      className="flex min-h-dvh flex-col items-center justify-center gap-4"
      style={{ background: BRAND.bg, color: BRAND.ink }}
    >
      <style>{`
        @keyframes vg-pulse{0%,100%{opacity:.4;transform:scale(.96)}50%{opacity:1;transform:scale(1)}}
        @keyframes vg-blink{0%,49%{opacity:1}50%,100%{opacity:0}}
      `}</style>
      <img src="/vigil-mark.svg" alt="" width={44} height={44} style={{ animation: "vg-pulse 1.4s ease-in-out infinite" }} />
      <div style={{ fontFamily: BRAND.mono, fontSize: 11, letterSpacing: ".22em", textTransform: "uppercase", color: `${BRAND.ink}99` }}>
        {label}
        <span style={{ color: BRAND.gold, animation: "vg-blink 1.1s step-end infinite" }}>_</span>
      </div>
    </div>
  );
}
