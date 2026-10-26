/**
 * The day's set, empty: why (plan UX, A9; section 24). The honest sentence and its reason, «todavía estamos revisando»
 * while the set does not exist yet, a day without matches - and, when the reason cannot be loaded, the empty state the
 * list always had with a retry: a failure never reads as a reason.
 */
import { Hourglass, Trophy } from "lucide-react";
import type { ReactNode } from "react";
import { t } from "@/lib/i18n";
import { Card, EmptyState, SkeletonBlock } from "@/product/shared/States";
import { noPickView, type NoPickLoad } from "./noPick";

function Frame({
  icon,
  testState,
  reason,
  children,
}: {
  icon: ReactNode;
  testState: string;
  reason?: string | null | undefined;
  children: ReactNode;
}) {
  return (
    <Card>
      <div
        data-empty-state
        data-testid="no-pick"
        data-state={testState}
        data-reason={reason ?? undefined}
        className="flex items-start gap-3 px-4 py-4 sm:px-5"
      >
        <span
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-border-strong bg-elevated text-subtle-foreground"
        >
          {icon}
        </span>
        <div className="min-w-0 space-y-1.5 pt-0.5">{children}</div>
      </div>
    </Card>
  );
}

function Generic({ action }: { action?: ReactNode }) {
  return (
    <Card>
      <EmptyState
        icon={<Trophy aria-hidden className="h-6 w-6" />}
        title={t("records.daily.reason.no_qualified_picks")}
        body={t("records.daily.emptyBody")}
        action={action}
      />
    </Card>
  );
}

export function NoPickState({
  load,
  more,
}: {
  load: NoPickLoad;
  /** What else a day without picks leads to (the way to «Cómo le va a PrediGol», A12): the caller decides. */
  more?: ReactNode;
}) {
  if (load.status === "pending") {
    return (
      <Card>
        <div
          aria-busy="true"
          aria-label={t("common.loading")}
          className="space-y-2 px-4 py-4 sm:px-5"
        >
          <SkeletonBlock className="h-4 w-3/4" />
          <SkeletonBlock className="h-4 w-1/2" />
        </div>
      </Card>
    );
  }
  if (load.status === "error") {
    return (
      <Generic
        action={
          <p className="text-caption text-muted-foreground" data-testid="no-pick-error">
            {t("records.noPick.reasonError")}{" "}
            <button
              type="button"
              onClick={load.retry}
              className="tap-y relative font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {t("common.retry")}
            </button>
          </p>
        }
      />
    );
  }
  const view = noPickView(load.value);
  if (view.kind === "generic") return <Generic />;
  if (view.kind === "reviewing") {
    return (
      <Frame icon={<Hourglass className="h-5 w-5" />} testState="reviewing">
        <p className="text-sm font-semibold text-foreground" data-testid="no-pick-title">
          {t("records.noPick.reviewing")}
        </p>
        <p className="text-sm text-muted-foreground">{t("records.noPick.reviewingBody")}</p>
      </Frame>
    );
  }
  if (view.kind === "no_matches") {
    return (
      <Frame icon={<Trophy className="h-5 w-5" />} testState="none" reason="no_matches">
        <p className="text-sm font-semibold text-foreground" data-testid="no-pick-title">
          {t("records.noPick.noMatches")}
        </p>
        {more}
      </Frame>
    );
  }
  return (
    <Frame icon={<Trophy className="h-5 w-5" />} testState="none" reason={load.value?.reason}>
      <p className="text-sm font-semibold leading-snug text-foreground" data-testid="no-pick-title">
        {t("records.noPick.honest")}
      </p>
      {view.why ? (
        <p className="text-sm text-muted-foreground" data-testid="no-pick-reason">
          <span className="font-medium text-foreground/90">{t("records.noPick.why")}: </span>
          {view.why}
        </p>
      ) : null}
      <p className="text-caption leading-snug text-subtle-foreground">
        {t("records.daily.emptyBody")}
      </p>
      {more}
    </Frame>
  );
}
