/**
 * How PrediGol is shown (plan maestro UX/UI 2026, decision 8; sheet U03): the clock, the way a price is written, fewer
 * animations and the view Inicio opens on. Each control saves on its own (PATCH /auth/me/preferences) and changes only
 * what it says: a price is still stored, computed and sent in decimal, an hour is still the same hour.
 */
import { useState } from "react";
import { Segmented } from "@/components/ui/segmented";
import { Switch } from "@/components/ui/switch";
import type { PreferencesIn } from "@/lib/api/v1/types_auth";
import { useAuth } from "@/lib/auth/AuthProvider";
import { DEFAULT_DISPLAY, type Display } from "@/lib/display";
import { t } from "@/lib/i18n";
import { formatOdds } from "@/lib/i18n/format";

type HomeChoice = "auto" | "mine" | "all";

export function DisplaySettings() {
  const auth = useAuth();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const shown: Display = { ...DEFAULT_DISPLAY, ...(auth.user?.display ?? {}) };

  async function save(prefs: PreferencesIn) {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      await auth.updatePreferences(prefs);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5" data-testid="display-settings" aria-busy={busy}>
      <div className="space-y-2">
        <p className="text-sm font-medium">{t("profile.display.time")}</p>
        <Segmented<Display["time_format"]>
          value={shown.time_format}
          onChange={(v) => void save({ time_format: v })}
          label={t("profile.display.time")}
          testId="display-time"
          options={[
            { value: "24h", label: t("profile.display.time24") },
            { value: "12h", label: t("profile.display.time12") },
          ]}
        />
      </div>
      <div className="space-y-2">
        <p className="text-sm font-medium">{t("profile.display.odds")}</p>
        <Segmented<Display["odds_format"]>
          value={shown.odds_format}
          onChange={(v) => void save({ odds_format: v })}
          label={t("profile.display.odds")}
          testId="display-odds"
          options={[
            { value: "decimal", label: t("profile.display.oddsDecimal") },
            { value: "american", label: t("profile.display.oddsAmerican") },
            { value: "fractional", label: t("profile.display.oddsFractional") },
          ]}
        />
        <p className="numeric text-xs text-muted-foreground" data-testid="display-odds-example">
          {t("profile.display.oddsExample", {
            decimal: formatOdds(2.05, "decimal"),
            american: formatOdds(2.05, "american"),
            fractional: formatOdds(2.05, "fractional"),
          })}
        </p>
        <p className="text-xs text-muted-foreground">{t("profile.display.oddsHelp")}</p>
      </div>
      <div className="space-y-2">
        <p className="text-sm font-medium">{t("profile.display.home")}</p>
        <Segmented<HomeChoice>
          value={shown.home_default ?? "auto"}
          onChange={(v) => void save({ home_default: v })}
          label={t("profile.display.home")}
          testId="display-home"
          options={[
            { value: "auto", label: t("profile.display.homeAuto") },
            { value: "mine", label: t("home.layers.forYou") },
            { value: "all", label: t("home.view.all") },
          ]}
        />
        <p className="text-xs text-muted-foreground">{t("profile.display.homeHelp")}</p>
      </div>
      <label className="flex min-h-11 items-center justify-between gap-4">
        <span>
          <span className="block text-sm font-medium">{t("profile.display.motion")}</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">
            {t("profile.display.motionHelp")}
          </span>
        </span>
        <Switch
          checked={shown.reduce_motion}
          onCheckedChange={(v) => void save({ reduce_motion: v })}
          data-testid="display-motion"
        />
      </label>
      {failed ? (
        <p role="alert" className="text-sm text-negative" data-testid="display-error">
          {t("profile.display.failed")}
        </p>
      ) : null}
    </div>
  );
}
