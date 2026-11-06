/**
 * The bell of a match (plan UX, B7 and section 34: «Recordatorios propios: «Empieza en 30 minutos», configurado por el
 * cliente en la campana del partido»; «seguir y recibir son cosas distintas: la estrella sigue a un equipo; la campana
 * pide avisos»). In the header of a match that has not started and starts within 7 days, only while the owner made
 * notices available: a tap opens a sheet with 15 minutes, 30 minutes or 1 hour before, and «Quitar aviso» once it rings.
 *
 * The reminder reaches the account's devices that receive notices; when the account has none, the sheet turns them on
 * here first (the browser's question comes from that tap) - or, on an iPhone in Safari, shows how to install PrediGol,
 * and a blocked browser says how to allow it. The reminder arrives at its minute even in the quiet hours: the reader
 * asked for it.
 */
import { useId, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellRing, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { AlertMinutes, MatchAlert } from "@/lib/api/v1/types_push";
import { t } from "@/lib/i18n";
import { formatDateLong, formatTime } from "@/lib/time";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { errorMessage } from "@/product/shared/States";
import { InstallGuide } from "./InstallGuide";
import { bellOffered } from "./moments";
import { usePush } from "./usePush";

const MINUTES: readonly AlertMinutes[] = [15, 30, 60];

export function MatchBell({
  fixtureId,
  kickoffAt,
  home,
  away,
}: {
  fixtureId: number;
  kickoffAt: string;
  home: string;
  away: string;
}) {
  const auth = useAuth();
  const signedIn = auth.status === "signed-in" && (auth.user?.consents_due ?? []).length === 0;
  const push = usePush(signedIn);
  const soon = bellOffered(kickoffAt);
  const qc = useQueryClient();
  const alert = useQuery({ ...live.matchAlert(fixtureId), enabled: push.available && soon });
  const [open, setOpen] = useState(false);
  const [minutes, setMinutes] = useState<AlertMinutes>(30);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const groupId = useId();
  if (!signedIn || !push.available || !soon) return null;

  const on = alert.data?.on === true;
  const receives = (push.state?.devices.length ?? 0) > 0 || push.device?.status === "on";
  const here = push.device?.status ?? null;
  const label = on
    ? t("push.bell.on", { minutes: t(`push.bell.minutes.${alert.data?.minutes_before ?? 30}`) })
    : t("push.bell.add");

  function opened(next: boolean) {
    setOpen(next);
    setNote(null);
    if (next) setMinutes(alert.data?.minutes_before ?? 30);
  }

  function saved(value: MatchAlert) {
    qc.setQueryData(live.matchAlert(fixtureId).queryKey, value);
    void qc.invalidateQueries({ queryKey: live.meToday.queryKey }); // Home's «Tus avisos» lists the bells
    track("notification_enabled", { channel: "push", category: "reminder" });
    toast(
      t("push.bell.saved", { minutes: t(`push.bell.minutes.${value.minutes_before ?? minutes}`) }),
    );
    setOpen(false);
  }

  async function ring() {
    setBusy(true);
    setNote(null);
    try {
      saved(await v1.setMatchAlert(fixtureId, minutes));
    } catch (err) {
      setNote(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function enableAndRing() {
    setBusy(true);
    setNote(null);
    // the browser's question first, from this tap
    void push.enable().then(async (result) => {
      if (!result.ok) {
        setBusy(false);
        setNote(
          result.reason === "denied"
            ? t("push.offer.denied")
            : result.reason === "dismissed"
              ? null
              : t("push.offer.failed"),
        );
        return;
      }
      await ring();
    });
  }

  async function silence() {
    setBusy(true);
    setNote(null);
    try {
      await v1.clearMatchAlert(fixtureId);
      qc.setQueryData(live.matchAlert(fixtureId).queryKey, {
        fixture_id: fixtureId,
        on: false,
        minutes_before: null,
        kickoff_at: alert.data?.kickoff_at ?? null,
      } satisfies MatchAlert);
      void qc.invalidateQueries({ queryKey: live.meToday.queryKey });
      track("notification_disabled", { channel: "push", category: "reminder" });
      toast(t("push.bell.removed"));
      setOpen(false);
    } catch (err) {
      setNote(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const blocked = !receives && here !== "off";
  return (
    <Sheet open={open} onOpenChange={opened}>
      <SheetTrigger asChild>
        <button
          type="button"
          aria-pressed={on}
          aria-label={label}
          title={label}
          data-testid="match-bell"
          data-on={on ? "1" : "0"}
          className={cn(
            "tap relative inline-flex h-8 w-8 items-center justify-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            on
              ? "border-gold/60 bg-gold-soft text-gold-strong"
              : "border-border-strong bg-card text-muted-foreground hover:text-foreground",
          )}
        >
          {on ? (
            <BellRing aria-hidden className="h-4 w-4" />
          ) : (
            <Bell aria-hidden className="h-4 w-4" />
          )}
        </button>
      </SheetTrigger>
      <SheetContent
        side="bottom"
        closeLabel={t("common.close")}
        data-testid="match-bell-sheet"
        className="mx-auto flex max-h-[88dvh] max-w-lg flex-col gap-0 rounded-t-2xl p-0 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]"
      >
        <SheetHeader className="px-4 pb-1 pr-14 pt-4 text-left">
          <SheetTitle className="font-display text-base">{t("push.bell.title")}</SheetTitle>
          <SheetDescription className="text-caption">
            {t("push.bell.description", {
              home,
              away,
              when: `${formatDateLong(kickoffAt)} · ${formatTime(kickoffAt)}`,
            })}
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
          <fieldset aria-describedby={`${groupId}-night`}>
            <legend className="mb-2 text-sm font-medium">{t("push.bell.choose")}</legend>
            <div className="grid grid-cols-3 gap-2">
              {MINUTES.map((m) => (
                <label
                  key={m}
                  className={cn(
                    "relative flex min-h-11 cursor-pointer items-center justify-center rounded-lg border px-2 text-center text-sm font-medium transition-colors focus-within:ring-2 focus-within:ring-ring",
                    minutes === m
                      ? "border-primary/60 bg-primary/12 text-primary"
                      : "border-border-strong hover:bg-elevated",
                  )}
                  data-testid={`match-bell-${m}`}
                >
                  <input
                    type="radio"
                    name={groupId}
                    value={m}
                    checked={minutes === m}
                    onChange={() => setMinutes(m)}
                    className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
                  />
                  {t(`push.bell.minutes.${m}`)}
                </label>
              ))}
            </div>
          </fieldset>
          {receives ? (
            here === "on" ? null : (
              <p className="text-caption text-muted-foreground">{t("push.bell.elsewhere")}</p>
            )
          ) : here === "needs_install" ? (
            <InstallGuide platform="ios" />
          ) : here === "denied" || here === "unsupported" ? (
            <p className="text-sm" data-testid="match-bell-blocked">
              {t(`push.profile.status.${here}`)}
            </p>
          ) : (
            <p className="text-sm">{t("push.bell.needsDevice")}</p>
          )}
          <p id={`${groupId}-night`} className="text-caption text-muted-foreground">
            {t("push.bell.night")}
          </p>
          <p className="text-caption text-muted-foreground">{t("push.bell.following")}</p>
          {note ? (
            <p role="alert" className="text-sm text-negative" data-testid="match-bell-note">
              {note}
            </p>
          ) : null}
        </div>
        <div className="flex gap-2 border-t border-border px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3">
          {on ? (
            <button
              type="button"
              onClick={() => void silence()}
              disabled={busy}
              data-testid="match-bell-remove"
              className="min-h-11 flex-1 rounded-lg border border-border-strong px-3 text-sm font-medium transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              {t("push.bell.remove")}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => (receives ? void ring() : enableAndRing())}
            disabled={busy || blocked}
            data-testid="match-bell-save"
            className="inline-flex min-h-11 flex-[2] items-center justify-center gap-2 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          >
            {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
            {receives ? t("push.bell.save") : t("push.bell.saveEnable")}
          </button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
