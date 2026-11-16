/**
 * The search's door in the top bar (UX-153): a 44 px button with the magnifier, in every width, and the keys «/» and
 * Ctrl/⌘ K. The layer itself loads the first time it is opened. Only drawn while FBI_SEARCH is on (the shell decides).
 *
 * The maqueta shows a field at 1280 px and up; with the unified bar (D-02) the pills fill that row up to the bell, so the
 * field stays a button at every width - the same door, never a second one.
 */
import { lazy, Suspense, useEffect, useState } from "react";
import { Search } from "lucide-react";
import { t } from "@/lib/i18n";
import { isTyping, opensSearch } from "./model";

const ReaderSearch = lazy(() => import("./ReaderSearch"));

export function SearchButton({ news = false }: { news?: boolean }) {
  const [open, setOpen] = useState(false);
  const [used, setUsed] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!opensSearch(e, isTyping(e.target))) return;
      e.preventDefault();
      setUsed(true);
      setOpen((o) => (e.key === "/" ? true : !o));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setUsed(true);
          setOpen(true);
        }}
        aria-label={t("nav.search.open")}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-keyshortcuts="/ Control+K Meta+K"
        title={t("nav.search.openHint")}
        data-testid="search-open"
        className="motion-press relative inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-full text-muted-foreground hover:bg-elevated hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      >
        <Search aria-hidden className="h-5 w-5" />
      </button>
      {used ? (
        <Suspense fallback={null}>
          <ReaderSearch open={open} onOpenChange={setOpen} news={news} />
        </Suspense>
      ) : null}
    </>
  );
}
