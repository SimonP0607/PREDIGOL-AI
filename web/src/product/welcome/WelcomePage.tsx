/**
 * /welcome (plan UX, A13; sections 19 and 20): the account's welcome, once, right after the consents - then Inicio. Two
 * moments and nothing more:
 *
 *   «Tu fútbol»        the leagues and teams the reader follows, the ones suggested for Colombia already ticked; saving
 *                      makes them the reader's, skipping keeps the suggested ones (labelled as suggested)
 *   «Qué es PrediGol»  three sentences, the way to «Cómo le va a PrediGol» when it is open, and the optional tour
 *                      - a new account only: an account from before A13 sees the favourites alone
 *
 * Every step can be skipped; the welcome is recorded as done either way (POST /me/onboarding) and never shown again.
 * FBI_ONBOARDING=0 sends every account straight to Inicio (the server says no welcome is owed). The product's analytics
 * count it: onboarding_started, onboarding_step_skipped, onboarding_completed {skipped} and each favourite added or removed.
 */
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { BarChart3, BookOpen, ChevronRight, Compass, Loader2, Sparkles } from "lucide-react";
import { BrandLogo } from "@/components/brand/Brand";
import { Disclaimer } from "@/components/system/Disclaimer";
import { LanguageSwitch } from "@/components/layout/HeaderControls";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { WelcomeStep } from "@/lib/api/v1/types_favorites";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { Card, ErrorState } from "@/product/shared/States";
import { trackChanges } from "@/product/favorites/analytics";
import { FavoritesPicker } from "@/product/favorites/FavoritesPicker";
import {
  beforeOf,
  bodyOf,
  changes,
  choiceOf,
  limitsOf,
  type Choice,
} from "@/product/favorites/model";
import { useOnboardingState, welcomeSteps } from "@/product/favorites/onboarding";
import { HOW_PATH } from "@/product/help/howItWorks";
import { useTour } from "@/product/tour/steps";
import { afterWelcome } from "./next";

const PRIMARY =
  "inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50";
const SECONDARY =
  "inline-flex min-h-11 items-center justify-center rounded-md border border-border-strong px-4 py-2 text-sm font-medium hover:bg-elevated disabled:opacity-50";

