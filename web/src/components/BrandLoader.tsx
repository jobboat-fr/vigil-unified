import { BRAND } from "@/lib/brand";

/** Full-screen branded loading state — the VIGIL mark on the teal canvas with a
 *  blinking-cursor caption. Announced to assistive tech via role="status", and
 *  the motion respects prefers-reduced-motion. */
export function BrandLoader({ label = "Loading your workspace" }: { label?: string }) {
  return (
    <div
      className="flex min-h-dvh flex-col items-center justify-center gap-4"
      style={{ background: BRAND.bg, color: BRAND.ink }}
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={label}
    >
      <style>{`
        @keyframes vg-pulse{0%,100%{opacity:.4;transform:scale(.96)}50%{opacity:1;transform:scale(1)}}
        @keyframes vg-blink{0%,49%{opacity:1}50%,100%{opacity:0}}
        .vg-mark{animation:vg-pulse 1.4s ease-in-out infinite}
        .vg-cur{animation:vg-blink 1.1s step-end infinite}
        @media (prefers-reduced-motion: reduce){.vg-mark,.vg-cur{animation:none}}
      `}</style>
      <img className="vg-mark" src="/vigil-mark.svg" alt="" width={44} height={44} />
      <div style={{ fontFamily: BRAND.mono, fontSize: 11, letterSpacing: ".22em", textTransform: "uppercase", color: `${BRAND.ink}99` }}>
        {label}
        <span aria-hidden className="vg-cur" style={{ color: BRAND.gold }}>_</span>
      </div>
    </div>
  );
}
