/**
 * The kinds of story the address and the page share (plan de correcciones UX, AP-N01/N03). Apart from `stories.ts` so the route,
 * which reads the address, does not pull the words of the news pages into the first visit's JS.
 */
import type { StoryCategory } from "@/lib/api/v1/types_stories";

/** The categories in the order the front page lists them (maqueta 08). */
export const CATEGORY_ORDER: readonly StoryCategory[] = [
  "colombia",
  "internacional",
  "selecciones",
  "fichajes",
  "bajas_y_sanciones",
  "declaraciones",
  "resultados_y_proximos",
  "competiciones",
];