function Football({
  last,
  older,
  onDone,
  onSkip,
}: {
  last: boolean;
  older: boolean;
  onDone: () => void;
  onSkip: () => void;
}) {
  const qc = useQueryClient();
  const favorites = useQuery(live.favorites);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(false);
  useEffect(() => {
    if (favorites.data && choice === null) setChoice(choiceOf(favorites.data));
  }, [favorites.data, choice]);

  async function save() {
    if (!choice || !favorites.data || busy) return;
    setBusy(true);
    setFailure(false);
    try {
      const saved = await v1.saveFavorites(bodyOf(choice));
      const { added, removed } = changes(beforeOf(favorites.data), choiceOf(saved));
      trackChanges({ added, removed });
      qc.setQueryData(live.favorites.queryKey, saved);
      void qc.invalidateQueries({ queryKey: ["v1", "today"] });
      void qc.invalidateQueries({ queryKey: ["me", "personal"] });
      onDone();
    } catch {
      setFailure(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1 className="flex items-center gap-2 font-display text-xl font-semibold">
        <Sparkles aria-hidden className="h-5 w-5 text-primary" />
        {t("onboarding.welcome.football.title")}
      </h1>
      <p className="text-sm leading-relaxed text-muted-foreground">
        {t(older ? "onboarding.welcome.football.introOlder" : "onboarding.welcome.football.intro")}
      </p>
      {favorites.isError ? (
        <ErrorState error={favorites.error} onRetry={() => void favorites.refetch()} />
      ) : choice === null ? (
        <p aria-busy="true" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          {t("onboarding.picker.loading")}
        </p>
      ) : (
        <FavoritesPicker choice={choice} limits={limitsOf(favorites.data)} onChange={setChoice} />
      )}
      {failure ? (
        <p role="alert" className="text-sm text-negative" data-testid="welcome-error">
          {t("onboarding.welcome.failed")}
        </p>
      ) : null}
      <div className="sticky bottom-0 -mx-5 -mb-5 flex flex-col gap-2 rounded-b-xl border-t border-border bg-card/95 px-5 py-3 backdrop-blur sm:static sm:mx-0 sm:mb-0 sm:flex-row sm:items-center sm:rounded-none sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
        <button
          type="button"
          onClick={() => void save()}
          disabled={!choice || busy}
          data-testid="welcome-save"
          className={PRIMARY}
        >
          {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          {t(last ? "onboarding.welcome.football.saveLast" : "onboarding.welcome.football.save")}
        </button>
        <button
          type="button"
          onClick={onSkip}
          disabled={busy}
          data-testid="welcome-skip"
          className={SECONDARY}
        >
          {t("onboarding.welcome.football.skip")}
        </button>
      </div>
      <p className="text-caption text-muted-foreground">
        {t("onboarding.welcome.football.skipHelp")}
      </p>
    </>
  );
}

function About({
  transparency,
  busy,
  onEnter,
  onTransparency,
  onHow,
  onTour,
}: {
  transparency: boolean;
  busy: boolean;
  onEnter: (skipped: boolean) => void;
  onTransparency: () => void;
  onHow: () => void;
  onTour: () => void;
}) {
  return (
    <>
      <h1 className="flex items-center gap-2 font-display text-xl font-semibold">
        <Sparkles aria-hidden className="h-5 w-5 text-primary" />
        {t("onboarding.welcome.about.title")}
      </h1>
      <p className="text-[0.9375rem] leading-relaxed" data-testid="welcome-what">
        {t("common.what")}
      </p>
      <ul className="space-y-3" data-testid="welcome-about">
        {(["analysis", "picks", "transparency"] as const).map((k) => (
          <li key={k} className="flex items-start gap-2.5 text-[0.9375rem] leading-relaxed">
            <ChevronRight aria-hidden className="mt-1 h-4 w-4 shrink-0 text-gold" />
            <span>
              {t(`onboarding.welcome.about.${k}`)}
              {k === "transparency" && transparency ? (
                <>
                  {" "}
                  <button
                    type="button"
                    data-testid="welcome-transparency"
                    disabled={busy}
                    className="tap-y relative inline-flex items-center gap-1 font-medium text-primary hover:underline"
                    onClick={onTransparency}
                  >
                    <BarChart3 aria-hidden className="h-3.5 w-3.5" />
                    {t("onboarding.welcome.about.transparencyLink")}
                  </button>
                </>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
      <p>
        <button
          type="button"
          data-testid="welcome-how"
          disabled={busy}
          className="tap-y relative inline-flex items-center gap-1 text-[0.9375rem] font-medium text-primary hover:underline"
          onClick={onHow}
        >
          <BookOpen aria-hidden className="h-3.5 w-3.5" />
          {t("onboarding.welcome.about.howItWorks")}
        </button>
      </p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <button
          type="button"
          onClick={() => onEnter(false)}
          disabled={busy}
          data-testid="welcome-enter"
          className={PRIMARY}
        >
          {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          {t("onboarding.welcome.about.enter")}
        </button>
        <button
          type="button"
          onClick={onTour}
          disabled={busy}
          data-testid="welcome-tour"
          className={SECONDARY}
        >
          <Compass aria-hidden className="mr-2 h-4 w-4 text-gold" />
          {t("onboarding.welcome.about.tour")}
        </button>
        <button
          type="button"
          onClick={() => onEnter(true)}
          disabled={busy}
          data-testid="welcome-about-skip"
          className="inline-flex min-h-11 items-center justify-center px-3 text-sm text-muted-foreground underline-offset-2 hover:underline"
        >
          {t("onboarding.welcome.about.skip")}
        </button>
      </div>
    </>
  );
}

export function WelcomePage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const tour = useTour();
  const record = useOnboardingState();
  const searchStr = useRouterState({ select: (s) => s.location.searchStr });
  const steps = welcomeSteps(auth.user);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const skipped = useRef(0);
  const started = useRef(false);
  const finishing = useRef(false);
  const due = Boolean(auth.user?.welcome_due);
  useEffect(() => {
    if (!due) return;
    if (started.current) return;
    started.current = true;
    track("onboarding_started", {});
  }, [due]);
  // Nothing owed (done already, the owner's account, or FBI_ONBOARDING=0): Inicio - unless this page is finishing it.
  useEffect(() => {
    if (!due && !finishing.current) void navigate({ to: "/home", replace: true });
  }, [due, navigate]);

  const step: WelcomeStep = steps[index] ?? "football";
  const last = index >= steps.length - 1;

  async function finish(then: "next" | "tour" | "transparency" | "how") {
    setBusy(true);
    setFailure(null);
    finishing.current = true;
    try {
      const state = await v1.completeOnboarding();
      track("onboarding_completed", { skipped: skipped.current });
      record(state);
      if (then === "tour") tour.start();
      else
        void navigate({
          to: (then === "transparency"
            ? "/transparency"
            : then === "how"
              ? HOW_PATH
              : afterWelcome(searchStr)) as never,
          replace: true,
        });
    } catch (err) {
      finishing.current = false;
      setFailure(err);
      setBusy(false);
    }
  }

  function advance() {
    if (last) void finish("next");
    else setIndex((i) => i + 1);
  }

  function skip(name: WelcomeStep) {
    skipped.current += 1;
    track("onboarding_step_skipped", { step: name });
    advance();
  }

  return (
    <div className="min-h-screen bg-background" data-testid="welcome" data-step={step}>
      <header className="safe-top border-b border-border">
        <div className="px-safe mx-auto flex h-14 max-w-3xl items-center gap-3">
          <BrandLogo size={30} tagline={t("common.tagline")} />
          <LanguageSwitch className="ml-auto" />
        </div>
      </header>
      <main className="px-safe mx-auto w-full max-w-3xl py-6">
        <Card className="space-y-4 p-5">
          {steps.length > 1 ? (
            <p
              className="text-caption font-medium uppercase tracking-[0.06em] text-muted-foreground"
              data-testid="welcome-progress"
            >
              {t("onboarding.welcome.step", { n: index + 1, total: steps.length })}
            </p>
          ) : null}
          {step === "football" ? (
            <Football
              last={last}
              older={!steps.includes("about")}
              onDone={advance}
              onSkip={() => skip("football")}
            />
          ) : (
            <About
              transparency={Boolean(auth.user?.transparency)}
              busy={busy}
              onEnter={(skippedIt) => {
                if (skippedIt) {
                  skipped.current += 1;
                  track("onboarding_step_skipped", { step: "about" });
                }
                void finish("next");
              }}
              onTransparency={() => void finish("transparency")}
              onHow={() => void finish("how")}
              onTour={() => void finish("tour")}
            />
          )}
          {failure ? <ErrorState error={failure} onRetry={() => void finish("next")} /> : null}
        </Card>
      </main>
      <footer className="px-safe mx-auto max-w-3xl pb-[calc(2rem+env(safe-area-inset-bottom))] text-center text-caption text-subtle-foreground">
        <Disclaimer />
      </footer>
    </div>
  );
}
