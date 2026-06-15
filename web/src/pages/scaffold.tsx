import type { ReactNode } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import { Spinner } from "@nous-research/ui/ui/components/spinner";
import type { WwState } from "@/lib/useWw";

/**
 * Wrap live gateway-backed content with consistent loading / sign-in / offline
 * states. Keeps showing data across transient refresh failures.
 */
export function WwGate({
  state,
  children,
}: {
  state: WwState<unknown>;
  children: ReactNode;
}) {
  if (state.data == null && state.loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner />
      </div>
    );
  }
  if (state.data == null && state.needsAuth) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-text-secondary">
          Sign in to VIGIL to load live data.
        </CardContent>
      </Card>
    );
  }
  if (state.data == null && state.error) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-text-secondary">
          Live feed offline — retrying…
        </CardContent>
      </Card>
    );
  }
  return <>{children}</>;
}

/**
 * Shared shell for the VIGIL × WinnyWoo product pages added on top of the
 * agent runtime. These render as branded, navigable scaffolds; the live data
 * + logic are wired in a later pass (see docs/VIGIL_HERMES_MIGRATION.md).
 */
export function ScaffoldPage({
  title,
  tagline,
  points,
  source,
}: {
  title: string;
  tagline: string;
  points: string[];
  source: string;
}) {
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="text-sm text-text-secondary">{tagline}</p>
          <ul className="list-disc pl-5 text-sm text-text-secondary space-y-1">
            {points.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
          <p className="text-xs opacity-60 font-mono">
            data source: {source} · UI scaffolded — logic wiring next
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
