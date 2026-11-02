/** The decisions an owner takes on referees (plan F3): merge two spellings of one man, say they are two, take a decision back. */
import type { PairStatus, RefereeSide } from "@/lib/api/v1/types_referees";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { t } from "@/lib/i18n";
import { isConflict, keepOptions } from "./refereeText";
import { useRefereeAction } from "./useRefereeAction";

const BUTTON =
  "rounded border border-border px-1.5 py-0.5 text-[11px] hover:bg-muted disabled:opacity-50";
const PRIMARY =
  "rounded border border-primary/40 bg-primary/10 px-1.5 py-0.5 text-[11px] text-primary hover:bg-primary/20 disabled:opacity-50";

/** The decision on one pair: keep one of the two, or say they are different people; a decided pair can be reopened. */
export function PairDecision({
  a,
  b,
  status,
}: {
  a: RefereeSide;
  b: RefereeSide;
  status: PairStatus;
}) {
  const m = useRefereeAction();
  const [first, second] = keepOptions(a, b);
  const last = m.variables?.kind === "merge" ? m.variables : null;

  if (status === "merged") {
    return (
      <span className="text-xs text-muted-foreground">{t("referees.queue.status.merged")}</span>
    );
  }
  if (status === "rejected") {
    return (
      <div className="space-y-1">
        <button
          type="button"
          className={BUTTON}
          disabled={m.isPending}
          onClick={() => m.mutate({ kind: "reopen", id: a.id, otherId: b.id })}
        >
          {m.isPending ? t("referees.action.pending") : t("referees.action.reopen")}
        </button>
        {m.isError ? <ApiErrorNotice error={m.error} /> : null}
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1">
        {[first, second].map((o, i) => (
          <button
            key={o.keepId}
            type="button"
            className={i === 0 ? PRIMARY : BUTTON}
            disabled={m.isPending}
            onClick={() => m.mutate({ kind: "merge", keepId: o.keepId, mergeId: o.mergeId })}
          >
            {t("referees.action.keep", { name: o.name })}
          </button>
        ))}
        <button
          type="button"
          className={BUTTON}
          disabled={m.isPending}
          onClick={() => m.mutate({ kind: "reject", id: a.id, otherId: b.id })}
        >
          {t("referees.action.different")}
        </button>
      </div>
      {m.isPending ? (
        <div className="text-caption text-subtle-foreground">{t("referees.action.pending")}</div>
      ) : null}
      {m.isError && isConflict(m.error) && last ? (
        <div
          role="alert"
          className="space-y-1 rounded border border-warning/40 bg-warning-soft px-2 py-1.5 text-xs"
        >
          <div>{t("referees.action.conflict")}</div>
          <button
            type="button"
            className={BUTTON}
            onClick={() => m.mutate({ ...last, force: true })}
          >
            {t("referees.action.force")}
          </button>
        </div>
      ) : m.isError ? (
        <ApiErrorNotice error={m.error} />
      ) : null}
    </div>
  );
}
