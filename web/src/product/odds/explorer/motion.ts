/**
 * The explorer's motion (plan Cuotas, section 5), CSS only: every class is `motion-safe:`, so with «reduce motion» a change
 * is instant and only the arrows remain. Nothing beyond the CSS the product already loads (tw-animate-css).
 */
export const MOTION = {
  /** Another family or market: a fade and an 8 px rise, 200 ms, ease-out. */
  swap: "motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-200 motion-safe:ease-out",
  /** A panel opening or closing (comparison, movement, «Ver todas»): height and opacity, 220 ms. */
  open: "overflow-hidden motion-safe:data-[state=open]:animate-collapsible-down motion-safe:data-[state=closed]:animate-collapsible-up motion-safe:duration-[220ms]",
  openFade: "motion-safe:animate-in motion-safe:fade-in motion-safe:duration-[220ms]",
  /** A price tapped: 100 ms down to .97 (its tick says it went in, with or without motion). */
  press:
    "motion-safe:transition-transform motion-safe:duration-100 motion-safe:active:scale-[0.97]",
  /** A price that changed: one 300 ms tint, never drawn with «reduce motion» (its arrow says it). */
  tint: "pointer-events-none absolute inset-0 rounded-[inherit] bg-info/25 motion-safe:animate-out motion-safe:fade-out motion-safe:duration-300 motion-safe:fill-mode-forwards motion-reduce:hidden",
  /** Results while the next answer loads: dimmed in 150 ms. */
  dim: "motion-safe:transition-opacity motion-safe:duration-150",
  /** The progress bar of filters being applied: in from the left in 150 ms. */
  progress: "motion-safe:animate-in motion-safe:slide-in-from-left-full motion-safe:duration-150",
} as const;

/** Every animated class of the explorer runs only without «reduce motion». */
export function onlyWithMotion(classes: string): boolean {
  const animated =
    /(^|:)(animate-|transition|duration-|ease-|fade-|slide-|zoom-|scale-|fill-mode-)/;
  return classes
    .split(/\s+/)
    .filter((c) => animated.test(c))
    .every((c) => c.startsWith("motion-safe:"));
}
