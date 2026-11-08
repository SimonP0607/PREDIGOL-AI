/**
 * What the reader did with a guide that could not be sent (no connection): kept on this device and sent again when the guide
 * next speaks to the API (plan UX-051, section 7). Only the last thing per guide is kept - the server decides which status
 * stands - and nothing here is ever the only copy of a view: the account's own state is the API's. Storage may be missing or
 * full (a private window): every read and write is guarded and the guides simply carry on without a queue.
 *
 * Each account has its own queue (UX-070): on a shared browser what one reader left waiting is never sent with the session
 * of the next one. The first queue had a single key for the whole device and no owner: whose it was cannot be known, so it
 * is dropped, never sent as anyone's.
 */
import type { GuideIn, GuideKey } from "@/lib/api/v1/types_guides";

const PREFIX = "predigol.guides.queue.v2:";
const LEGACY = "predigol.guides.queue.v1";

export type Queue = Partial<Record<GuideKey, GuideIn>>;

/** The account a queue belongs to: the id of the account that did it. */
export type Owner = number;

const keyOf = (owner: Owner) => `${PREFIX}${owner}`;

export function readQueue(owner: Owner): Queue {
  try {
    const raw = window.localStorage.getItem(keyOf(owner));
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Queue) : {};
  } catch {
    return {};
  }
}

function write(owner: Owner, queue: Queue): void {
  try {
    if (Object.keys(queue).length === 0) window.localStorage.removeItem(keyOf(owner));
    else window.localStorage.setItem(keyOf(owner), JSON.stringify(queue));
  } catch {
    // storage unavailable: nothing to keep
  }
}

export function enqueue(owner: Owner, guide: GuideKey, body: GuideIn): void {
  write(owner, { ...readQueue(owner), [guide]: body });
}

export function dequeue(owner: Owner, guide: GuideKey): void {
  const queue = readQueue(owner);
  if (!(guide in queue)) return;
  delete queue[guide];
  write(owner, queue);
}

/** The device-wide queue of before UX-070: no owner, so it goes. */
export function dropLegacy(): void {
  try {
    window.localStorage.removeItem(LEGACY);
  } catch {
    // storage unavailable: nothing to drop
  }
}

/**
 * Whether the API turned a write down for good (a closed list it does not accept): sending it again would only fail again
 * and hold back what waits behind it. A lost connection, a session that ended, a limit or the server's own error is not:
 * the write waits for the next time.
 */
export function refused(err: unknown): boolean {
  const status = (err as { status?: unknown } | null)?.status;
  return (
    typeof status === "number" &&
    status >= 400 &&
    status < 500 &&
    ![401, 403, 408, 429].includes(status)
  );
}

/** Sends what is waiting for one account, each guide once; a guide that fails again stays for the next time. */
export async function flush(
  owner: Owner,
  send: (guide: GuideKey, body: GuideIn) => Promise<unknown>,
): Promise<void> {
  const queue = readQueue(owner);
  for (const [guide, body] of Object.entries(queue) as [GuideKey, GuideIn][]) {
    try {
      await send(guide, body);
      dequeue(owner, guide);
    } catch (err) {
      if (!refused(err)) return;
      dequeue(owner, guide);
    }
  }
}
