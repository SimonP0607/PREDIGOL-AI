/**
 * The AI's side of a match in the Admin Console (plan F6): the latest brief (what it said and how sure it was), the
 * research it asked the server to look into and what the server did about it pass by pass, and every claim the server
 * refused with the reason. The AI says WHAT is missing from a list the server wrote; the server decides whether to
 * look, inside the day's searches and budget - so a request can be left unserved, and this is where that shows.
 * Admin only: the users never see any of it.
 */
import { t } from "@/lib/i18n";
import { KeyValue, Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell } from "@/components/primitives/DataTable";
import type { IntelBrief, IntelPass } from "@/lib/api/v1/types_intel";
import { Note, SubTitle } from "./AiBits";
import { bogotaDateTime, passLabel, reasonLabel, usd } from "./aiModel";
import { DASH, askLines, briefFlags, passLines, refusedLines } from "./intelMatch";

// ── the latest brief ─────────────────────────────────────────────────────────

export function BriefPanel({ brief }: { brief: IntelBrief }) {
  const flags = briefFlags(brief);
  return (
    <Panel
      title={t("intel.match.brief.title")}
      subtitle={`${passLabel(brief.pass)} · ${bogotaDateTime(brief.created_at)} · ${brief.version}${
        brief.model ? ` · ${brief.model}` : ""
      } · ${usd(brief.cost_usd)}`}
      actions={
        brief.status === "ok" ? null : (
          <StatusBadge tone="warning" dot={false}>
            {brief.status}
          </StatusBadge>
        )
      }
    >
      <div className="space-y-3" data-testid="intel-brief">
        <p className="text-sm leading-relaxed">{brief.summary ?? DASH}</p>
        <div className="grid gap-x-8 sm:grid-cols-2">
          <div>
            {flags.map((f) => (
              <KeyValue key={f.key} label={f.label} value={f.value} />
            ))}
          </div>
          <div>
            <KeyValue
              label={t("intel.match.brief.reasons")}
              value={
                brief.reasons.length ? (
                  <span className="flex flex-wrap justify-end gap-1">
                    {brief.reasons.map((r) => (
                      <StatusBadge key={r} tone="warning" dot={false}>
                        {reasonLabel(r)}
                      </StatusBadge>
                    ))}
                  </span>
                ) : (
                  DASH
                )
              }
            />
            <KeyValue label={t("intel.match.brief.refused")} value={String(brief.refused_total)} />
            <KeyValue
              label={t("intel.match.brief.research")}
              value={String(brief.research.length)}
            />
          </div>
        </div>
      </div>
    </Panel>
  );
}

// ── the research the AI asked for, and what each pass did about it ──────────

export function ResearchPanel({
  brief,
  passes,
}: {
  brief: IntelBrief | null;
  passes: readonly IntelPass[];
}) {
  const asks = askLines(brief?.research);
  const lines = passLines(passes);
  return (
    <Panel title={t("intel.match.research.title")} subtitle={t("intel.match.research.subtitle")}>
      <div className="space-y-4" data-testid="intel-research">
        <div className="space-y-2">
          <SubTitle>{t("intel.match.research.asked")}</SubTitle>
          {asks.length ? (
            <ul className="space-y-2">
              {asks.map((a) => (
                <li
                  key={`${a.topic}-${a.side}`}
                  className="rounded-md border border-border bg-card px-3 py-2 text-sm"
                  data-testid="intel-research-ask"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <StatusBadge tone="info" dot={false} className="whitespace-normal text-left">
                      {a.topic}
                    </StatusBadge>
                    <span className="text-xs text-subtle-foreground">{a.side}</span>
                  </div>
                  <p className="mt-1 break-words text-xs text-foreground/85">{a.reason}</p>
                  {a.refs.length ? (
                    <p className="mt-0.5 break-words font-mono text-caption text-subtle-foreground">
                      {a.refs.join(" · ")}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <Note>{t("intel.match.research.none")}</Note>
          )}
        </div>
        <div className="space-y-2">
          <SubTitle>{t("intel.match.research.passes")}</SubTitle>
          {lines.length ? (
            <TableShell>
              <THead>
                <TH>{t("intel.match.research.col.pass")}</TH>
                <TH>{t("intel.match.research.col.when")}</TH>
                <TH align="right">{t("intel.match.research.col.requested")}</TH>
                <TH align="right">{t("intel.match.research.col.asked")}</TH>
                <TH align="right">{t("intel.match.research.col.searched")}</TH>
                <TH>{t("intel.match.research.col.unserved")}</TH>
                <TH align="right">{t("intel.match.research.col.searches")}</TH>
                <TH align="right">{t("intel.match.research.col.cost")}</TH>
              </THead>
              <tbody>
                {lines.map((p) => (
                  <TRow key={`${p.pass}-${p.finishedAt}`}>
                    <TD className="whitespace-nowrap">
                      {passLabel(p.pass)}
                      {p.escalated ? (
                        <span className="ml-1 text-caption text-warning">
                          ({t("intel.match.picker.escalated")})
                        </span>
                      ) : null}
                    </TD>
                    <TD className="whitespace-nowrap text-xs">{bogotaDateTime(p.finishedAt)}</TD>
                    <TD align="right">{p.requested}</TD>
                    <TD align="right">{p.asked}</TD>
                    <TD align="right">{p.searched}</TD>
                    <TD className="max-w-[16rem] break-words text-xs">{p.unserved}</TD>
                    <TD align="right">{p.webSearches}</TD>
                    <TD align="right">{usd(p.cost)}</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          ) : (
            <Note>{t("intel.match.research.noPasses")}</Note>
          )}
        </div>
        <Note>{t("intel.match.research.how")}</Note>
      </div>
    </Panel>
  );
}

// ── the claims the server refused ────────────────────────────────────────────

export function RefusedPanel({ brief }: { brief: IntelBrief }) {
  const lines = refusedLines(brief.refused);
  return (
    <Panel
      title={t("intel.match.refused.title")}
      subtitle={t("intel.match.refused.subtitle")}
      actions={
        <StatusBadge tone="warning" dot={false}>
          {brief.refused.length < brief.refused_total
            ? t("intel.match.refused.shown", {
                shown: brief.refused.length,
                total: brief.refused_total,
              })
            : String(brief.refused_total)}
        </StatusBadge>
      }
    >
      <ul className="space-y-2" data-testid="intel-refused">
        {lines.map((c, i) => (
          <li
            key={`${c.group}-${i}`}
            className="rounded-md border border-border bg-card px-3 py-2 text-sm"
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusBadge tone="neutral" dot={false} className="whitespace-normal text-left">
                {c.groupLabel}
              </StatusBadge>
              {c.factor ? (
                <StatusBadge tone="info" dot={false} className="whitespace-normal text-left">
                  {t("intel.match.refused.descriptive", { factor: c.factor })}
                </StatusBadge>
              ) : null}
            </div>
            <p className="mt-1 break-words text-xs text-foreground/85">{c.text}</p>
            <p className="mt-0.5 break-words text-caption text-negative">{c.why}</p>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
