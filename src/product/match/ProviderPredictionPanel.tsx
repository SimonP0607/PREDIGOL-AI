/**
 * Admin only: API-Football's own forecast of the match, every version kept, labelled as the provider's.
 * It sits in the Advanced tab, away from PrediGol's model and the market, and no pick is made from it.
 */
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import { Card } from "@/product/shared/States";
import { ProvenanceNote } from "@/live/ReferenceData";
import { dec, utcDateTime } from "@/live/format";

export function ProviderPredictionPanel({ fixtureId }: { fixtureId: string }) {
  const q = useQuery(live.providerPrediction(fixtureId));
  const env = q.data;
  const view = env?.data ?? null;
  const latest = view?.history.length ? view.history[view.history.length - 1] : null;
  return (
    <Card className="space-y-3 p-4" data-testid="provider-prediction">
      <div>
        <h2 className="text-sm font-semibold">{t("match.providerPrediction.title")}</h2>
        <p className="mt-1 flex items-start gap-1.5 text-caption text-muted-foreground">
          <Info aria-hidden className="mt-px h-3.5 w-3.5 shrink-0" />
          {t("match.providerPrediction.label")}
        </p>
      </div>
      {q.isLoading ? (
        <p className="text-xs text-muted-foreground">{t("common.loading")}</p>
      ) : !latest ? (
        <p className="text-xs text-muted-foreground">
          {env?.reason ?? t("match.providerPrediction.none")}
        </p>
      ) : (
        <>
          <dl className="grid grid-cols-3 gap-2 text-center">
            {(
              [
                ["home", latest.percent_home],
                ["draw", latest.percent_draw],
                ["away", latest.percent_away],
              ] as const
            ).map(([k, v]) => (
              <div key={k} className="rounded-md border border-border/70 px-2 py-1.5">
                <dt className="text-caption text-subtle-foreground">
                  {t(`match.providerPrediction.${k}`)}
                </dt>
                <dd className="numeric text-sm font-semibold">
                  {v === null ? "—" : `${dec(v, 0)}%`}
                </dd>
              </div>
            ))}
          </dl>
          <ul className="space-y-1 text-xs">
            {latest.advice ? (
              <li>{t("match.providerPrediction.advice", { advice: latest.advice })}</li>
            ) : null}
            {latest.winner_name ? (
              <li>
                {t("match.providerPrediction.winner", {
                  team: latest.winner_name,
                  comment: latest.winner_comment ?? "",
                })}
              </li>
            ) : null}
            {latest.under_over ? (
              <li>{t("match.providerPrediction.underOver", { line: latest.under_over })}</li>
            ) : null}
          </ul>
          <ProvenanceNote
            p={{
              source: "API-Football /predictions",
              observed_at: latest.observed_at,
              payload_hash: latest.payload_hash,
              normalizer_version: latest.normalizer_version,
              checked_at: null,
            }}
          />
          {view && view.history.length > 1 ? (
            <p className="text-caption text-subtle-foreground">
              {t("match.providerPrediction.versions", {
                count: view.history.length,
                first: utcDateTime(view.history[0]?.observed_at ?? null),
              })}
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}
