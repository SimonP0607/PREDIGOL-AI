/** The line chips of a total in «Probabilidades» (plan EA, EA-202). */

/** At most `size` lines around the one shown, so the chip of the selected line is always on screen (FE-003). */
export function lineWindow(lines: readonly number[], current: number, size = 8): number[] {
  if (lines.length <= size) return [...lines];
  const at = Math.max(0, lines.indexOf(current));
  const start = Math.min(Math.max(0, at - Math.floor(size / 2)), lines.length - size);
  return lines.slice(start, start + size);
}
