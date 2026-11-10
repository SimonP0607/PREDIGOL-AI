/**
 * Inicio in two layers (closing plan 3.2; plan UX, section 24 and 38). **Para ti** is what the reader chose to follow -
 * and only when they chose something; **PrediGol** is the same for everyone: the day's picks, the parlays, the featured
 * matches. Nothing is hidden: a reader with no favourites sees the whole of PrediGol, and the leagues and the
 * team PrediGol suggests until they choose are PrediGol's - never «tuyas».
 *
 * Where the blocks that read the common board go depends on what the reader's leagues and teams are: theirs (they chose some)
 * - the matches, the news, what is at stake and the results sit in «Para ti» - or the suggested ones, which sit in PrediGol,
 * labelled as suggested. Pure: the two answers are arguments.
 */
import type { MeToday } from "@/lib/api/v1/types_me_today";
import type { Today } from "@/lib/api/v1/types_today";
import { suggestedView } from "./today";

export interface Layers {
  /** «Para ti» shows: the reader chose a league, a team, a player or a market. */
  forYou: boolean;
  /** Their leagues and teams are their own: the board's blocks (matches, news, what is at stake, results) belong to «Para ti». */
  mine: boolean;
  /** The discreet «Elige tus favoritos»: only once /me/today says they chose nothing, and personalisation is on. */
  prompt: boolean;
}

/**
 * While /me/today has not answered, the board's own word stands in (a reader with leagues or teams of their own has «Para ti»
 * already) - and the prompt waits, so a reader with favourites is never asked to choose them.
 */
export function layersOf(me: MeToday | undefined, today: Today | undefined): Layers {
  const own = today ? !suggestedView(today) : false;
  const forYou = me ? me.chosen : own;
  return {
    forYou,
    mine: forYou && own,
    prompt: me !== undefined && !me.chosen && me.personalization,
  };
}

/** How long a reader's page waits to know its layers before it paints without them: a slow answer is never waited for longer. */
export const LAYERS_HOLD_MS = 1500;

/**
 * Whether a reader's page still holds back its blocks. «Para ti» and, without favourites, «Elige tus favoritos» go on top of
 * PrediGol, so when they arrive after PrediGol is painted they push it down - on a phone, a layout shift far over the web
 * vitals' «good» line (0.1) with favourites and close to it without. The day's picks (/daily) and the board (/home) change
 * height when they arrive too (the skeleton of the picks is taller than «no picks today»), and the blocks under them climb into
 * the first screen of a tablet or a desktop: 0.11 to 0.22 without favourites. The page waits for the four answers (never longer
 * than `LAYERS_HOLD_MS`) and paints the layers and the blocks together. Only a reader is held: the owner's account has no
 * /me/today and paints as it always did. Pure: the clock is the caller's.
 */
export function holdsLayers(state: {
  reader: boolean;
  mePending: boolean;
  todayPending: boolean;
  homePending: boolean;
  boardPending: boolean;
  expired: boolean;
}): boolean {
  return (
    state.reader &&
    !state.expired &&
    (state.mePending || state.todayPending || state.homePending || state.boardPending)
  );
}
