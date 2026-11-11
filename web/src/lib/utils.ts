import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge does not know the design system's own type scale (src/styles.css
 * `@utility text-caption` & co.), so by default it read `text-caption` as a COLOUR and
 * dropped it whenever a real text colour followed: `cn("text-caption text-muted-foreground")`
 * kept only the colour and the text rendered at body size. Registering them as font sizes
 * fixes every component at once.
 */
/**
 * The names of styles.css's own text sizes and radii. A size added there and not here is the bug of UX-100 again:
 * `text-micro` was missing, so some 88 pills and counts lost it next to a colour and took the body's size.
 * utils.test.ts reads styles.css and fails when the two lists differ.
 */
export const TEXT_SIZES = [
  "display",
  "heading",
  "subheading",
  "title",
  "body",
  "small",
  "label",
  "overline",
  "micro",
  "caption",
  "figure",
  "figure-xl",
] as const;
export const RADII = ["chip", "field", "control", "card", "feature", "sheet"] as const;

const twMerge = extendTailwindMerge({
  extend: {
    theme: { radius: [...RADII] },
    classGroups: {
      "font-size": [{ text: [...TEXT_SIZES] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
