/**
 * Saves a value the moment it changes, one request at a time (plan de Inicio, 3.4): what is changed while a save is still
 * going is sent after it - only the last of it, since each save replaces the whole choice - and a failure keeps the value
 * that was not saved for a retry. Pure of the page: the sending and the reports are arguments.
 */
export interface SaverHooks<R> {
  onStart: () => void;
  /** Each answer, in order. */
  onSaved: (answer: R) => void;
  /** Nothing left to send: everything the reader changed is saved. */
  onIdle: () => void;
  onFail: () => void;
}

export interface LatestSaver<T> {
  push: (value: T) => void;
  /** Sends again what a failure left unsaved. */
  retry: () => void;
}

export function createSaver<T, R>(
  send: (value: T) => Promise<R>,
  hooks: SaverHooks<R>,
): LatestSaver<T> {
  let pending: { value: T } | null = null;
  let running = false;

  async function run(): Promise<void> {
    if (running) return;
    running = true;
    hooks.onStart();
    try {
      while (pending) {
        const { value } = pending;
        pending = null;
        try {
          hooks.onSaved(await send(value));
        } catch {
          // What failed is still the latest, unless the reader has changed it since.
          pending ??= { value };
          hooks.onFail();
          return;
        }
      }
      hooks.onIdle();
    } finally {
      running = false;
    }
  }

  return {
    push(value) {
      pending = { value };
      void run();
    },
    retry() {
      void run();
    },
  };
}
