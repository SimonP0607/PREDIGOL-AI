/**
 * PrediGol Intelligence in Evolución - the learning center: the calibrators (champion, challengers, retired), the
 * markets whose edge is validated or not, the latest promotions and regressions, and the newest DAILY LEARNING REPORT.
 * Everything with its rule fixed in advance; the full record lives in Admin › PrediGol Intelligence.
 */
import { Link } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { live } from "@/lib/api/v1/queries";
import { Note, SubTitle } from "./AiBits";
import { bogotaDateTime } from "./aiModel";
import { Markdown } from "./Markdown";

export function IntelLearningCenter() {
  const cal = useLiveQuery(live.intelCalibration);
  const rep = useLiveQuery(live.intelReports());
  const c = cal.data?.data;
  const r = rep.data?.data?.report ?? null;
  const regressions = (c?.promotions ?? [])
    .filter((p) => String(p["to_role"]) === "RETIRED")
    .slice(0, 5);
  const promotions = (c?.promotions ?? [])
    .filter((p) => String(p["to_role"]) !== "RETIRED")
    .slice(0, 6);
  return (
    <Panel
      title={t("intel.learning.title")}
      subtitle={t("intel.learning.subtitle")}
      actions={
        <Link to="/admin/intelligence" className="text-xs text-primary">
          {t("intel.learning.open")}
        </Link>
      }
    >
      <div className="grid gap-4 lg:grid-cols-2" data-testid="intel-learning-center">
        <div className="space-y-3">
          <SubTitle>{t("intel.learning.champions")}</SubTitle>
          {c && c.champions.length ? (
            <ul className="space-y-1 text-xs">
              {c.champions.map((x) => (
                <li
                  key={`${x.market_key}-${x.model_name}`}
                  className="flex flex-wrap items-center gap-2"
                >
                  <span className="font-medium">
                    {x.market_key} · {x.model_name}
                  </span>
                  <StatusBadge tone={x.role === "CHAMPION" ? "positive" : "info"} dot={false}>
                    {x.role}
                  </StatusBadge>
                  <StatusBadge tone={x.edge === "VALIDATED" ? "positive" : "neutral"} dot={false}>
                    {x.edge === "VALIDATED"
                      ? t("intel.calibration.validated")
                      : t("intel.calibration.notValidated")}
                  </StatusBadge>
                </li>
              ))}
            </ul>
          ) : (
            <Note>{t("intel.calibration.empty")}</Note>
          )}
          <SubTitle>{t("intel.learning.promotions")}</SubTitle>
          {promotions.length ? (
            <ul className="space-y-1 text-xs">
              {promotions.map((p) => (
                <li key={String(p["id"])} className="break-words">
                  <span className="text-muted-foreground">{bogotaDateTime(String(p["at"]))}</span> ·{" "}
                  {String(p["market_key"])}/{String(p["model_name"])} → {String(p["to_role"])}:{" "}
                  {String(p["reason"])}
                </li>
              ))}
            </ul>
          ) : (
            <Note>—</Note>
          )}
          <SubTitle>{t("intel.learning.regressions")}</SubTitle>
          {regressions.length ? (
            <ul className="space-y-1 text-xs">
              {regressions.map((p) => (
                <li key={String(p["id"])} className="break-words">
                  {String(p["market_key"])}/{String(p["model_name"])}: {String(p["reason"])}
                </li>
              ))}
            </ul>
          ) : (
            <Note>{t("intel.learning.noRegressions")}</Note>
          )}
        </div>
        <div className="space-y-2">
          <SubTitle>{t("intel.day.reportTitle")}</SubTitle>
          {r ? (
            <Markdown text={r.text} className="max-h-[28rem] overflow-y-auto" />
          ) : (
            <Note>{t("intel.day.reportEmpty")}</Note>
          )}
        </div>
      </div>
    </Panel>
  );
}
