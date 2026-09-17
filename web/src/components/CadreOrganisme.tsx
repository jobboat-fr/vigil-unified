import type { ReactNode } from "react";

/**
 * Cadre des pages publiques (activation, désinscription, nouveau mot de passe) : même identité
 * que les e-mails — logo ou nom de l'organisme en tête, filet à sa couleur, pied « VTLVS ».
 * Quelqu'un qui clique depuis un e-mail arrive sur une page qui lui ressemble.
 */
export function CadreOrganisme({
  organisme,
  logoUrl,
  couleur,
  children,
}: {
  organisme?: string | null;
  logoUrl?: string | null;
  couleur?: string | null;
  children: ReactNode;
}) {
  const accent = couleur && /^#[0-9a-fA-F]{6}$/.test(couleur) ? couleur : "#1D3FAE";
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-4 py-10" style={{ background: "#F4F6FA", color: "#0B2239" }}>
      <div className="w-full max-w-md overflow-hidden rounded-xl bg-white shadow-sm">
        <div className="px-6 py-5" style={{ borderBottom: `3px solid ${accent}` }}>
          {logoUrl ? (
            <img src={logoUrl} alt={organisme ?? ""} className="h-10 max-w-[220px] object-contain" />
          ) : (
            <span className="text-lg font-bold">{organisme ?? "VTLVS"}</span>
          )}
        </div>
        <div className="px-6 py-6">{children}</div>
      </div>
      <a href="https://vtlvs.com" className="mt-5 flex flex-col items-center gap-1 text-[11px]" style={{ color: "#5B6B7F" }}>
        <img src="/logo-lockup.png" alt="VTLVS" className="h-4" />
        Propulsé par VTLVS
      </a>
    </div>
  );
}

export const champPublic = "w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500";

export function BoutonPublic({
  couleur,
  children,
  disabled,
  type = "submit",
  onClick,
}: {
  couleur?: string | null;
  children: ReactNode;
  disabled?: boolean;
  type?: "submit" | "button";
  onClick?: () => void;
}) {
  const accent = couleur && /^#[0-9a-fA-F]{6}$/.test(couleur) ? couleur : "#1D3FAE";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="w-full rounded-lg px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"
      style={{ background: accent }}
    >
      {children}
    </button>
  );
}
