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
import { BarChart3, BookOpen, ChevronRight, Compass, Loader2 } from "lucide-react";
import { BrandLogo } from "@/components/brand/Brand";
import { Disclaimer } from "@/components/system/Disclaimer";
import { LanguageSwitch } from "@/components/layout/HeaderControls";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { WelcomeStep } from "@/lib/api/v1/types_favorites";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { track } from "@/lib/track";
import { buttonVariants } from "@/components/ui/button";
import { ErrorState } from "@/product/shared/States";
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
import { useGuides } from "@/product/guides/context";
import { afterWelcome, welcomeExit } from "./next";

const PRIMARY = buttonVariants({ variant: "primary", size: "lg" });
const SECONDARY = buttonVariants({ variant: "secondary", size: "lg" });

function Football({
  last,
  older,
  onDone,
  onBusy,
}: {
  last: boolean;
  older: boolean;
  onDone: () => void;
  /** Saving: «Saltar», at the top of the page, waits with it. */
  onBusy: (busy: boolean) => void;
}) {
  const qc = useQueryClient();
  const favorites = useQuery(live.favorites);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(false);
  useEffect(() => onBusy(busy), [busy, onBusy]);
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
      <h1 className="text-display text-balance">{t("onboarding.welcome.football.title")}</h1>
      <p className="text-[0.9375rem] leading-relaxed text-muted-foreground">
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
      {/* the sheet's foot (A09): the one action stays in reach on a phone while the lists scroll under it */}
      <div className="sticky bottom-0 z-10 -mx-4 flex flex-col gap-2 border-t border-border bg-background/95 px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3 backdrop-blur sm:static sm:mx-0 sm:flex-row sm:items-center sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
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
  /** Absent when the account is shown no guide (FBI_GUIDES=0): the button is not offered. */
  onTour?: (() => void) | undefined;
}) {
  return (
    <>
      <h1 className="text-display text-balance">{t("onboarding.welcome.about.title")}</h1>
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
        {onTour ? (
          <button
            type="button"
            onClick={onTour}
            disabled={busy}
            data-testid="welcome-tour"
            className={SECONDARY}
          >
            <Compass aria-hidden className="text-gold" />
            {t("onboarding.welcome.about.tour")}
          </button>
        ) : null}
        <button
          type="button"
          onClick={() => onEnter(true)}
          disabled={busy}
          data-testid="welcome-about-skip"
          className={buttonVariants({ variant: "text", size: "lg" })}
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
  const guides = useGuides();
  const record = useOnboardingState();
  const searchStr = useRouterState({ select: (s) => s.location.searchStr });
  const steps = welcomeSteps(auth.user);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  // where to go once the account itself says the welcome is done (UX-081): not at the API's answer, a moment before the gate knows
  const [leaving, setLeaving] = useState<string | null>(null);
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
  // The welcome was recorded as done: leave it once the account the gate reads agrees (same render), never before.
  const exit = welcomeExit(due, leaving);
  useEffect(() => {
    if (exit !== null) void navigate({ to: exit as never, replace: true });
  }, [exit, navigate]);

  const step: WelcomeStep = steps[index] ?? "football";
  const name = (auth.user?.display_name ?? "").trim().split(/\s+/)[0] ?? "";
  const last = index >= steps.length - 1;

  async function finish(then: "next" | "tour" | "transparency" | "how") {
    setBusy(true);
    setFailure(null);
    finishing.current = true;
    try {
      const state = await v1.completeOnboarding();
      track("onboarding_completed", { skipped: skipped.current });
      record(state);
      if (then === "tour") guides.request("general", 1);
      else
        setLeaving(
          then === "transparency"
            ? "/transparency"
            : then === "how"
              ? HOW_PATH
              : afterWelcome(searchStr),
        );
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
    <div
      className="pitch-glow relative min-h-screen bg-background"
      data-testid="welcome"
      data-step={step}
    >
      <header className="safe-top border-b border-border">
        <div className="px-safe mx-auto flex h-14 max-w-3xl items-center gap-3">
          <BrandLogo size={30} tagline={t("common.tagline")} />
          <LanguageSwitch className="ml-auto" />
          {step === "football" ? (
            <button
              type="button"
              onClick={() => skip("football")}
              disabled={saving || busy}
              data-testid="welcome-skip"
              className={buttonVariants({ variant: "text", size: "sm" })}
            >
              {t("onboarding.welcome.football.skip")}
            </button>
          ) : null}
        </div>
      </header>
      <main className="px-safe mx-auto w-full max-w-3xl py-6">
        <div
          className={cn(
            "space-y-4",
            step === "about" && "card-surface rounded-feature p-5 shadow-xl",
          )}
        >
          {name || steps.length > 1 ? (
            <p className="truncate text-overline text-gold" data-testid="welcome-overline">
              {name ? t("onboarding.welcome.greeting", { name }) : null}
              {name && steps.length > 1 ? " · " : null}
              {steps.length > 1 ? (
                <span data-testid="welcome-progress">
                  {t("onboarding.welcome.step", { n: index + 1, total: steps.length })}
                </span>
              ) : null}
            </p>
          ) : null}
          {step === "football" ? (
            <Football
              last={last}
              older={!steps.includes("about")}
              onDone={advance}
              onBusy={setSaving}
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
              onTour={
                auth.user?.guides_on === false || auth.user?.membership?.limited
                  ? undefined
                  : () => void finish("tour")
              }
            />
          )}
          {failure ? <ErrorState error={failure} onRetry={() => void finish("next")} /> : null}
        </div>
      </main>
      <footer className="px-safe mx-auto max-w-3xl pb-[calc(2rem+env(safe-area-inset-bottom))] text-center text-caption text-subtle-foreground">
        <Disclaimer />
      </footer>
    </div>
  );
}
