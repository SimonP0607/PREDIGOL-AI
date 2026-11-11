/**
 * The place of a picture («Noche de partido», the system's sheet 6: the nine generated images, A-01 to A-09). The
 * place is kept before the picture arrives - its proportions are the box's, so nothing below it moves (CLS) - and it is
 * never empty: behind the picture, or instead of it while there is none or it fails to load, the scene drawn with CSS
 * that the rest of the product uses. A picture here is atmosphere, never information: `alt` is empty unless the page
 * gives one, it loads lazily and off the critical path, and no figure is ever drawn over it.
 */
import { useState } from "react";
import { cn } from "@/lib/utils";

export const IMAGE_RATIOS = {
  /** A-01, the stadium's scene */
  scene: "16 / 10",
  /** A-04 to A-07, an empty state */
  empty: "3 / 2",
  /** A-08, the welcome */
  portrait: "4 / 5",
  /** A-09, Transparencia */
  wide: "21 / 9",
} as const;

export type ImageRatio = keyof typeof IMAGE_RATIOS;

export function ImageSlot({
  src,
  sources,
  alt = "",
  ratio,
  width,
  height,
  priority = false,
  className,
  testId,
}: {
  /** The picture's address (the fallback format); nothing while the picture does not exist. */
  src?: string | undefined;
  /** Lighter formats first: AVIF, then WebP. */
  sources?: ReadonlyArray<{ srcSet: string; type: string }> | undefined;
  alt?: string;
  ratio: ImageRatio;
  /** The picture's own size, for the browser to reserve it. */
  width?: number | undefined;
  height?: number | undefined;
  /** Only for the one picture at the top of a page that is its largest content. */
  priority?: boolean;
  className?: string | undefined;
  testId?: string | undefined;
}) {
  const [failed, setFailed] = useState(false);
  const shown = Boolean(src) && !failed;
  return (
    <div
      data-testid={testId}
      data-image={shown ? "picture" : "scene"}
      style={{ aspectRatio: IMAGE_RATIOS[ratio] }}
      className={cn("surface-pitch relative w-full overflow-hidden rounded-card", className)}
    >
      {/* the scene behind: the pitch's chalk under the floodlight, as everywhere else */}
      <span aria-hidden className="scene scene-touchline" style={{ height: "100%" }} />
      {shown ? (
        <picture>
          {sources?.map((s) => (
            <source key={s.type} srcSet={s.srcSet} type={s.type} />
          ))}
          <img
            src={src}
            alt={alt}
            width={width}
            height={height}
            loading={priority ? "eager" : "lazy"}
            decoding="async"
            draggable={false}
            onError={() => setFailed(true)}
            className="absolute inset-0 h-full w-full select-none object-cover"
          />
        </picture>
      ) : null}
    </div>
  );
}
