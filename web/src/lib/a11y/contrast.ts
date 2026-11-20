/**
 * The contrast of the system's tokens, measured from `styles.css` itself (plan PM, PM-14-01 and PM-10-06): a test can say «this
 * text on this surface reads at 4.5:1» without a browser. OKLCH → sRGB as CSS Color 4 does it; a colour with alpha is blended over
 * its ground in gamma-encoded sRGB, as browsers paint it. Pure; used by tests only.
 */

export type Rgb = readonly [number, number, number];
export interface Colour {
  rgb: Rgb;
  alpha: number;
}

const OKLCH = /oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*(?:\/\s*([\d.]+)(%?))?\s*\)/;

function gamma(c: number): number {
  const v = Math.min(1, Math.max(0, c));
  return v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
}

function linear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/** An `oklch(L C h [/ a])` value as gamma-encoded sRGB (0-1) and its alpha. */
export function parseOklch(value: string): Colour {
  const m = OKLCH.exec(value);
  if (!m) throw new Error(`not an oklch() colour: ${value}`);
  const [L, C, h] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const alpha = m[4] === undefined ? 1 : Number(m[4]) / (m[5] === "%" ? 100 : 1);
  const a = C * Math.cos((h * Math.PI) / 180);
  const b = C * Math.sin((h * Math.PI) / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const mm = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb: Rgb = [
    gamma(4.0767416621 * l - 3.3077115913 * mm + 0.2309699292 * s),
    gamma(-1.2684380046 * l + 2.6097574011 * mm - 0.3413193965 * s),
    gamma(-0.0041960863 * l - 0.7034186147 * mm + 1.707614701 * s),
  ];
  return { rgb, alpha };
}

/** A translucent colour painted over an opaque ground. */
export function over(top: Colour, ground: Rgb): Rgb {
  const a = top.alpha;
  return [0, 1, 2].map((i) => top.rgb[i]! * a + ground[i]! * (1 - a)) as unknown as Rgb;
}

export function luminance(rgb: Rgb): number {
  return 0.2126 * linear(rgb[0]) + 0.7152 * linear(rgb[1]) + 0.0722 * linear(rgb[2]);
}

/** WCAG 2 contrast ratio of two opaque colours (1 to 21). */
export function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** The `:root` custom properties of a stylesheet that are `oklch()` colours, by name without the leading `--`. */
export function rootTokens(css: string): Record<string, Colour> {
  const root = /:root\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? "";
  const out: Record<string, Colour> = {};
  for (const m of root.matchAll(/--([\w-]+):\s*(oklch\([^)]*\))/g)) {
    out[m[1]!] = parseOklch(m[2]!);
  }
  return out;
}
