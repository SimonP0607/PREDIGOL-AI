/**
 * Parlays: the parlay of the day and the multi-day parlay in full, and how they are
 * built. With too few selections that have value there is no parlay - never a padded one.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { BadgeCheck, Check, ChevronDown, Info, ListX, Unlink } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import { useAuth, usePreviewParam } from "@/lib/auth/AuthProvider";
import type { Envelope } from "@/lib/api/v1/types";
import type { Parlay, ParlayKind } from "@/lib/api/v1/types_product";
import { ErrorState, PageTitle, SkeletonBlock } from "@/product/shared/States";
import { ShadowToggle } from "@/product/home/ShadowToggle";
import { ParlayCard } from "./ParlayCard";
import { PARLAY_ICON, parlayTitle } from "./parlayText";

function ParlaySlot({
  kind,
  query,
}: {
  kind: ParlayKind;
  query: UseQueryResult<Envelope<Parlay>>;
}) {
  const parlay = query.data?.data;
  if (parlay) return <ParlayCard parlay={parlay} variant="full" />;
  const Icon = PARLAY_ICON[kind];
  return (
    <section
      aria-label={parlayTitle(kind)}
      aria-busy={query.isPending || undefined}
      className="rounded-xl border border-gold/25 bg-card"
    >
      <h2 className="flex items-center gap-2 px-4 pt-4 font-display text-lg font-semibold tracking-tight sm:px-5">
        <Icon aria-hidden className="h-5 w-5 shrink-0 text-gold" />
        {parlayTitle(kind)}
      </h2>
      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className="space-y-3 px-4 pb-5 pt-4 sm:px-5">
          <SkeletonBlock className="h-3.5 w-40" />
          {[0, 1, 2].map((i) => (
            <SkeletonBlock key={i} className="h-16" />
          ))}
          <SkeletonBlock className="h-20" />
        </div>
      )}
    </section>
  );
}

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
      <div className="grid gap-6 border-t border-border px-4 py-5 sm:px-5 md:grid-cols-3 md:gap-8">
        <RuleGroup
          icon={BadgeCheck}
          title={t("parlays.how.value.title")}
          lines={[
            t("parlays.how.value.qualified"),
            t("parlays.how.value.fresh"),
            t("parlays.how.value.ev"),
            t("parlays.how.value.consensus"),
          ]}
        />
        <RuleGroup
          icon={Unlink}
          title={t("parlays.how.independence.title")}
          lines={[
            t("parlays.how.independence.oneMatch"),
            t("parlays.how.independence.noTeam"),
            t("parlays.how.independence.independent"),
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

export function ParlaysPage() {
  const auth = useAuth();
  const preview = usePreviewParam();
  const daily = useQuery(live.parlay("daily", preview));
  const multiday = useQuery(live.parlay("multiday", preview));
  const adminToggle = auth.showAdmin && auth.can("admin.shadow_preview");
  return (
    <div className="space-y-6" data-testid="parlays-page">
      <PageTitle
        title={t("nav.parlays")}
        subtitle={t("parlays.subtitle")}
        right={adminToggle ? <ShadowToggle /> : undefined}
      />
      <ParlaySlot kind="daily" query={daily} />
      <ParlaySlot kind="multiday" query={multiday} />
      <HowWeBuild />
      {/* Wide screens already carry it in the page footer. */}
      <p className="text-center text-caption text-subtle-foreground lg:hidden">
        {t("common.disclaimer")}
      </p>
    </div>
  );
}
