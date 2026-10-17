/**
 * ResponsiveContainer (recharts 2) sizes its DIRECT child by cloning it with
 * width and height. A chart written as a wrapper component must take those
 * two props and hand them to the recharts root - without them the chart
 * renders nothing at all.
 */
export interface ChartSize {
  width?: number | undefined;
  height?: number | undefined;
}

/** The injected size as props, leaving out what was not injected. */
export function sized({ width, height }: ChartSize): { width?: number; height?: number } {
  return {
    ...(width === undefined ? {} : { width }),
    ...(height === undefined ? {} : { height }),
  };
}
