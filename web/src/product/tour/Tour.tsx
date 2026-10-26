/**
 * The optional four-step tour (plan UX, A13; section 20: «Recorrido opcional de 4 pasos desde Ayuda»): Inicio, a match's
 * centre, a pick with its state and Mis picks. Started only by the reader - from the welcome's «Qué es PrediGol» or from
 * the help - never on its own: a small card at the foot of the page (over nothing the reader needs: it leaves the tab bar
 * and the parlay button clear), «Siguiente» to the next page, closed at any step. It keeps nothing: a reload ends it.
 */
import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Compass, X } from "lucide-react";
import type { Envelope } from "@/lib/api/v1/types";
import type { Today } from "@/lib/api/v1/types_today";
import { t } from "@/lib/i18n";
import { TOUR_STEPS, TourContext, stepPath, useTour, type TourStep, type TourValue } from "./steps";

export function TourProvider({ children }: { children: ReactNode }) {
  const [step, setStep] = useState<TourStep | null>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const go = useCallback(
    (to: TourStep) => {
      const today = qc.getQueryData<Envelope<Today>>(["v1", "today"])?.data;
      setStep(to);
      void navigate({ to: stepPath(to, today) as never });
    },
    [navigate, qc],
  );
  const value = useMemo<TourValue>(
    () => ({
      step,
      start: () => go("home"),
      next: () => {
        const at = step ? TOUR_STEPS.indexOf(step) : -1;
        const following = TOUR_STEPS[at + 1];
        if (following) go(following);
        else setStep(null);
      },
      close: () => setStep(null),
    }),
    [step, go],
  );
  return <TourContext.Provider value={value}>{children}</TourContext.Provider>;
}

/** The step's card, at the foot of the page: above the tab bar and the parlay button on a phone, bottom left from 1024 px. */
export function TourCard() {
  const tour = useTour();
  if (!tour.step) return null;
  const n = TOUR_STEPS.indexOf(tour.step) + 1;
  const last = n === TOUR_STEPS.length;
  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-labelledby="tour-title"
      data-testid="tour-card"
      data-step={tour.step}
      className="fixed inset-x-3 bottom-[calc(8.5rem+env(safe-area-inset-bottom))] z-40 mx-auto max-w-md rounded-xl border border-gold/40 bg-card p-4 shadow-lg short:bottom-[calc(7rem+env(safe-area-inset-bottom))] lg:bottom-6 lg:left-6 lg:right-auto lg:mx-0 lg:w-[26rem]"
    >
      <div className="flex items-start gap-3">
        <Compass aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-gold" />
        <div className="min-w-0 flex-1">
          <p className="text-caption font-medium uppercase tracking-[0.06em] text-muted-foreground">
            {t("onboarding.tour.step", { n, total: TOUR_STEPS.length })}
          </p>
          <h2 id="tour-title" className="mt-0.5 font-display text-base font-semibold">
            {t(`onboarding.tour.${tour.step}.title`)}
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-foreground/90">
            {t(`onboarding.tour.${tour.step}.body`)}
          </p>
        </div>
        <button
          type="button"
          aria-label={t("onboarding.tour.close")}
          onClick={tour.close}
          data-testid="tour-close"
          className="tap relative -mr-1 -mt-1 rounded-md p-1.5 text-muted-foreground hover:bg-elevated"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={tour.next}
          data-testid="tour-next"
          className="inline-flex min-h-11 items-center rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground"
        >
          {last ? t("onboarding.tour.done") : t("onboarding.tour.next")}
        </button>
      </div>
    </div>
  );
}

/** «Hacer el recorrido»: where the help offers it. */
export function TourStart({ className }: { className?: string }) {
  const tour = useTour();
  if (!tour.available) return null;
  return (
    <div className={className} data-testid="tour-offer">
      <button
        type="button"
        onClick={tour.start}
        data-testid="tour-start"
        className="inline-flex min-h-11 items-center gap-2 rounded-md border border-gold/50 bg-gold-soft px-3 py-2 text-sm font-semibold text-gold-strong hover:bg-gold/15"
      >
        <Compass aria-hidden className="h-4 w-4" />
        {t("onboarding.tour.start")}
      </button>
      <p className="mt-1.5 text-caption text-muted-foreground">{t("onboarding.tour.startHelp")}</p>
    </div>
  );
}
