/** The tie a match is a leg of, under the score in the header: the aggregate and, once it is over, who went through. */
import type { TieView } from "./tie";

export function TieLines({ view }: { view: TieView }) {
  if (!view.score && !view.outcome) return null;
  return (
    <div className="mt-1.5 flex flex-col items-center gap-0.5 text-center" data-testid="match-tie">
      {view.score ? (
        <span
          className="numeric text-caption font-semibold text-foreground"
          data-testid="tie-score"
        >
          {view.score}
        </span>
      ) : null}
      {view.outcome ? (
        <span
          className="max-w-[12rem] break-words text-caption leading-snug text-muted-foreground"
          data-testid="tie-outcome"
        >
          {view.outcome}
        </span>
      ) : null}
    </div>
  );
}
