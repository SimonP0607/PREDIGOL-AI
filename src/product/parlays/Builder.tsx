/**
 * The automatic parlay builder (REVIEW PREDIGOL, point 15): the user says what they are after - when the matches
 * start, how many selections, which markets and competitions, the odds of each selection and of the whole - and
 * PrediGol builds the parlay with the rule of its own parlays, explains every selection, and the user decides:
 * save it to "Mis picks", change it in "Mi parlay", or leave it. With nothing worth combining it says so and why:
 * never a padded parlay.
 *
 * A user builds from qualified picks only; the Admin Console's preview builds from shadow picks, labelled.
 */
import { useState, type FormEvent } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { RotateCcw, Wand2 } from "lucide-react";
import { t } from "@/lib/i18n";
import { localDecimalText } from "@/lib/i18n/format";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam } from "@/lib/auth/AuthProvider";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import { ChipGroup } from "@/product/picks/Controls";
import {
  BUILDER_HOURS,
  DEFAULT_BUILDER,
  formIssues,
  toBuilderQuery,
  withLegs,
  type BuilderForm,
} from "./builderForm";
import { CompetitionsPicker, Field, LegsSelect, MarketChips, OddsInput } from "./BuilderControls";
import { NoParlay, Result } from "./BuilderResult";

