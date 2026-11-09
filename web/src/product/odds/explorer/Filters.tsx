/**
 * Search, filters and order (plan Cuotas, section 5). One search for teams, competitions AND markets: «córners» or
 * «goleador» offers those markets, and Enter jumps to the first. The filters - «Empiezan en», country, competition, bookmaker
 * (only those present), a price range, a minimum of bookmakers, «Solo con cuota justa», «Mis equipos y ligas» - sit in a row
 * from 640 px, where a change applies at once; on a phone, in a sheet whose «Aplicar» applies them together.
 */
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { BookOpen, Globe2, Layers3, SlidersHorizontal, Trophy } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { FacetPicker, SearchBox } from "@/product/matches/Filters";
import { sortLabel, windowLabel, type FilterOptions } from "./filterOptions";
import type { BoardSort } from "./model";
import {
  NO_FILTERS,
  SORTS,
  WINDOWS,
  activeFilters,
  normalizeOdds,
  type ExplorerFilters,
} from "./state";
import { searchMarkets, tabName, type ExplorerTab, type MarketHit } from "./tabs";
import { Chip, Strip, ToggleChip } from "./ui";

const MIN_BOOKS: readonly number[] = [2, 3, 5, 8];

// ── the search ────────────────────────────────────────────────────────────────────────────────────────────────────────

/**
 * The search box: names of teams and competitions filter the board (after a short pause), names of markets are offered as
 * jumps instead - typing «córners» never empties the board looking for a team called so.
 */
