/**
 * The left half of the sign-in at a desk (plan maestro UX/UI 2026, sheet A02): the centre circle under the floodlights,
 * the crest, what PrediGol is in one sentence and its three promises. Decoration and words only - no figure, no claim of
 * results. Hidden under 1024 px, where the sign-in is one column.
 */
import { CalendarDays, Target, TrendingUp } from "lucide-react";
import { BrandCrest } from "@/components/brand/Brand";
import { t } from "@/lib/i18n";

const PROMISES = [
  { key: "matches", icon: CalendarDays, tone: "text-primary" },
  { key: "picks", icon: Target, tone: "text-gold" },
  { key: "odds", icon: TrendingUp, tone: "text-primary" },
] as const;

export function LoginScene() {
  return (
    <aside
      data-testid="login-scene"
      className="surface-pitch relative hidden w-[57%] max-w-[51.25rem] shrink-0 flex-col items-center justify-center overflow-hidden border-y-0 border-l-0 px-10 py-12 lg:flex"
    >
      <span aria-hidden className="scene scene-kickoff" style={{ height: "100%" }} />
      <div className="relative flex w-full max-w-xl flex-col items-center text-center">
        <BrandCrest size={168} />
        <p className="mt-6 text-overline text-gold">{t("auth.scene.overline")}</p>
        <p className="mt-2 font-display text-[2rem] font-bold leading-tight tracking-tight text-balance xl:text-[2.375rem]">
          {t("auth.subtitle")}
        </p>
        <ul className="mt-10 grid w-full grid-cols-3 gap-3 text-left">
          {PROMISES.map(({ key, icon: Icon, tone }) => (
            <li key={key} className="card-surface rounded-card p-4">
              <span className="flex h-9 w-9 items-center justify-center rounded-field bg-elevated">
                <Icon aria-hidden className={`h-[1.125rem] w-[1.125rem] ${tone}`} />
              </span>
              <p className="mt-3 text-sm font-semibold">{t(`auth.scene.${key}.title`)}</p>
              <p className="mt-1 text-caption text-muted-foreground">
                {t(`auth.scene.${key}.body`)}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
