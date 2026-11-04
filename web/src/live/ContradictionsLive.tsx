/**
 * CONTRADICCIONES (Operación > Trabajo de la IA, plan IA, phase 3, section 24): what `contra-v1` found between the numbers of a match and what the
 * state says about it - the eight codes C01-C08 -, how many times each fired, on how many matches, how many were confirmed and what each engine's
 * Council did with the candidates they touch (kept, lowered, abstained, or no verdict), and the latest ones with the candidates they touch.
 * Codes and the server's numbers only: never a model's text. Reading only.
 */
import { useState } from "react";
import { t, translateOr } from "@/lib/i18n";
import { DASH, localInt } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  ContraCandidate,
  ContraCode,
  ContraCount,
  ContraItem,
  Contradictions,
} from "@/lib/api/v1/types_ai_shadow";
import { Block, Choice, Framed, Note, Stat, StatGrid, Toolbar } from "./AiBits";
import { bogotaDateTime } from "./aiModel";
import { marketText, pickText } from "./familiesText";
import { Refs, ShadowOffNotice } from "./ShadowBits";
import {
  CONTRA_CODES,
  SHADOW_ENGINES,
  TREATMENTS,
  TREATMENT_TONE,
  contraLabel,
} from "./shadowModel";

const DAYS = [1, 7, 30] as const;

function candidateText(c: ContraCandidate): string {
  if (c.market === null) return c.key;
  return `${marketText(c.market)} · ${pickText(c.market, c.selection ?? "", c.line)}`;
}

/** What one engine did with the candidates a contradiction touched: "mantuvo 2 · bajó 1". */
function TreatmentLine({
  engine,
  byTreatment,
}: {
  engine: string;
  byTreatment: Record<string, number>;
}) {
  const parts = TREATMENTS.filter((k) => (byTreatment[k] ?? 0) > 0);
  return (
    <div className="flex flex-wrap items-center gap-1" data-testid={`contra-treatment-${engine}`}>
      <span className="numeric text-caption text-muted-foreground">{engine}</span>
      {parts.length === 0 ? (
        <span className="text-muted-foreground">{DASH}</span>
      ) : (
        parts.map((k) => (
          <StatusBadge key={k} tone={TREATMENT_TONE[k]} dot={false}>
            {t(`ai.contra.treatment.${k}`)} {localInt(byTreatment[k] ?? 0)}
          </StatusBadge>
        ))
      )}
    </div>
  );
}

function CountRow({ c }: { c: ContraCount }) {
  return (
    <TRow data-testid={`contra-count-${c.code}`}>
      <TD className="min-w-[12rem]">
        <span className="numeric font-medium">{c.code}</span>{" "}
        <span className="text-xs text-muted-foreground">{contraLabel(c.code)}</span>
      </TD>
      <TD align="right">{localInt(c.n)}</TD>
      <TD align="right">{localInt(c.passes)}</TD>
      <TD align="right">{localInt(c.matches)}</TD>
      <TD align="right">{localInt(c.confirmed)}</TD>
      <TD>
        <div className="space-y-1">
          {SHADOW_ENGINES.map((e) => (
            <TreatmentLine key={e} engine={e} byTreatment={c.treatment[e] ?? {}} />
          ))}
        </div>
      </TD>
    </TRow>
  );
}

function RecentRow({
  x,
  onMatch,
}: {
  x: ContraItem;
  onMatch?: ((fixture: number) => void) | undefined;
}) {
  return (
    <TRow data-testid="contra-item">
      <TD className="numeric whitespace-nowrap">
        <div className="font-medium">{x.code}</div>
        <div className="text-caption text-muted-foreground">{contraLabel(x.code)}</div>
      </TD>
      <TD className="min-w-[10rem]">
        {onMatch ? (
          <button
            type="button"
            className="text-left underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            onClick={() => onMatch(x.fixture_id)}
          >
            {x.match ?? `#${x.fixture_id}`}
          </button>
        ) : (
          (x.match ?? `#${x.fixture_id}`)
        )}
        <div className="text-caption text-muted-foreground">
          {translateOr(`ai.arms.pass.${x.pass_kind}`, x.pass_kind)} · {bogotaDateTime(x.known_at)}
        </div>
      </TD>
      <TD>
        {x.candidates.length === 0 ? (
          <span className="text-muted-foreground">{t("ai.contra.wholeMatch")}</span>
        ) : (
          <ul className="space-y-0.5 text-xs">
            {x.candidates.map((c) => (
              <li key={c.key}>
                <span className="numeric text-muted-foreground">{c.key}</span> {candidateText(c)}
              </li>
            ))}
          </ul>
        )}
      </TD>
      <TD>
        <StatusBadge tone={x.confirmed ? "warning" : "neutral"} dot={false}>
          {t(x.confirmed ? "ai.contra.confirmed" : "ai.contra.unconfirmed")}
        </StatusBadge>
        {x.official_lineup ? (
          <div className="mt-0.5 text-caption text-muted-foreground">{t("ai.contra.lineup")}</div>
        ) : null}
      </TD>
      <TD>
        <div className="space-y-1">
          {SHADOW_ENGINES.map((e) => {
            const per = x.treatment[e] ?? {};
            const tally: Record<string, number> = {};
            for (const v of Object.values(per)) tally[v] = (tally[v] ?? 0) + 1;
            return <TreatmentLine key={e} engine={e} byTreatment={tally} />;
          })}
        </div>
      </TD>
      <TD>
        <Refs refs={x.refs} />
      </TD>
    </TRow>
  );
}

