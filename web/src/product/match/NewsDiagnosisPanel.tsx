/**
 * Admin only (IA-018): why this match has news or not - the verdict of the server first, then what it is made of: the competition's
 * priority group and the guaranteed coverage, the market and the AI's day, the next pass, the paid searches, Exa's budget of the
 * month, the stored news by status and every pass with its web counts. Drawn by the Advanced tab for the owner alone; a reader's
 * Noticias say only whether the match was searched.
 */
import { useQuery } from "@tanstack/react-query";
import { SearchCheck } from "lucide-react";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import type { NewsDiagnosis } from "@/lib/api/v1/types_news";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { Card } from "@/product/shared/States";
import {
  coverageText,
  dayText,
  evidenceText,
  exaText,
  marketText,
  nextPassText,
  passName,
  passStatusText,
  passWebText,
  searchesText,
  verdictText,
  whenText,
} from "./newsDiagnosis";

export function NewsDiagnosisView({ d, now = Date.now() }: { d: NewsDiagnosis; now?: number }) {
  const rows: Array<[string, string]> = [
    [
      t("match.advanced.news.label.competition"),
      t("match.advanced.news.competitionLine", {
        competition: d.match.competition,
        group: d.match.priority_group,
      }),
    ],
    [t("match.advanced.news.label.coverage"), coverageText(d)],
    [t("match.advanced.news.label.market"), marketText(d, now)],
    [t("match.advanced.news.label.day"), dayText(d, now)],
    [t("match.advanced.news.label.next"), nextPassText(d.next_pass, now)],
    [t("match.advanced.news.label.searches"), searchesText(d, now)],
    [t("match.advanced.news.label.exa"), exaText(d.exa)],
    [t("match.advanced.news.label.evidence"), evidenceText(d)],
  ];
  return (
    <div className="space-y-3">
      <p
        className="rounded-md border border-border/70 bg-muted/40 px-3 py-2 text-sm font-medium"
        data-testid="advanced-news-verdict"
        data-code={d.verdict.code}
      >
        {verdictText(d.verdict, now)}
      </p>
      <dl className="grid gap-x-4 gap-y-1.5 text-xs sm:grid-cols-[auto_1fr]">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-subtle-foreground">{label}</dt>
            <dd className="min-w-0 break-words">{value}</dd>
          </div>
        ))}
      </dl>
      <div>
        <h3 className="mb-1 text-xs font-semibold">{t("match.advanced.news.label.passes")}</h3>
        {d.passes.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("match.advanced.news.empty")}</p>
        ) : (
          <ul className="space-y-1 text-xs" data-testid="advanced-news-passes">
            {d.passes.map((p) => (
              <li
                key={`${p.day}-${p.kind}`}
                className="rounded-md border border-border/70 px-2 py-1.5"
              >
                <span className="font-medium">
                  {t("match.advanced.news.passRow", {
                    pass: passName(p.kind),
                    when: whenText(p.finished_at, now),
                    status: passStatusText(p.status),
                  })}
                </span>
                <span className="block text-muted-foreground">{passWebText(p)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function NewsDiagnosisPanel({ fixtureId }: { fixtureId: string }) {
  const q = useQuery(live.newsDiagnosis(fixtureId));
  const d = q.data?.data ?? null;
  return (
    <Card className="space-y-3 p-4" data-testid="advanced-news-diagnostics">
      <div>
        <h2 className="flex items-center gap-1.5 text-sm font-semibold">
          <SearchCheck aria-hidden className="h-4 w-4 shrink-0" />
          {t("match.advanced.news.title")}
        </h2>
        <p className="mt-1 text-caption text-muted-foreground">{t("match.advanced.news.intro")}</p>
      </div>
      {q.isLoading ? (
        <p className="text-xs text-muted-foreground">{t("common.loading")}</p>
      ) : q.isError && !d ? (
        <ApiErrorNotice error={q.error} />
      ) : d ? (
        <NewsDiagnosisView d={d} />
      ) : (
        <p className="text-xs text-muted-foreground">{t("match.advanced.news.error")}</p>
      )}
    </Card>
  );
}
