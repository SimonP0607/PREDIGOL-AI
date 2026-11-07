/**
 * What the reader did with a guide that could not be sent (no connection): kept on this device and sent again when the guide
 * next speaks to the API (plan UX-051, section 7). Only the last thing per guide is kept - the server decides which status
 * stands - and nothing here is ever the only copy of a view: the account's own state is the API's. Storage may be missing or
 * full (a private window): every read and write is guarded and the guides simply carry on without a queue.
 */
import type { GuideIn, GuideKey } from "@/lib/api/v1/types_guides";

const KEY = "predigol.guides.queue.v1";

export type Queue = Partial<Record<GuideKey, GuideIn>>;

export function readQueue(): Queue {
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? (parsed as Queue) : {};
  } catch {
    return {};
  }
}

function write(queue: Queue): void {
  try {
    if (Object.keys(queue).length === 0) window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, JSON.stringify(queue));
  } catch {
    // storage unavailable: nothing to keep
  }
}

export function enqueue(guide: GuideKey, body: GuideIn): void {
  write({ ...readQueue(), [guide]: body });
}

export function dequeue(guide: GuideKey): void {
  const queue = readQueue();
  if (!(guide in queue)) return;
  delete queue[guide];
  write(queue);
}

/** Sends what is waiting, each guide once; a guide that fails again stays for the next time. */
export async function flush(
  send: (guide: GuideKey, body: GuideIn) => Promise<unknown>,
): Promise<void> {
  const queue = readQueue();
  for (const [guide, body] of Object.entries(queue) as [GuideKey, GuideIn][]) {
    try {
      await send(guide, body);
      dequeue(guide);
    } catch {
      return;
    }
  }
}
