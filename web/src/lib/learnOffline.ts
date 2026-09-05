// LEARN — offline émargement queue.
//
// The one feature that genuinely needs a native shell: a training room in a basement with
// no signal, twelve people signing on their phones.
//
// It carries an integrity problem that has to be solved out loud rather than papered over.
// A signature written when the phone reconnects is recorded *later than it happened*, and
// `signed_at` is deliberately the server's clock — a phone's clock belongs to the person
// holding the phone, so we will not let it set the authoritative time.
//
// The resolution: queue the attempt with the device's own reading of when it was made, and
// send that as `offline_at` inside the evidence bundle. The authoritative `signed_at` stays
// the server time of the write, and the feuille shows both. An auditor then sees exactly
// what happened — "signed on the device at 09:02, recorded at 11:40 on reconnection" —
// instead of a timestamp that quietly misrepresents the room.
//
// The alternative, trusting the device clock, would let anyone sign for yesterday.

const KEY = "learn.offline.signatures.v1";

export interface QueuedSignature {
  slotId: string;
  kind: "in" | "out" | "countersign";
  /** The device's reading of when the person actually signed. Evidence, not authority. */
  offlineAt: string;
  attempts: number;
  lastError?: string;
}

function read(): QueuedSignature[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as QueuedSignature[]) : [];
  } catch {
    // A private window, cleared storage, or a browser refusing site data. An empty queue
    // is the correct answer; throwing here would break signing for everyone.
    return [];
  }
}

function write(q: QueuedSignature[]): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(q));
  } catch {
    /* storage unavailable — the caller already has the network result it needs */
  }
}

export function pending(): QueuedSignature[] {
  return read();
}

export function enqueue(slotId: string, kind: QueuedSignature["kind"]): void {
  const q = read();
  // One entry per (slot, kind): signing twice offline is the same act, not two.
  if (q.some((x) => x.slotId === slotId && x.kind === kind)) return;
  q.push({ slotId, kind, offlineAt: new Date().toISOString(), attempts: 0 });
  write(q);
}

/**
 * Send one signature, queueing it if the network is unreachable.
 *
 * Returns `"sent"`, `"queued"`, or throws for a real refusal — a 403 from the policy layer
 * or a 409 for an already-recorded signature must not be retried forever, so those are
 * surfaced rather than swallowed into the queue.
 */
export async function signOrQueue(
  slotId: string,
  kind: QueuedSignature["kind"],
  send: (slotId: string, kind: QueuedSignature["kind"], offlineAt?: string) => Promise<unknown>,
): Promise<"sent" | "queued"> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    enqueue(slotId, kind);
    return "queued";
  }
  try {
    await send(slotId, kind);
    return "sent";
  } catch (e) {
    const status = (e as { status?: number }).status;
    // 4xx is the server deciding; only a transport failure deserves a retry.
    if (status && status >= 400 && status < 500) throw e;
    enqueue(slotId, kind);
    return "queued";
  }
}

/**
 * Replay the queue. Each entry carries the device time it was made, so the evidence bundle
 * records both when the person signed and when we managed to store it.
 */
export async function flush(
  send: (slotId: string, kind: QueuedSignature["kind"], offlineAt?: string) => Promise<unknown>,
): Promise<{ sent: number; failed: number; remaining: number }> {
  const q = read();
  if (q.length === 0) return { sent: 0, failed: 0, remaining: 0 };

  const keep: QueuedSignature[] = [];
  let sent = 0;
  let failed = 0;

  for (const item of q) {
    try {
      await send(item.slotId, item.kind, item.offlineAt);
      sent += 1;
    } catch (e) {
      const status = (e as { status?: number }).status;
      // 409 means it is already recorded — the queue did its job, drop it.
      if (status === 409) {
        sent += 1;
        continue;
      }
      // A policy refusal will never succeed on retry; keep it visible instead of looping.
      failed += 1;
      keep.push({
        ...item,
        attempts: item.attempts + 1,
        lastError: (e as Error).message,
      });
    }
  }

  write(keep);
  return { sent, failed, remaining: keep.length };
}

/** Replay automatically when the device comes back. Returns an unsubscribe function. */
export function autoFlush(
  send: (slotId: string, kind: QueuedSignature["kind"], offlineAt?: string) => Promise<unknown>,
): () => void {
  const handler = () => void flush(send);
  window.addEventListener("online", handler);
  if (navigator.onLine) handler();
  return () => window.removeEventListener("online", handler);
}
