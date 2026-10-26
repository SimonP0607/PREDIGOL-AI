/**
 * One block of the account centre (plan UX, B1; section 21): a card with its title and, folded, the one line it says;
 * the header is a button (aria-expanded) that opens and closes it by finger, mouse or keyboard. Folded by default under
 * 1024 px - a phone sees the eight lines at once - and open at a desk; the block an address names (#privacy) opens and
 * comes into view. Its content mounts only once open: a folded block reads nothing.
 */
import { useId, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Card } from "@/product/shared/States";
import type { BlockKey } from "./centre";

export function Block({
  id,
  icon,
  title,
  summary,
  open,
  onToggle,
  children,
}: {
  id: BlockKey;
  icon: ReactNode;
  title: string;
  /** The line it says folded (null while the summary loads or could not be read). */
  summary: string | null;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const head = useId();
  const panel = useId();
  return (
    <section
      id={id}
      className="scroll-mt-20"
      data-testid={`profile-block-${id}`}
      data-open={open ? "true" : "false"}
    >
      <Card as="div" className="overflow-hidden p-0">
        <h2 className="m-0">
          <button
            type="button"
            id={head}
            aria-expanded={open}
            aria-controls={panel}
            onClick={onToggle}
            data-testid={`profile-toggle-${id}`}
            className="flex min-h-14 w-full items-start gap-3 px-5 py-4 text-left transition-colors hover:bg-elevated/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          >
            <span aria-hidden className="mt-0.5 shrink-0 text-primary">
              {icon}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block font-display text-base font-semibold">{title}</span>
              {!open && summary ? (
                <span
                  className="mt-0.5 block break-words text-xs text-muted-foreground"
                  data-testid={`profile-summary-${id}`}
                >
                  {summary}
                </span>
              ) : null}
            </span>
            <ChevronDown
              aria-hidden
              className={cn(
                "mt-0.5 h-5 w-5 shrink-0 text-muted-foreground transition-transform",
                open && "rotate-180",
              )}
            />
          </button>
        </h2>
        <div
          id={panel}
          role="region"
          aria-labelledby={head}
          hidden={!open}
          className="border-t border-border px-5 pb-5 pt-4"
          data-testid={`profile-panel-${id}`}
        >
          {open ? children : null}
        </div>
      </Card>
    </section>
  );
}
