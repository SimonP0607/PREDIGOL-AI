/**
 * ResponsiveContainer (recharts 2) sized its DIRECT child by cloning it with
 * width and height; recharts 3 hands the size down through context instead, so a
 * wrapper component renders in both. The two props stay optional and are passed
 * on when they are given (FE-001 checked the charts render the same in 3.10).
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
