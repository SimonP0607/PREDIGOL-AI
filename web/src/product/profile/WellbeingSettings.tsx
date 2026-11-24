/**
 * «Solo fútbol» and the voluntary pause (plan PM, PM-14-07; FBI_WELLBEING): two choices of the reader's own, in Perfil > Preferencias.
 * Both end the same way - no price, pick or parlay anywhere - and both are saved on the server (PUT /me/wellbeing), where the calls
 * that are a price are refused for them. A running pause runs to its date: the page says so before it is asked for. Nothing is drawn
 * while the owner has not opened the choice.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { Switch } from "@/components/ui/switch";
import { useWellbeing } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";

const PAUSES = [1, 7, 30] as const;

/** The choices, or nothing while the owner has not opened them. */
export function WellbeingSettings() {
  return useWellbeing().available ? <WellbeingForm /> : null;
}

function WellbeingForm() {
  const w = useWellbeing();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const paused = w.pausedUntil !== null;

  async function save(body: { football_only?: boolean; pause_days?: 0 | 1 | 7 | 30 }) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await v1.putWellbeing(body);
      await client.invalidateQueries({ queryKey: ["auth", "me"] });
    } catch (e) {
      setError(
        e instanceof LiveApiError && e.code === "pause_running"
          ? t("profile.wellbeing.pauseRunning")
          : t("profile.wellbeing.failed"),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4" data-testid="wellbeing-settings" aria-busy={busy}>
      <p className="text-xs text-muted-foreground">{t("profile.wellbeing.intro")}</p>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium" id="wellbeing-mode-label">
            {t("profile.wellbeing.mode")}
          </p>
          <p className="text-xs text-muted-foreground">{t("profile.wellbeing.modeHelp")}</p>
        </div>
        <Switch
          checked={w.footballOnly}
          disabled={busy}
          onCheckedChange={(v) => void save({ football_only: v })}
          aria-labelledby="wellbeing-mode-label"
          data-testid="wellbeing-mode"
        />
      </div>
      <div className="space-y-2">
        <p className="text-sm font-medium">{t("profile.wellbeing.pause")}</p>
        {paused ? (
          <p className="text-sm" data-testid="wellbeing-paused">
            {t("profile.wellbeing.pausedUntil", { date: formatDateTime(w.pausedUntil!) })}
            {w.canLift ? "" : ` ${t("profile.wellbeing.noCut")}`}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">{t("profile.wellbeing.pauseHelp")}</p>
        )}
        <div className="flex flex-wrap gap-2">
          {PAUSES.map((days) => (
            <button
              key={days}
              type="button"
              disabled={busy}
              onClick={() => void save({ pause_days: days })}
              data-testid={`wellbeing-pause-${days}`}
              className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-3 py-2 text-sm font-medium hover:bg-elevated disabled:opacity-60"
            >
              {t(paused ? "profile.wellbeing.extend" : "profile.wellbeing.start", { days })}
            </button>
          ))}
          {paused && w.canLift ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void save({ pause_days: 0 })}
              data-testid="wellbeing-lift"
              className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-3 py-2 text-sm font-medium hover:bg-elevated disabled:opacity-60"
            >
              {t("profile.wellbeing.lift")}
            </button>
          ) : null}
        </div>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-negative" data-testid="wellbeing-error">
          {error}
        </p>
      ) : null}
    </div>
  );
}
