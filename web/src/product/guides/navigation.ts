/**
 * The cards of a guide and how to walk them (plan UX-051): the welcome card, when the guide has one, is the card 0 the API
 * records; a step whose element is not on the screen is left out, going forward or back.
 */
import type { GuideDef, StepDef } from "./registry";
import { resolvable } from "./anchors";

export const WELCOME: StepDef = { id: "welcome", anchors: [] };

export function cardsOf(def: GuideDef): readonly StepDef[] {
  return def.welcome ? [WELCOME, ...def.steps] : def.steps;
}

/** The nearest card from `from` in a direction (+1 or -1) that can be shown, or null when there is none. */
export function neighbour(
  def: GuideDef,
  from: number,
  dir: 1 | -1,
  find?: (anchors: readonly string[]) => unknown,
): number | null {
  const cards = cardsOf(def);
  for (let i = from + dir; i >= 0 && i < cards.length; i += dir) {
    const card = cards[i];
    if (card && resolvable(card, find)) return i;
  }
  return null;
}

/** The first card at or after `from` that can be shown. */
export function firstFrom(
  def: GuideDef,
  from: number,
  find?: (anchors: readonly string[]) => unknown,
): number | null {
  const cards = cardsOf(def);
  const card = cards[from];
  if (card && resolvable(card, find)) return from;
  return neighbour(def, from, 1, find);
}

/** The numbered steps that can be shown now (the welcome card is not one), for «Paso n de total». */
export function numbered(def: GuideDef, find?: (anchors: readonly string[]) => unknown): number[] {
  const cards = cardsOf(def);
  const out: number[] = [];
  cards.forEach((card, i) => {
    if (card.id !== WELCOME.id && resolvable(card, find)) out.push(i);
  });
  return out;
}
