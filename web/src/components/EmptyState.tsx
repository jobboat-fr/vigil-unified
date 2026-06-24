import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Consistent empty state: an icon, a one-line title, an optional hint, and an
 *  optional primary action. Replaces bare "no data" strings so every empty page
 *  guides the user to the next step. Uses the dashboard theme tokens. */
export function EmptyState({
  icon, title, hint, action, className,
}: { icon?: ReactNode; title: string; hint?: string; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-12 text-center", className)}>
      {icon && (
        <div className="flex h-11 w-11 items-center justify-center rounded-lg text-text-secondary"
             style={{ background: "color-mix(in srgb, currentColor 7%, transparent)" }}>
          {icon}
        </div>
      )}
      <div className="text-sm font-semibold text-foreground/90">{title}</div>
      {hint && <p className="max-w-xs text-xs leading-relaxed text-text-secondary">{hint}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

/** One shimmering placeholder block. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-current/10", className)} aria-hidden />;
}

/** A column of skeleton rows for list/table loading states. */
export function SkeletonRows({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-2", className)} aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}
