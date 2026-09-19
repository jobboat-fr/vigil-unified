import { BRAND } from "@/lib/brand";
import { MarqueVtlvs } from "@/components/MarqueVtlvs";

/** Écran de chargement plein cadre — la marque VTLVS sur le fond de la charte, avec
 *  une légende à curseur clignotant. Annoncé aux technologies d'assistance via
 *  role="status" ; l'animation respecte prefers-reduced-motion. */
export function BrandLoader({ label = "Ouverture de votre espace" }: { label?: string }) {
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
      <MarqueVtlvs hauteur={44} className="vg-mark" />
      <div style={{ fontFamily: BRAND.mono, fontSize: 11, letterSpacing: ".22em", textTransform: "uppercase", color: `${BRAND.ink}99` }}>
        {label}
        <span aria-hidden className="vg-cur" style={{ color: BRAND.gold }}>_</span>
      </div>
    </div>
  );
}
