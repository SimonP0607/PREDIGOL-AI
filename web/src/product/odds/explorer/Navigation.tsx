/**
 * The two levels: the family tabs (seven at most and «Más», each with its number of matches) and the market chips of the
 * tab, both strips that scroll sideways on a phone. The tabs are a real tab list: arrow keys, Home and End move between them.
 */
import { Fragment, useRef, type KeyboardEvent } from "react";
import { t } from "@/lib/i18n";
import { fmtInt } from "@/lib/i18n/format";
import { useScrollCue } from "@/lib/scrollCue";
import { cn } from "@/lib/utils";
import { prefersReducedMotion } from "@/product/shared/motion";
import { chipTitle, familyName } from "./markets";
import { tabId, tabName, type ExplorerTab, type TabKey, type TabMarket } from "./tabs";
import { Chip, Strip } from "./ui";

export function FamilyTabs({
  tabs,
  active,
  onChoose,
  panelId,
}: {
  tabs: readonly ExplorerTab[];
  active: TabKey;
  onChoose: (key: TabKey) => void;
  panelId: string;
}) {
  const bar = useRef<HTMLDivElement>(null);
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  useScrollCue(bar);

  function go(index: number) {
    const tab = tabs[index];
    if (!tab) return;
    onChoose(tab.key);
    const el = buttons.current[index];
    el?.focus();
    el?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
      behavior: prefersReducedMotion() ? "auto" : "smooth",
    });
  }

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const i = tabs.findIndex((x) => x.key === active);
    const last = tabs.length - 1;
    const next =
      e.key === "ArrowRight"
        ? i >= last
          ? 0
          : i + 1
        : e.key === "ArrowLeft"
          ? i <= 0
            ? last
            : i - 1
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? last
              : null;
    if (next === null) return;
    e.preventDefault();
    go(next);
  }

  return (
    <div
      ref={bar}
      role="tablist"
      aria-label={t("explorer.tabsLabel")}
      onKeyDown={onKeyDown}
      data-testid="explorer-tabs"
      className="scroll-strip flex gap-1 rounded-xl border border-border bg-card p-1"
    >
      {tabs.map((tab, i) => {
        const on = tab.key === active;
        return (
          <button
            key={tab.key}
            ref={(el) => {
              buttons.current[i] = el;
            }}
            id={tabId(tab.key)}
            type="button"
            role="tab"
            aria-selected={on}
            aria-controls={panelId}
            tabIndex={on ? 0 : -1}
            onClick={() => onChoose(tab.key)}
            data-testid={`explorer-tab-${tab.key}`}
            className={cn(
              "tap-y relative inline-flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 text-[0.8125rem] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring md:text-sm",
              on
                ? "bg-elevated text-foreground shadow-sm ring-1 ring-border-strong"
                : "text-muted-foreground hover:bg-elevated/50 hover:text-foreground",
            )}
          >
            {tabName(tab.key)}
            <span
              aria-hidden
              className="numeric rounded-full bg-background/60 px-1.5 text-micro text-subtle-foreground"
            >
              {fmtInt(tab.fixtures)}
            </span>
            <span className="sr-only">{t("explorer.tabCount", { count: tab.fixtures })}</span>
          </button>
        );
      })}
    </div>
  );
}

/** The tab's markets; «Más» names the family before its first chip (shots, goalkeepers, specials...). */
export function MarketChips({
  tab,
  active,
  onChoose,
}: {
  tab: ExplorerTab;
  active: string;
  onChoose: (market: TabMarket) => void;
}) {
  return (
    <Strip label={t("explorer.marketsLabel", { tab: tabName(tab.key) })} testId="explorer-markets">
      {tab.markets.map((m, i) => {
        const groupStart = tab.key === "more" && tab.markets[i - 1]?.family !== m.family;
        return (
          <Fragment key={m.key}>
            {groupStart ? (
              <span
                aria-hidden
                className={cn(
                  "shrink-0 text-label text-subtle-foreground",
                  i > 0 && "ml-2 border-l border-border pl-3",
                )}
              >
                {familyName(m.family)}
              </span>
            ) : null}
            <Chip
              on={m.key === active}
              onClick={() => onChoose(m)}
              testId={`explorer-market-${m.key}`}
              title={tab.key === "more" ? familyName(m.family) : undefined}
            >
              {chipTitle(m.info, m.own)}
            </Chip>
          </Fragment>
        );
      })}
    </Strip>
  );
}
