import { useEffect, useRef, useState } from "react";
import { GatewayError } from "./ww";

export interface WwState<T> {
  data: T | null;
  loading: boolean;
  error: GatewayError | null;
  /** True when the failure is just "no VIGIL session" (sign-in prompt, not an error). */
  needsAuth: boolean;
}

/**
 * Poll a WinnyWoo gateway call on an interval. Keeps the last good data across
 * transient failures so the UI doesn't flash empty between refreshes.
 */
export function useWwPoll<T>(fn: () => Promise<T>, intervalMs = 6000): WwState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<GatewayError | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let alive = true;
    async function tick() {
      try {
        const d = await fnRef.current();
        if (alive) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(e as GatewayError);
      } finally {
        if (alive) setLoading(false);
      }
    }
    tick();
    const t = setInterval(tick, intervalMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [intervalMs]);

  return {
    data,
    loading,
    error,
    needsAuth: error?.code === "NO_SESSION",
  };
}
