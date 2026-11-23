/** Cuotas «Por partido» on the API (UX-141): the view by match over the explorer's own data layer. Its own chunk. */
import type { ReactNode } from "react";
import { API_EXPLORER_DATA } from "../explorer/apiData";
import type { DayKey } from "../explorer/model";
import { ByMatchView } from "./ByMatchView";

export function ByMatchScreen({
  modeSwitch,
  day,
  onDay,
}: {
  modeSwitch?: ReactNode;
  /** The day of the URL (`h`), and how a choice writes it back (AP-C01). */
  day?: DayKey;
  onDay?: (day: DayKey) => void;
}) {
  return (
    <ByMatchView
      data={API_EXPLORER_DATA}
      modeSwitch={modeSwitch}
      {...(day ? { day } : {})}
      {...(onDay ? { onDay } : {})}
    />
  );
}