/** Everything the view shows, given the figures: the part that needs no server. */
export function ContradictionsBody({
  d,
  onMatch,
}: {
  d: Contradictions;
  onMatch?: ((fixture: number) => void) | undefined;
}) {
  return (
    <div className="space-y-4" data-testid="contradictions-body">
      {!d.switches.orchestrate || d.passes === 0 ? <ShadowOffNotice switches={d.switches} /> : null}
      {d.passes > 0 ? (
        <>
          <StatGrid testId="contra-totals">
            <Stat label={t("ai.contra.passes")} value={localInt(d.passes)} />
            <Stat label={t("ai.contra.withContra")} value={localInt(d.with_contradictions)} />
            <Stat label={t("ai.contra.total")} value={localInt(d.total)} />
          </StatGrid>
          <Block
            title={t("ai.contra.counts.title", { days: d.days })}
            hint={t("ai.contra.counts.hint")}
          >
            <Framed>
              <TableShell>
                <THead>
                  <TH>{t("ai.contra.col.code")}</TH>
                  <TH align="right">{t("ai.contra.col.n")}</TH>
                  <TH align="right">{t("ai.contra.col.passes")}</TH>
                  <TH align="right">{t("ai.contra.col.matches")}</TH>
                  <TH align="right">{t("ai.contra.col.confirmed")}</TH>
                  <TH>{t("ai.contra.col.council")}</TH>
                </THead>
                <tbody>
                  {CONTRA_CODES.map((code) => d.counts.find((c) => c.code === code)).map((c, i) =>
                    c ? (
                      <CountRow key={c.code} c={c} />
                    ) : (
                      <TRow key={CONTRA_CODES[i]} data-testid={`contra-count-${CONTRA_CODES[i]}`}>
                        <TD>
                          <span className="numeric font-medium">{CONTRA_CODES[i]}</span>{" "}
                          <span className="text-xs text-muted-foreground">
                            {contraLabel(CONTRA_CODES[i] ?? "")}
                          </span>
                        </TD>
                        <TD align="right">0</TD>
                        <TD colSpan={4} className="text-xs text-muted-foreground">
                          {t("ai.contra.never")}
                        </TD>
                      </TRow>
                    ),
                  )}
                </tbody>
              </TableShell>
            </Framed>
          </Block>
          <Block title={t("ai.contra.recent.title")} hint={t("ai.contra.recent.hint")}>
            {d.recent.length === 0 ? (
              <Note>{t("ai.contra.recent.empty")}</Note>
            ) : (
              <Framed>
                <TableShell>
                  <THead>
                    <TH>{t("ai.contra.col.code")}</TH>
                    <TH>{t("ai.contra.col.match")}</TH>
                    <TH>{t("ai.contra.col.candidates")}</TH>
                    <TH>{t("ai.contra.col.state")}</TH>
                    <TH>{t("ai.contra.col.council")}</TH>
                    <TH>{t("ai.contra.col.refs")}</TH>
                  </THead>
                  <tbody>
                    {d.recent.map((x, i) => (
                      <RecentRow
                        key={`${x.fixture_id}-${x.pass_kind}-${x.code}-${x.subject}-${i}`}
                        x={x}
                        onMatch={onMatch}
                      />
                    ))}
                  </tbody>
                </TableShell>
              </Framed>
            )}
          </Block>
        </>
      ) : null}
    </div>
  );
}

/** CONTRADICCIONES: the view of Operación > Trabajo de la IA. */
export function ContradictionsView({
  onMatch,
}: {
  onMatch?: ((fixture: number) => void) | undefined;
}) {
  const [days, setDays] = useState<number>(7);
  const [code, setCode] = useState<string>("");
  const q = useLiveQuery(
    live.aiContradictions(days, code === "" ? undefined : (code as ContraCode)),
  );
  const d = q.data?.data ?? null;
  return (
    <Panel
      title={t("ai.contra.title")}
      subtitle={t("ai.contra.subtitle")}
      bodyClassName="space-y-4 p-4"
    >
      <div className="space-y-4" data-testid="contradictions">
        <Note>{t("ai.contra.intro")}</Note>
        <Toolbar>
          <Choice
            label={t("ai.contra.filter.days")}
            value={String(days)}
            onChange={(v) => setDays(Number(v))}
          >
            {DAYS.map((n) => (
              <option key={n} value={n}>
                {t("ai.contra.filter.nDays", { n })}
              </option>
            ))}
          </Choice>
          <Choice label={t("ai.contra.filter.code")} value={code} onChange={setCode}>
            <option value="">{t("ai.contra.filter.allCodes")}</option>
            {CONTRA_CODES.map((c) => (
              <option key={c} value={c}>
                {c} · {contraLabel(c)}
              </option>
            ))}
          </Choice>
        </Toolbar>
        {q.isError ? <ApiErrorNotice error={q.error} /> : null}
        {d ? (
          <ContradictionsBody d={d} onMatch={onMatch} />
        ) : q.isLoading ? (
          <TableSkeleton rows={8} cols={6} />
        ) : null}
      </div>
    </Panel>
  );
}
