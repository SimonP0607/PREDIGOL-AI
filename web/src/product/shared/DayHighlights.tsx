/**
 * AP-K04: «Lo más interesante de hoy · Análisis del día · no es un pick». Two or three matches of the day with what each side
 * plays for and PrediGol's forecast with its seal. No unit, no price, no Mi parlay button: it is something to read, said so in
 * its label (see ./dayHighlightsModel.ts for how the matches are chosen). It shows only on a day without picks, with FBI_DAY_HIGHLIGHTS on.
 */
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { CompetitionTag, Matchup } from "@/components/football/Logos";
import { live } from "@/lib/api/v1/queries";
import { usePreviewParam, useUxFixSwitches } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { Reasons, kickoffAt } from "@/product/home/HomeStakes";
import { Card, SectionHeader } from "@/product/shared/States";
import { chooseHighlights, type Highlight } from "./dayHighlightsModel";

function forecastLine(h: Highlight): string | null {
  const f = h.forecast;
  if (!f) return null;
  const pct = Math.round(Math.min(1, Math.max(0, Number(f.probability))) * 100);
  const who =
    f.outcome === "draw"
      ? t("home.atStake.draw")
      : t("home.atStake.wins", {
          team: f.outcome === "home" ? h.stake.home.name : h.stake.away.name,
        });
  return `${pct} % ${who}`;
}

export function DayHighlightsView({
  highlights,
  now,
}: {
  highlights: readonly Highlight[];
  now?: number | undefined;
}) {
  if (highlights.length === 0) return null;
  return (
    <section data-testid="day-highlights" aria-label={t("home.dayHighlights.title")}>
      <SectionHeader
        title={t("home.dayHighlights.title")}
        subtitle={t("home.dayHighlights.label")}
        icon={<Sparkles aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
      />
      <Card className="mt-3 overflow-hidden">
        <ul className="divide-y divide-border/70">
          {highlights.map((h) => {
            const line = forecastLine(h);
            return (
              <li key={h.stake.fixture_id} data-testid="day-highlight">
                <Link
                  to="/matches/$fixtureId"
                  params={{ fixtureId: String(h.stake.fixture_id) }}
                  className="block space-y-1.5 px-4 py-3 transition-colors hover:bg-elevated/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring sm:px-5"
                >
                  <Matchup
                    home={{ name: h.stake.home.name, logo: h.stake.home.logo_url }}
                    away={{ name: h.stake.away.name, logo: h.stake.away.logo_url }}
                    score={null}
                    size={18}
                    strong={false}
                    className="font-medium"
                  />
                  <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-caption">
                    <span className="numeric font-semibold text-foreground">
                      {kickoffAt(h.stake.kickoff_at, now)}
                    </span>
                    <CompetitionTag
                      name={h.stake.competition.name}
                      logo={h.stake.competition.logo_url}
                      flag={h.stake.competition.flag_url}
                      country={h.stake.competition.country}
                      size={12}
                      className="min-w-0"
                    />
                    {h.followed ? (
                      <span className="rounded-full border border-border px-1.5 text-micro text-muted-foreground">
                        {t("home.dayHighlights.yours")}
                      </span>
                    ) : null}
                  </div>
                  <Reasons reasons={[h.stake.reason]} />
                  <p
                    className="text-caption text-muted-foreground"
                    data-testid="day-highlight-forecast"
                  >
                    {line ? (
                      <>
                        <span className="text-subtle-foreground">
                          {t("home.dayHighlights.forecast")}:{" "}
                        </span>
                        <span className="numeric font-semibold text-primary">{line}</span>
                        {h.forecast?.calibrated === false ? (
                          <span className="ml-1 font-semibold text-warning">
                            · {t("intelligence.calibration.uncalibrated")}
                          </span>
                        ) : null}
                      </>
                    ) : (
                      t("home.atStake.noForecast")
                    )}
                  </p>
                </Link>
              </li>
            );
          })}
        </ul>
      </Card>
      <p className="mt-2 text-caption text-subtle-foreground" data-testid="day-highlights-how">
        {t("home.dayHighlights.how")}
      </p>
    </section>
  );
}

/** The block as the pages use it: nothing at all while the switch is off, and nothing of its own to say when there is nothing to read. */
export function DayHighlights() {
  const { dayHighlights } = useUxFixSwitches();
  const preview = usePreviewParam();
  const home = useQuery({ ...live.home(preview), enabled: dayHighlights });
  const today = useQuery({ ...live.today, enabled: dayHighlights });
  if (!dayHighlights) return null;
  const stakes = home.data?.data?.at_stake?.data ?? [];
  const matches = today.data?.data?.matches.data ?? [];
  return <DayHighlightsView highlights={chooseHighlights(stakes, matches)} />;
}
