/**
 * System page (plan UX, A2): the synthetic journey's last runs, and the owner's tests of error reporting - an error
 * raised on purpose in the API and one in the browser, each to be found in Sentry by its reference.
 */
import { useState } from "react";
import { Panel, KeyValue } from "@/components/primitives/Panel";
import { Numeric } from "@/components/primitives/Indicators";
import { StatusNotice } from "@/components/system/LiveState";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { RunSummary } from "@/lib/api/v1/types";
import { t } from "@/lib/i18n";
import { int } from "@/lib/format";
import { reportTestError } from "@/lib/observability";
import { utcDateTime } from "./format";
import { RunStatusBadge } from "./shared";
import { syntheticJob } from "./synthetic";

export function SyntheticPanel() {
  const q = useLiveQuery(live.jobs);
  const job = syntheticJob(q.data?.data ?? []);
  return (
    <Panel title={t("system.synthetic.title")} subtitle={t("system.synthetic.subtitle")}>
      <div data-testid="synthetic-panel" className="space-y-2">
        {!job ? (
          <StatusNotice status="not_available" reason={t("system.synthetic.off")} />
        ) : (
          <>
            <KeyValue
              label={t("system.synthetic.last")}
              value={
                job.last_status ? (
                  <RunStatusBadge status={job.last_status as RunSummary["status"]} />
                ) : (
                  "—"
                )
              }
            />
            <KeyValue
              label={t("system.synthetic.lastSuccess")}
              value={<Numeric muted>{utcDateTime(job.last_success_at)}</Numeric>}
            />
            <KeyValue
              label={t("system.synthetic.runs24h")}
              value={<Numeric>{int(job.runs_24h)}</Numeric>}
            />
            <KeyValue
              label={t("system.synthetic.failed24h")}
              value={
                <Numeric className={job.failed_24h ? "text-negative" : ""}>
                  {int(job.failed_24h)}
                </Numeric>
              }
            />
            {job.last_error ? (
              <p className="text-caption text-negative" data-testid="synthetic-last-error">
                {t("system.synthetic.lastError", { error: job.last_error })}
              </p>
            ) : null}
          </>
        )}
      </div>
    </Panel>
  );
}

export function ObservabilityTestPanel() {
  const [api, setApi] = useState<string | null>(null);
  const [web, setWeb] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function apiTest() {
    setBusy(true);
    try {
      await v1.monitoringTestError();
      setApi(t("system.observability.unexpected"));
    } catch (err) {
      setApi(
        err instanceof LiveApiError && err.status === 500 && err.requestId
          ? t("system.observability.apiSent", { id: err.requestId })
          : t("system.observability.failed", {
              error: err instanceof Error ? err.message : String(err),
            }),
      );
    } finally {
      setBusy(false);
    }
  }

  async function webTest() {
    setBusy(true);
    try {
      setWeb(
        (await reportTestError())
          ? t("system.observability.webSent")
          : t("system.observability.webOff"),
      );
    } finally {
      setBusy(false);
    }
  }

  const button =
    "inline-flex items-center justify-center rounded-md border border-border-strong px-3 py-2 text-xs font-medium hover:bg-elevated disabled:opacity-50 pointer-coarse:min-h-11";
  return (
    <Panel title={t("system.observability.title")} subtitle={t("system.observability.subtitle")}>
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={button}
            onClick={() => void apiTest()}
            disabled={busy}
            data-testid="obs-api-test"
          >
            {t("system.observability.apiTest")}
          </button>
          <button
            type="button"
            className={button}
            onClick={() => void webTest()}
            disabled={busy}
            data-testid="obs-web-test"
          >
            {t("system.observability.webTest")}
          </button>
        </div>
        {api ? (
          <p className="text-caption" data-testid="obs-api-result" role="status">
            {api}
          </p>
        ) : null}
        {web ? (
          <p className="text-caption" data-testid="obs-web-result" role="status">
            {web}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
