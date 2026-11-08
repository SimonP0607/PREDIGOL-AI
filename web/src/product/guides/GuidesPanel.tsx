/**
 * Ayuda > Guías (plan UX-051): every guide the reader can be shown, with what they did with it, to see it or repeat it; and
 * the reader's own switch for the guide of each screen on the first visit. It shows nothing outside the provider, with the
 * guides off (FBI_GUIDES=0) or for the owner's account (guides are for readers).
 */
import { useId, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Compass } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { v1 } from "@/lib/api/v1/client";
import type { Me } from "@/lib/api/v1/types_auth";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { useGuides } from "./context";
import { GUIDE_LIST, launchable } from "./registry";

export function GuidesPanel({ className }: { className?: string }) {
  const guides = useGuides();
  const user = useAuth().user;
  const qc = useQueryClient();
  const labelId = useId();
  const [failed, setFailed] = useState(false);
  if (!guides.available || !user || user.role !== "USER" || user.guides_on === false) return null;
  // every guide, Inicio's own too (UX-070): the general tour covers it only for what comes up by itself
  const list = GUIDE_LIST.filter(launchable);
  if (list.length === 0) return null;
  // the switch only means something when there is a guide of a screen to show by itself
  const hasScreenGuides = list.some((g) => g.key !== "general" && !g.mandatory);
  const auto = user.guides_auto !== false;

  async function change(value: boolean) {
    setFailed(false);
    const before = qc.getQueryData<Me | null>(["auth", "me"]);
    qc.setQueryData<Me | null>(["auth", "me"], (me) => (me ? { ...me, guides_auto: value } : me));
    try {
      await v1.updatePreferences({ guides_auto: value });
    } catch {
      qc.setQueryData<Me | null>(["auth", "me"], before ?? null);
      setFailed(true);
    }
  }

  return (
    <section
      id="guides"
      aria-labelledby="help-guides"
      className={className}
      data-testid="guides-panel"
    >
      <h2
        id="help-guides"
        className="flex items-center gap-2 font-display text-lg font-semibold tracking-tight"
      >
        <Compass aria-hidden className="h-4 w-4 text-gold" />
        {t("guides.panel.title")}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">{t("guides.panel.intro")}</p>
      <ul className="mt-3 divide-y divide-border rounded-lg border border-border">
        {list.map((def) => {
          const state = guides.seen(def.key)?.status ?? "pending";
          const done = state === "completed" || state === "skipped";
          return (
            <li
              key={def.key}
              className="flex items-center justify-between gap-3 px-3 py-2"
              data-testid={`guide-row-${def.key}`}
            >
              <div className="min-w-0">
                <p className="text-sm font-medium">{t(`guides.names.${def.key}`)}</p>
                <p className="text-caption text-muted-foreground">
                  {t(`guides.panel.state.${state}`)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => guides.request(def.key, 0)}
                data-testid={`guide-open-${def.key}`}
                className="inline-flex min-h-11 shrink-0 items-center rounded-md border border-gold/50 bg-gold-soft px-3 py-2 text-sm font-semibold text-gold-strong hover:bg-gold/15"
              >
                {done ? t("guides.panel.repeat") : t("guides.panel.view")}
              </button>
            </li>
          );
        })}
      </ul>
      {hasScreenGuides ? (
        <div className="mt-3 flex min-h-11 items-center justify-between gap-3">
          <span id={labelId} className="text-sm">
            {t("guides.panel.auto")}
          </span>
          <Switch
            checked={auto}
            onCheckedChange={(value) => void change(value)}
            aria-labelledby={labelId}
            data-testid="guides-auto"
          />
        </div>
      ) : null}
      {failed ? (
        <p role="alert" className="text-caption text-destructive" data-testid="guides-auto-failed">
          {t("guides.panel.autoFailed")}
        </p>
      ) : null}
    </section>
  );
}