export function ExplorerSearch({
  value,
  tabs,
  onQuery,
  onJump,
}: {
  value: string;
  tabs: readonly ExplorerTab[];
  onQuery: (q: string) => void;
  onJump: (hit: MarketHit) => void;
}) {
  const [draft, setDraft] = useState(value);
  // What this box last sent: a value that differs came from another hand (a cleared filter, «atrás») and the box follows
  // it - never its own answer arriving while the reader goes on typing.
  const sent = useRef(value);
  useEffect(() => {
    if (value !== sent.current) {
      sent.current = value;
      setDraft(value);
    }
  }, [value]);
  const hits = useMemo(() => searchMarkets(tabs, draft), [tabs, draft]);
  const markets = hits.length > 0;
  const send = useCallback(
    (q: string) => {
      sent.current = q;
      onQuery(q);
    },
    [onQuery],
  );
  useEffect(() => {
    if (draft === sent.current || (markets && draft.trim() !== "")) return;
    const timer = setTimeout(() => send(draft), 350);
    return () => clearTimeout(timer);
  }, [draft, markets, send]);

  function jumpTo(hit: MarketHit) {
    setDraft("");
    sent.current = "";
    onJump(hit);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const first = hits[0];
    if (first) jumpTo(first);
    else send(draft);
  }

  return (
    <div className="min-w-0 flex-1 space-y-1.5">
      <form role="search" onSubmit={submit} className="flex min-w-0">
        <SearchBox
          value={draft}
          onChange={setDraft}
          placeholder={t("explorer.search.placeholder")}
          label={t("explorer.search.label")}
          testId="explorer-search"
          className="lg:w-96"
        />
      </form>
      {markets ? (
        <div
          role="group"
          aria-label={t("explorer.search.markets")}
          data-testid="explorer-search-markets"
          className="flex flex-wrap items-center gap-1.5"
        >
          <span className="text-caption text-muted-foreground">{t("explorer.search.goTo")}</span>
          {hits.map((h) => (
            <button
              key={`${h.tab}|${h.market.key}`}
              type="button"
              onClick={() => jumpTo(h)}
              data-testid="explorer-search-hit"
              className="tap-y relative inline-flex min-h-8 items-center gap-1 rounded-full border border-primary/40 bg-primary/10 px-3 text-xs font-semibold text-primary hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="font-normal text-muted-foreground">{tabName(h.tab)} ›</span>
              {h.title}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ── the fields, drawn in the row and in the sheet ─────────────────────────────────────────────────────────────────────

/** A price bound typed as text: it is read when it is left (or Enter), so the board does not reload at every key. */
function OddsField({
  label,
  value,
  onCommit,
  testId,
}: {
  label: string;
  value: string | null;
  onCommit: (v: string | null) => void;
  testId: string;
}) {
  const id = useId();
  const [text, setText] = useState(value ?? "");
  useEffect(() => setText(value ?? ""), [value]);
  const commit = () => {
    const next = normalizeOdds(text);
    setText(next ?? "");
    if (next !== value) onCommit(next);
  };
  return (
    <label htmlFor={id} className="flex min-w-0 items-center gap-1.5">
      <span className="shrink-0 text-caption text-muted-foreground">{label}</span>
      <input
        id={id}
        type="text"
        inputMode="decimal"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
        placeholder="—"
        maxLength={7}
        data-testid={testId}
        className="numeric h-9 w-16 rounded-md border border-border bg-card px-2 text-sm tabular-nums focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:h-11"
      />
    </label>
  );
}

function FilterFields({
  value,
  sort,
  options,
  onChange,
  onSort,
  sheet = false,
}: {
  value: ExplorerFilters;
  sort: BoardSort;
  options: FilterOptions;
  onChange: (patch: Partial<ExplorerFilters>) => void;
  onSort: (sort: BoardSort) => void;
  sheet?: boolean;
}) {
  const competitions = options.competitions.filter(
    (c) => value.country === null || c.country === value.country,
  );
  const field = (label: string, control: ReactNode) =>
    sheet ? (
      <div className="grid min-w-0 gap-1.5">
        <span aria-hidden className="text-sm font-medium text-muted-foreground">
          {label}
        </span>
        {control}
      </div>
    ) : (
      control
    );
  return (
    <>
      {field(
        t("explorer.filters.window"),
        <Strip label={t("explorer.filters.window")} testId="explorer-window">
          {!sheet ? (
            <span aria-hidden className="shrink-0 text-label text-subtle-foreground">
              {t("explorer.filters.window")}
            </span>
          ) : null}
          {WINDOWS.map((w) => (
            <Chip key={String(w)} on={value.window === w} onClick={() => onChange({ window: w })}>
              {windowLabel(w)}
            </Chip>
          ))}
        </Strip>,
      )}
      {field(
        t("explorer.filters.country"),
        <FacetPicker<string>
          label={t("explorer.filters.country")}
          anyLabel={t("explorer.filters.allCountries")}
          emptyText={sheet ? t("explorer.filters.allCountries") : undefined}
          value={value.country}
          options={options.countries}
          onChange={(country) => onChange({ country, competition: null })}
          icon={<Globe2 />}
          testId="explorer-country"
        />,
      )}
      {field(
        t("explorer.filters.competition"),
        <FacetPicker<string>
          label={t("explorer.filters.competition")}
          anyLabel={t("explorer.filters.allCompetitions")}
          emptyText={sheet ? t("explorer.filters.allCompetitions") : undefined}
          value={value.competition === null ? null : String(value.competition)}
          options={competitions}
          onChange={(c) => onChange({ competition: c === null ? null : Number(c) })}
          icon={<Trophy />}
          testId="explorer-competition"
        />,
      )}
      {field(
        t("explorer.filters.bookmaker"),
        <FacetPicker<string>
          label={t("explorer.filters.bookmaker")}
          anyLabel={t("explorer.filters.allBookmakers")}
          emptyText={sheet ? t("explorer.filters.allBookmakers") : undefined}
          value={value.bookmaker === null ? null : String(value.bookmaker)}
          options={options.bookmakers}
          onChange={(b) => onChange({ bookmaker: b === null ? null : Number(b) })}
          icon={<BookOpen />}
          testId="explorer-bookmaker"
        />,
      )}
      {field(
        t("explorer.filters.minBooks"),
        <FacetPicker<string>
          label={t("explorer.filters.minBooks")}
          anyLabel={t("explorer.filters.anyBooks")}
          emptyText={sheet ? t("explorer.filters.anyBooks") : undefined}
          value={value.minBooks === null ? null : String(value.minBooks)}
          options={MIN_BOOKS.map((n) => ({
            key: String(n),
            label: t("explorer.filters.booksAtLeast", { count: n }),
          }))}
          onChange={(n) => onChange({ minBooks: n === null ? null : Number(n) })}
          icon={<Layers3 />}
          testId="explorer-min-books"
        />,
      )}
      {field(
        t("explorer.filters.range"),
        <div
          role="group"
          aria-label={t("explorer.filters.range")}
          className="flex items-center gap-2"
        >
          <OddsField
            label={t("explorer.filters.from")}
            value={value.oddsMin}
            onCommit={(oddsMin) => onChange({ oddsMin })}
            testId="explorer-odds-min"
          />
          <OddsField
            label={t("explorer.filters.to")}
            value={value.oddsMax}
            onCommit={(oddsMax) => onChange({ oddsMax })}
            testId="explorer-odds-max"
          />
        </div>,
      )}
      <div className="flex flex-wrap items-center gap-2">
        <ToggleChip
          on={value.fairOnly}
          onChange={(fairOnly) => onChange({ fairOnly })}
          testId="explorer-fair-only"
        >
          {t("explorer.filters.fairOnly")}
        </ToggleChip>
        {options.follow ? (
          <ToggleChip
            on={value.mine}
            onChange={(mine) => onChange({ mine })}
            testId="explorer-mine"
          >
            {t("explorer.filters.mine")}
          </ToggleChip>
        ) : null}
      </div>
      {field(
        t("explorer.sort.label"),
        <Strip label={t("explorer.sort.label")} testId="explorer-sort">
          {!sheet ? (
            <span aria-hidden className="shrink-0 text-label text-subtle-foreground">
              {t("explorer.sort.label")}
            </span>
          ) : null}
          {SORTS.map((s) => (
            <Chip key={s} on={sort === s} onClick={() => onSort(s)}>
              {sortLabel(s)}
            </Chip>
          ))}
        </Strip>,
      )}
    </>
  );
}

/** From 640 px: the filters in the page's own row; each change applies at once. */
export function FiltersRow({
  value,
  sort,
  options,
  onChange,
  onSort,
  onClear,
}: {
  value: ExplorerFilters;
  sort: BoardSort;
  options: FilterOptions;
  onChange: (patch: Partial<ExplorerFilters>) => void;
  onSort: (sort: BoardSort) => void;
  onClear: () => void;
}) {
  return (
    <div
      className="hidden flex-wrap items-center gap-x-3 gap-y-2 sm:flex"
      data-testid="explorer-filters-row"
    >
      <FilterFields
        value={value}
        sort={sort}
        options={options}
        onChange={onChange}
        onSort={onSort}
      />
      {activeFilters(value) > 0 ? (
        <button
          type="button"
          onClick={onClear}
          data-testid="explorer-clear"
          className="tap relative ml-auto inline-flex min-h-9 items-center text-xs font-medium text-primary hover:underline"
        >
          {t("explorer.filters.clear")}
        </button>
      ) : null}
    </div>
  );
}

/**
 * A phone: «Filtros» opens a sheet from the bottom with every filter and the order; nothing changes behind it until
 * «Aplicar» (the board would reload under the reader's thumb at each tap otherwise).
 */
export function FiltersSheet({
  value,
  sort,
  options,
  onApply,
}: {
  value: ExplorerFilters;
  sort: BoardSort;
  options: FilterOptions;
  onApply: (filters: ExplorerFilters, sort: BoardSort) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const [draftSort, setDraftSort] = useState(sort);
  const active = activeFilters(value);
  const drafted = activeFilters(draft);
  const openWith = (next: boolean) => {
    if (next) {
      setDraft(value);
      setDraftSort(sort);
    }
    setOpen(next);
  };
  return (
    <Sheet open={open} onOpenChange={openWith}>
      <SheetTrigger asChild>
        <button
          type="button"
          data-testid="explorer-filters-open"
          className={cn(
            "tap-y relative inline-flex h-10 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[0.8125rem] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:hidden",
            active > 0
              ? "border-primary/45 bg-primary/12 text-primary"
              : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
          )}
        >
          <SlidersHorizontal aria-hidden className="h-4 w-4" />
          {t("explorer.filters.open")}
          {active > 0 ? (
            <>
              <span
                aria-hidden
                className="numeric inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-xs font-semibold text-primary-foreground"
              >
                {active}
              </span>
              <span className="sr-only">{t("explorer.filters.active", { count: active })}</span>
            </>
          ) : null}
        </button>
      </SheetTrigger>
      <SheetContent
        side="bottom"
        closeLabel={t("common.close")}
        data-testid="explorer-filters-sheet"
        className="mx-auto flex max-h-[88dvh] max-w-2xl flex-col gap-0 rounded-t-2xl p-0 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)]"
      >
        <SheetHeader className="px-4 pb-1 pr-14 pt-4 text-left">
          <SheetTitle className="font-display text-base">{t("explorer.filters.title")}</SheetTitle>
          <SheetDescription className="text-caption">
            {drafted > 0
              ? t("explorer.filters.active", { count: drafted })
              : t("explorer.filters.description")}
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
          <FilterFields
            value={draft}
            sort={draftSort}
            options={options}
            onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))}
            onSort={setDraftSort}
            sheet
          />
        </div>
        <div className="flex gap-2 border-t border-border px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pt-3">
          <button
            type="button"
            onClick={() => setDraft({ ...NO_FILTERS, window: draft.window })}
            disabled={drafted === 0}
            data-testid="explorer-filters-reset"
            className="min-h-11 flex-1 rounded-lg border border-border-strong px-3 text-sm font-medium transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          >
            {t("explorer.filters.clear")}
          </button>
          <button
            type="button"
            onClick={() => {
              onApply(draft, draftSort);
              setOpen(false);
            }}
            data-testid="explorer-filters-apply"
            className="min-h-11 flex-[2] rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t("explorer.filters.apply")}
          </button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
