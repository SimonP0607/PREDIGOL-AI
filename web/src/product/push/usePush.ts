/**
 * The reader's notices on their devices, as a page uses them (plan UX, B7): the account's state (GET /me/push), what this
 * browser is (lib/push.ts: cannot, must be installed, blocked, receiving, not yet), and the two actions a tap starts -
 * receiving here and stopping here. A browser whose push service gave it a new address tells the server again, quietly.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { PushState } from "@/lib/api/v1/types_push";
import {
  deviceState,
  disableOnThisDevice,
  enableOnThisDevice,
  followMovedSubscription,
  type DeviceState,
  type EnableResult,
  type PushApi,
} from "@/lib/push";
import { track } from "@/lib/track";

export const PUSH_API: PushApi = {
  subscribe: (body) => v1.subscribePush(body),
  unsubscribe: (body) => v1.unsubscribePush(body),
};

export interface PushView {
  /** GET /me/push, once read. */
  state: PushState | undefined;
  /** Notices can be offered at all: the switch on and PrediGol's key set (P12). */
  available: boolean;
  /** What this browser is - null while it is being found out. */
  device: DeviceState | null;
  loading: boolean;
  error: unknown;
  /** From the reader's tap on «Activar avisos». */
  enable: () => Promise<EnableResult>;
  /** «Desactivar en este dispositivo». */
  disable: () => Promise<void>;
  refresh: () => Promise<void>;
}

export function usePush(enabled = true): PushView {
  const qc = useQueryClient();
  const query = useQuery({ ...live.push, enabled });
  const state = query.data;
  const liveIds = useMemo(() => state?.devices.map((d) => d.id) ?? [], [state]);
  const idsKey = liveIds.join(",");
  const [device, setDevice] = useState<DeviceState | null>(null);
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(async () => {
    await qc.invalidateQueries({ queryKey: live.push.queryKey });
    setNonce((n) => n + 1);
  }, [qc]);

  useEffect(() => {
    if (!state) return;
    let gone = false;
    void deviceState(liveIds).then(async (found) => {
      if (gone) return;
      setDevice(found);
      if (found.moved) {
        try {
          await followMovedSubscription(found.moved, PUSH_API);
          void qc.invalidateQueries({ queryKey: live.push.queryKey });
        } catch {
          // the next visit tries again; the device keeps its last address until then
        }
      }
    });
    return () => {
      gone = true;
    };
    // liveIds changes with idsKey; nonce asks again after an action of this page
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, idsKey, nonce, qc]);

  // Synchronous up to the browser's question: the tap's activation must still be there when it is asked.
  const enable = useCallback((): Promise<EnableResult> => {
    const key = state?.public_key;
    if (!key) return Promise.resolve({ ok: false, reason: "unsupported" });
    return enableOnThisDevice(key, PUSH_API).then(async (result) => {
      if (result.ok) track("notification_enabled", { channel: "push", category: "device" });
      await refresh();
      return result;
    });
  }, [state, refresh]);

  const disable = useCallback(async () => {
    await disableOnThisDevice(PUSH_API);
    track("notification_disabled", { channel: "push", category: "device" });
    await refresh();
  }, [refresh]);

  return {
    state,
    available: Boolean(state?.available && state.public_key),
    device,
    loading: query.isPending,
    error: query.error,
    enable,
    disable,
    refresh,
  };
}
