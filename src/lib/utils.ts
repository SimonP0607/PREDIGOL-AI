import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge does not know the design system's own type scale (src/styles.css
 * `@utility text-caption` & co.), so by default it read `text-caption` as a COLOUR and
 * dropped it whenever a real text colour followed: `cn("text-caption text-muted-foreground")`
 * kept only the colour and the text rendered at body size. Registering them as font sizes
 * fixes every component at once.
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["caption", "label", "title", "heading", "display"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
