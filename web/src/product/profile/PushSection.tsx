/**
 * The notices on the reader's devices, in their profile's «Notificaciones» (plan UX, B7; sections 21, 34 and 35: «email
 * y push por categoría, horas silenciosas y estado del permiso por dispositivo»; «el estado del permiso de cada
 * dispositivo, en el perfil, con cómo reactivarlo»; «se apagan en un toque desde el perfil»).
 *
 * Only while the owner made notices available (FBI_PUSH and PrediGol's key, P12): until then nothing here says they
 * exist. This browser first - receiving, not yet, blocked (and how to allow it), cannot, or an iPhone in Safari (how to
 * install PrediGol) -; then the four categories, the rules (quiet hours and the daily ceiling), the account's devices
 * with «Quitar», and a test notice.
 *
 * PushSectionView draws it from what it is given (a test renders it without a browser); PushSection acts.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { BellRing, Loader2, Send, Smartphone } from "lucide-react";
import { toast } from "sonner";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { PushCategory, PushDevice, PushState } from "@/lib/api/v1/types_push";
import { t } from "@/lib/i18n";
import type { DeviceStatus } from "@/lib/push";
import { formatRelative } from "@/lib/time";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import { InstallGuide } from "@/product/push/InstallGuide";
import { usePush } from "@/product/push/usePush";
import { errorMessage } from "@/product/shared/States";

const CATEGORIES: readonly PushCategory[] = ["result", "lineup", "digest", "account"];

function deviceName(d: PushDevice): string {
  return t("push.profile.device", {
    browser: t(`push.profile.families.${d.family}`),
    system: t(`push.profile.systems.${d.system}`),
  });
}

function Switch({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "relative inline-flex h-6 w-11 items-center rounded-full border-2 border-transparent transition-colors",
        on ? "bg-primary" : "bg-input",
      )}
    >
      <span
        className={cn(
          "block h-5 w-5 rounded-full bg-background shadow transition-transform",
          on ? "translate-x-5" : "translate-x-0",
        )}
      />
    </span>
  );
}

const BUTTON =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-4 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";

export function PushSectionView({
  state,
  here,
  hereId,
  busy,
  failure,
  onEnable,
  onDisable,
  onToggle,
  onRemove,
  onTest,
}: {
  state: PushState;
  /** This browser; null while it is being found out. */
  here: DeviceStatus | null;
  /** The account's device this browser is. */
  hereId: number | null;
  /** What is being done: "enable", "disable", "test", a category or "device:<id>". */
  busy: string | null;
  failure: string | null;
  onEnable: () => void;
  onDisable: () => void;
  onToggle: (category: PushCategory) => void;
  onRemove: (device: PushDevice) => void;
  onTest: () => void;
}) {
  return (
    <div className="space-y-3 border-t border-border pt-4" data-testid="push-section">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <BellRing aria-hidden className="h-4 w-4 text-primary" />
        {t("push.profile.title")}
      </h3>
      <p className="text-xs text-muted-foreground">
        {t("push.profile.help", {
          from: state.quiet_start,
          to: state.quiet_end,
          cap: state.daily_cap,
        })}
      </p>

      <div
        className="space-y-2 rounded-lg border border-border p-3"
        data-testid="push-here"
        data-status={here ?? "loading"}
      >
        <p className="flex items-center gap-2 text-sm font-medium">
          <Smartphone aria-hidden className="h-4 w-4 text-muted-foreground" />
          {t("push.profile.thisDevice")}
        </p>
        {here === null ? (
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
        ) : (
          <p className="text-sm text-muted-foreground" data-testid="push-here-status">
            {t(`push.profile.status.${here}`)}
          </p>
        )}
        {here === "needs_install" ? <InstallGuide platform="ios" /> : null}
        {here === "off" ? (
          <button
            type="button"
            onClick={onEnable}
            disabled={busy !== null}
            data-testid="push-enable"
            className={cn(
              BUTTON,
              "border-primary/45 bg-primary text-primary-foreground hover:bg-primary/90",
            )}
          >
            {busy === "enable" ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
            {t("push.profile.enable")}
          </button>
        ) : null}
        {here === "on" ? (
          <button
            type="button"
            onClick={onDisable}
            disabled={busy !== null}
            data-testid="push-disable"
            className={cn(BUTTON, "border-border-strong hover:bg-elevated")}
          >
            {busy === "disable" ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
            {t("push.profile.disable")}
          </button>
        ) : null}
      </div>

      <h4 className="text-sm font-medium">{t("push.profile.categories")}</h4>
      <ul className="divide-y divide-border">
        {CATEGORIES.map((category) => {
          const on = state.categories[category];
          return (
            <li key={category} data-testid={`push-category-${category}`}>
              <button
                type="button"
                role="switch"
                aria-checked={on}
                disabled={busy !== null}
                onClick={() => onToggle(category)}
                className="flex min-h-11 w-full items-center justify-between gap-3 rounded-md py-2 text-left hover:bg-elevated/60 disabled:opacity-60"
              >
                <span className="min-w-0">
                  <span className="block text-sm font-medium">
                    {t(`push.profile.category.${category}`)}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {t(`push.profile.categoryHelp.${category}`)}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {busy === category ? (
                    <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
                  ) : null}
                  <span className="sr-only">
                    {on ? t("profile.notifications.on") : t("profile.notifications.off")}
                  </span>
                  <Switch on={on} />
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <h4 className="text-sm font-medium">{t("push.profile.devices")}</h4>
      {state.devices.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="push-no-devices">
          {t("push.profile.noDevices")}
        </p>
      ) : (
        <ul className="divide-y divide-border" data-testid="push-devices">
          {state.devices.map((d) => {
            const name = deviceName(d);
            return (
              <li
                key={d.id}
                className="flex min-h-11 items-center justify-between gap-3 py-2"
                data-testid="push-device"
                data-id={d.id}
              >
                <span className="min-w-0">
                  <span className="block text-sm font-medium">
                    {name}
                    {d.id === hereId ? (
                      <span className="ml-1.5 rounded-full border border-primary/40 px-1.5 py-0.5 text-micro text-primary">
                        {t("push.profile.here")}
                      </span>
                    ) : null}
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {[
                      d.installed ? t("push.profile.installed") : null,
                      d.last_ok_at
                        ? t("push.profile.lastOk", { when: formatRelative(d.last_ok_at) })
                        : t("push.profile.never"),
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
                <button
                  type="button"
                  onClick={() => onRemove(d)}
                  disabled={busy !== null}
                  aria-label={t("push.profile.removeLabel", { device: name })}
                  data-testid="push-device-remove"
                  className={cn(BUTTON, "shrink-0 border-border-strong px-3 hover:bg-elevated")}
                >
                  {busy === `device:${d.id}` ? (
                    <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
                  ) : null}
                  {t("push.profile.remove")}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {state.devices.length > 0 ? (
        <div className="space-y-1">
          <button
            type="button"
            onClick={onTest}
            disabled={busy !== null}
            data-testid="push-test"
            className={cn(BUTTON, "border-border-strong hover:bg-elevated")}
          >
            {busy === "test" ? (
              <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
            ) : (
              <Send aria-hidden className="h-4 w-4" />
            )}
            {t("push.profile.test")}
          </button>
          <p className="text-caption text-muted-foreground">{t("push.profile.testHelp")}</p>
        </div>
      ) : null}

      {failure ? (
        <p role="alert" className="text-xs text-negative" data-testid="push-failure">
          {failure}
        </p>
      ) : null}
    </div>
  );
}

export function PushSection() {
  const qc = useQueryClient();
  const push = usePush();
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const state = push.state;
  if (!state || !push.available) return null;

  function enable() {
    setBusy("enable");
    setFailure(null);
    // the browser's question first, from this tap
    void push.enable().then((result) => {
      setBusy(null);
      if (result.ok) toast(t("push.offer.done"));
      else if (result.reason === "denied") setFailure(t("push.offer.denied"));
      else if (result.reason === "failed") {
        setFailure(result.error ? errorMessage(result.error) : t("push.offer.failed"));
      }
    });
  }

  async function act(what: string, run: () => Promise<void>) {
    setBusy(what);
    setFailure(null);
    try {
      await run();
    } catch (err) {
      setFailure(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <PushSectionView
      state={state}
      here={push.device?.status ?? null}
      hereId={push.device?.deviceId ?? null}
      busy={busy}
      failure={failure}
      onEnable={enable}
      onDisable={() => void act("disable", push.disable)}
      onToggle={(category) =>
        void act(category, async () => {
          const on = !state.categories[category];
          const categories = await v1.updatePushCategories({ [category]: on });
          qc.setQueryData(live.push.queryKey, { ...state, categories });
          track(on ? "notification_enabled" : "notification_disabled", {
            channel: "push",
            category,
          });
        })
      }
      onRemove={(device) =>
        void act(`device:${device.id}`, async () => {
          if (device.id === push.device?.deviceId) {
            await push.disable();
          } else {
            await v1.unsubscribePush({ device_id: device.id });
            track("notification_disabled", { channel: "push", category: "device" });
            await push.refresh();
          }
          toast(t("push.profile.removed"));
        })
      }
      onTest={() =>
        void act("test", async () => {
          await v1.sendTestPush();
          toast(t("push.profile.testSent"));
        })
      }
    />
  );
}
