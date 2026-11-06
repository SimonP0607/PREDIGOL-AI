/**
 * The words of «Cómo le va a PrediGol» that are not figures (plan de cierre UX, 1.5): what a pick is, how to read
 * probabilities and odds, the history of changes (Novedades and the dated definitions) and, while nothing has been
 * published, the plain statement of it with the days without picks and the forecast that is measured. Text and links only:
 * nothing here is read from the intelligence, and no threshold, prompt or internal state is named.
 */
import { Link } from "@tanstack/react-router";
import { BookOpen, History, Info, Sigma } from "lucide-react";
import { t } from "@/lib/i18n";
import type { Transparency } from "@/lib/api/v1/types_transparency";
import { Block, Note } from "./parts";
import { changesOf, dayText, intText, reasonsOf, type Change } from "./model";

/** The lines of the history shown at once; the rest open under «Ver todo el historial». */
export const CHANGES_SHOWN = 6;

const PICK_PARAGRAPHS = ["what", "notSure", "frozen", "filters"] as const;
const READ_TERMS = ["odds", "said", "market", "value", "units", "results"] as const;

/** While no pick has been published the page says so, as it is, and where the rest is (never a figure it does not have). */
export function ZeroNotice({ data }: { data: Transparency }) {
  const days = data.days;
  const reason = reasonsOf(days)[0];
  const measured = data.forecasts.filter((f) => f.matches > 0);
  return (
    <section
      className="space-y-2 rounded-xl border border-info/30 bg-info-soft p-4"
      data-testid="transparency-zero"
      aria-labelledby="transparency-zero-title"
    >
      <h2
        id="transparency-zero-title"
        className="flex items-center gap-2 font-display text-base font-semibold sm:text-lg"
      >
        <Info aria-hidden className="h-4 w-4" />
        {t("transparency.zero.title")}
      </h2>
      <p className="text-sm">{t("transparency.zero.body")}</p>
      {days.days > 0 ? (
        <p className="text-sm" data-testid="transparency-zero-days">
          {t("transparency.days.summary", {
            without: intText(days.without),
            days: intText(days.days),
            since: dayText(days.since),
            until: dayText(days.until),
          })}
          {reason
            ? ` ${t("transparency.zero.reason", { reason: t(`transparency.days.reasons.${reason[0]}`) })}`
            : ""}
        </p>
      ) : null}
      {measured.length > 0 ? (
        <p className="text-sm" data-testid="transparency-zero-forecast">
          {t("transparency.zero.forecast")}
        </p>
      ) : null}
      <p className="text-sm">
        <a
          href="#transparency-days"
          className="tap-y relative text-primary underline-offset-2 hover:underline"
        >
          {t("transparency.zero.toDays")}
        </a>
        {" · "}
        <a
          href="#transparency-forecast"
          className="tap-y relative text-primary underline-offset-2 hover:underline"
        >
          {t("transparency.zero.toForecast")}
        </a>
      </p>
    </section>
  );
}

export function WhatIsPickBlock() {
  return (
    <Block
      id="what-is-a-pick"
      title={t("transparency.reading.pick.title")}
      icon={<BookOpen className="h-4 w-4" />}
    >
      <div className="space-y-2 text-sm">
        {PICK_PARAGRAPHS.map((k) => (
          <p key={k}>{t(`transparency.reading.pick.${k}`)}</p>
        ))}
      </div>
    </Block>
  );
}

export function HowToReadBlock() {
  return (
    <Block
      id="how-to-read"
      title={t("transparency.reading.read.title")}
      subtitle={t("transparency.reading.read.intro")}
      icon={<Sigma className="h-4 w-4" />}
    >
      <dl className="space-y-2.5 text-sm">
        {READ_TERMS.map((k) => (
          <div key={k} data-testid={`transparency-term-${k}`}>
            <dt className="font-semibold">{t(`transparency.reading.read.terms.${k}.name`)}</dt>
            <dd className="text-muted-foreground">
              {t(`transparency.reading.read.terms.${k}.text`)}
            </dd>
          </div>
        ))}
      </dl>
      <Note>{t("transparency.reading.read.example")}</Note>
    </Block>
  );
}

function ChangeLine({ change }: { change: Change }) {
  return (
    <li
      className="space-y-0.5 px-3 py-2 text-sm"
      data-testid={`transparency-change-${change.kind}`}
    >
      <p className="text-caption text-muted-foreground">
        <time dateTime={change.day}>{dayText(change.day)}</time>
        {" · "}
        {t(`transparency.changes.kinds.${change.kind}`)}
      </p>
      <p className="font-medium">
        {change.kind === "novelty"
          ? t(`support.updates.items.${change.key}.title`)
          : t("transparency.changes.definitionLine", {
              name: t(`transparency.definitions.names.${change.key}`),
              version: change.version,
            })}
      </p>
    </li>
  );
}

export function ChangesBlock({ data }: { data: Transparency }) {
  const changes = changesOf(data.definitions);
  const first = changes.slice(0, CHANGES_SHOWN);
  const rest = changes.slice(CHANGES_SHOWN);
  return (
    <Block
      id="changes"
      title={t("transparency.changes.title")}
      subtitle={t("transparency.changes.subtitle")}
      icon={<History className="h-4 w-4" />}
    >
      <ul
        className="divide-y divide-border rounded-lg border border-border"
        data-testid="transparency-changes"
      >
        {first.map((c) => (
          <ChangeLine key={c.id} change={c} />
        ))}
      </ul>
      {rest.length > 0 ? (
        <details
          className="group rounded-lg border border-border"
          data-testid="transparency-changes-more"
        >
          <summary className="flex min-h-11 cursor-pointer items-center px-3 text-sm font-medium text-primary">
            {t("transparency.changes.more", { count: changes.length })}
          </summary>
          <ul className="divide-y divide-border border-t border-border">
            {rest.map((c) => (
              <ChangeLine key={c.id} change={c} />
            ))}
          </ul>
        </details>
      ) : null}
      <p className="text-sm">
        <Link
          to="/updates"
          className="tap-y relative text-primary underline-offset-2 hover:underline"
        >
          {t("transparency.changes.toUpdates")}
        </Link>
      </p>
    </Block>
  );
}