export function ParlayBuilder() {
  const preview = usePreviewParam();
  const [form, setForm] = useState<BuilderForm>(DEFAULT_BUILDER);
  const [asked, setAsked] = useState<ReturnType<typeof toBuilderQuery> | null>(null);
  const issues = formIssues(form);
  // What the filters can offer in the chosen window: the competitions and markets with selections that pass.
  const options = useQuery({
    ...live.builtParlay(toBuilderQuery({ ...DEFAULT_BUILDER, hours: form.hours }), preview),
    placeholderData: keepPreviousData,
  });
  const result = useQuery({
    ...live.builtParlay(asked ?? toBuilderQuery(DEFAULT_BUILDER), preview),
    enabled: asked !== null,
  });
  const competitions = options.data?.data.competitions ?? [];
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (issues.length) return;
    setAsked(toBuilderQuery(form));
  };
  const set = (patch: Partial<BuilderForm>) => setForm((f) => ({ ...f, ...patch }));
  const body = result.data?.data;

  return (
    <section
      aria-labelledby="parlay-builder-title"
      data-testid="parlay-builder"
      className="overflow-hidden rounded-xl border border-gold/30 bg-card"
    >
      <header className="px-4 pt-4 sm:px-5">
        <h2
          id="parlay-builder-title"
          className="flex items-center gap-2 font-display text-lg font-semibold tracking-tight"
        >
          <Wand2 aria-hidden className="h-5 w-5 shrink-0 text-gold" />
          {t("parlays.builder.title")}
        </h2>
        <p className="mt-0.5 text-xs text-muted-foreground">{t("parlays.builder.subtitle")}</p>
      </header>

      <form onSubmit={submit} className="space-y-4 px-4 py-4 sm:px-5" noValidate>
        <div className="grid gap-4 lg:grid-cols-2">
          <Field label={t("parlays.builder.window")}>
            <ChipGroup
              label={t("parlays.builder.window")}
              value={form.hours}
              options={BUILDER_HOURS.map((h) => ({
                value: h,
                label: t("parlays.builder.hours", { count: h }),
              }))}
              onChange={(hours) => set({ hours, competitions: [] })}
              testId="builder-window"
            />
          </Field>
          <Field label={t("parlays.builder.legs")}>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>{t("parlays.builder.legsFrom")}</span>
              <LegsSelect
                label={t("parlays.builder.legsMin")}
                value={form.minLegs}
                onChange={(n) => setForm((f) => withLegs(f, "min", n))}
              />
              <span>{t("parlays.builder.legsTo")}</span>
              <LegsSelect
                label={t("parlays.builder.legsMax")}
                value={form.maxLegs}
                onChange={(n) => setForm((f) => withLegs(f, "max", n))}
              />
            </div>
          </Field>
        </div>
        <Field label={t("parlays.builder.markets")}>
          <MarketChips value={form.markets} onChange={(markets) => set({ markets })} />
        </Field>
        <div className="grid gap-4 lg:grid-cols-[auto_1fr]">
          <Field label={t("parlays.builder.competitions")}>
            <CompetitionsPicker
              value={form.competitions}
              options={competitions}
              onChange={(c) => set({ competitions: c })}
            />
          </Field>
          <div className="flex flex-wrap gap-4">
            <Field label={t("parlays.builder.legOdds")}>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>{t("parlays.builder.oddsFrom")}</span>
                <OddsInput
                  label={`${t("parlays.builder.legOdds")} · ${t("parlays.builder.oddsFrom")}`}
                  value={form.minOdds}
                  onChange={(minOdds) => set({ minOdds })}
                  invalid={issues.includes("minOdds") || issues.includes("oddsOrder")}
                  placeholder={localDecimalText("1.40")}
                  testId="builder-min-odds"
                />
                <span>{t("parlays.builder.oddsTo")}</span>
                <OddsInput
                  label={`${t("parlays.builder.legOdds")} · ${t("parlays.builder.oddsTo")}`}
                  value={form.maxOdds}
                  onChange={(maxOdds) => set({ maxOdds })}
                  invalid={issues.includes("maxOdds") || issues.includes("oddsOrder")}
                  placeholder={localDecimalText("3.00")}
                  testId="builder-max-odds"
                />
              </div>
            </Field>
            <Field
              label={
                <>
                  {t("parlays.builder.maxTotal")}{" "}
                  <span className="normal-case tracking-normal">
                    ({t("parlays.builder.optional")})
                  </span>
                </>
              }
            >
              <OddsInput
                label={t("parlays.builder.maxTotal")}
                value={form.maxTotal}
                onChange={(maxTotal) => set({ maxTotal })}
                invalid={issues.includes("maxTotal")}
                placeholder="20"
                testId="builder-max-total"
              />
            </Field>
          </div>
        </div>
        {issues.length ? (
          <ul className="space-y-0.5 text-caption text-negative" role="alert">
            {issues.map((i) => (
              <li key={i}>{t(`parlays.builder.issue.${i}`)}</li>
            ))}
          </ul>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="submit"
            disabled={issues.length > 0 || result.isFetching}
            data-testid="builder-build"
            className="inline-flex min-h-10 items-center gap-1.5 rounded-full bg-gold px-5 text-sm font-semibold text-gold-foreground transition-colors hover:brightness-105 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Wand2 aria-hidden className="h-4 w-4" />
            {result.isFetching ? t("parlays.builder.building") : t("parlays.builder.build")}
          </button>
          <button
            type="button"
            onClick={() => {
              setForm(DEFAULT_BUILDER);
              setAsked(null);
            }}
            className="inline-flex min-h-10 items-center gap-1.5 rounded-full px-3 text-sm font-medium text-muted-foreground hover:text-foreground"
          >
            <RotateCcw aria-hidden className="h-3.5 w-3.5" />
            {t("parlays.builder.reset")}
          </button>
        </div>
      </form>

      <div className="border-t border-border/70" aria-live="polite">
        {asked === null ? (
          <p className="px-4 py-4 text-sm text-muted-foreground sm:px-5">
            {t("parlays.builder.hint")}
          </p>
        ) : result.isPending ? (
          <div className="space-y-3 px-4 py-4 sm:px-5">
            <SkeletonBlock className="h-24" />
            <SkeletonBlock className="h-24" />
          </div>
        ) : result.isError ? (
          <ErrorState error={result.error} onRetry={() => void result.refetch()} className="py-6" />
        ) : body ? (
          body.status === "ok" ? (
            <Result key={JSON.stringify(asked)} body={body} />
          ) : (
            <NoParlay body={body} />
          )
        ) : null}
      </div>
    </section>
  );
}
