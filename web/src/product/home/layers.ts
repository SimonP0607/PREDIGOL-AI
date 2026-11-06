/**
 * Inicio in two layers (closing plan 3.2; plan UX, section 24 and 38). **Para ti** is what the reader chose to follow -
 * and only when they chose something; **PrediGol** is the same for everyone: the day's picks, the parlays, the featured
 * matches, the best prices. Nothing is hidden: a reader with no favourites sees the whole of PrediGol, and the leagues and the
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
