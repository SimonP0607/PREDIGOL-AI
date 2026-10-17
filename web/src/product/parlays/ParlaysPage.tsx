/**
 * Parlays: the day's parlay and the multi-day parlay as PrediGol recorded them - built once,
 * frozen, followed to their result, each selection with why it is there - the automatic builder
 * (REVIEW point 15: the user's filters, PrediGol's rule), the way to build one's own (point 16)
 * and how they are chosen. With too few selections worth combining there is no parlay: never a
 * padded one.
 */
import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, Check, ChevronDown, Info, Layers, ListX, Sigma, Unlink } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import { useAuth, usePreviewParam } from "@/lib/auth/AuthProvider";
import type { RecordKind } from "@/lib/api/v1/types_records";
import { Card, ErrorState, PageTitle, SkeletonBlock } from "@/product/shared/States";
import { ShadowToggle } from "@/product/shared/ShadowToggle";
import { EvaluationNote } from "@/product/records/DailySetBlock";
import { ParlayRecordCard } from "@/product/records/ParlayRecordCard";
import { useSlip } from "@/product/records/slipContext";
import { ParlayBuilder } from "./Builder";

function RuleGroup({
  icon: Icon,
  title,
  lines,
}: {
  icon: LucideIcon;
  title: string;
  lines: string[];
}) {
  return (
    <div>
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Icon aria-hidden className="h-4 w-4 shrink-0 text-gold" />
        {title}
      </h3>
      <ul className="mt-2.5 space-y-2">
        {lines.map((line) => (
          <li key={line} className="flex items-start gap-2 text-sm text-muted-foreground">
            <Check aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            <span>{line}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function HowWeBuild() {
  return (
    <details className="group rounded-xl border border-border bg-card" data-testid="parlays-how">
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-3 text-sm font-semibold transition-colors hover:bg-elevated/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring sm:px-5 [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-2">
          <Info aria-hidden className="h-4 w-4 shrink-0 text-primary" />
          {t("parlays.how.title")}
        </span>
        <ChevronDown
          aria-hidden
          className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="grid gap-6 border-t border-border px-4 py-5 sm:px-5 md:grid-cols-2 md:gap-8 xl:grid-cols-4">
        <RuleGroup
          icon={BadgeCheck}
          title={t("parlays.how.value.title")}
          lines={[
            t("parlays.how.value.qualified"),
            t("parlays.how.value.fresh"),
            t("parlays.how.value.ev"),
            t("parlays.how.value.consensus"),
            t("parlays.how.value.books"),
            t("parlays.how.value.interval"),
            t("parlays.how.value.risk"),
            t("parlays.how.value.ai"),
          ]}
        />
        <RuleGroup
          icon={Unlink}
          title={t("parlays.how.independence.title")}
          lines={[
            t("parlays.how.independence.oneMatch"),
            t("parlays.how.independence.noTeam"),
            t("parlays.how.independence.perCompetition"),
            t("parlays.how.independence.noQuarter"),
            t("parlays.how.independence.measured"),
          ]}
        />
        <RuleGroup
          icon={Sigma}
          title={t("parlays.how.choice.title")}
          lines={[
            t("parlays.how.choice.growth"),
            t("parlays.how.choice.positive"),
            t("parlays.how.choice.frozen"),
          ]}
        />
        <RuleGroup
          icon={ListX}
          title={t("parlays.how.noPadding.title")}
          lines={[t("parlays.how.noPadding.body")]}
        />
      </div>
    </details>
  );
}

function BuildYourOwn() {
  const slip = useSlip();
  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-5">
      <div className="min-w-0">
        <p className="font-display text-sm font-semibold">{t("parlays.own.title")}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">{t("parlays.own.body")}</p>
      </div>
      <button
        type="button"
        onClick={() => slip.setOpen(true)}
        data-testid="parlays-build-own"
        className="inline-flex min-h-10 items-center gap-1.5 rounded-full border border-gold/50 bg-gold-soft px-4 text-sm font-semibold text-gold-strong transition-colors hover:bg-gold-soft/70 pointer-coarse:min-h-11"
      >
        <Layers aria-hidden className="h-4 w-4" />
        {t("records.mine.parlays.build")}
      </button>
    </Card>
  );
}

const KINDS: readonly RecordKind[] = ["daily", "multiday"];

export function ParlaysPage() {
  const auth = useAuth();
  const preview = usePreviewParam();
  const board = useQuery(live.daily(preview));
  const data = board.data?.data;
  const adminToggle = auth.showAdmin && auth.can("admin.shadow_preview");
  return (
    <div className="space-y-6" data-testid="parlays-page">
      <PageTitle
        title={t("nav.parlays")}
        subtitle={t("parlays.subtitle")}
        right={adminToggle ? <ShadowToggle /> : undefined}
      />
      {data?.evaluation_mode ? <EvaluationNote /> : null}
      {KINDS.map((kind) =>
        data ? (
          <ParlayRecordCard
            key={kind}
            kind={kind}
            parlay={kind === "daily" ? data.daily_parlay : data.multiday_parlay}
            evaluation={data.evaluation_mode}
          />
        ) : board.isError ? (
          <Card key={kind}>
            <ErrorState error={board.error} onRetry={() => void board.refetch()} />
          </Card>
        ) : (
          <SkeletonBlock key={kind} className="h-80 rounded-xl" />
        ),
      )}
      <ParlayBuilder />
      <BuildYourOwn />
      <HowWeBuild />
      {/* Wide screens already carry it in the page footer. */}
      <p className="text-center text-caption text-subtle-foreground lg:hidden">
        {t("common.disclaimer")}
      </p>
    </div>
  );
}
