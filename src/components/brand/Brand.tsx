/** The PrediGol crest and wordmark. The crest is the brand's main asset (public/brand). */
import { cn } from "@/lib/utils";

export function BrandMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <img
      src="/brand/predigol-mark-64.png"
      srcSet="/brand/predigol-mark-64.png 1x, /brand/predigol-mark-128.png 2x"
      width={size}
      height={size}
      alt="PrediGol"
      decoding="async"
      className={cn("shrink-0 select-none object-contain", className)}
      draggable={false}
    />
  );
}

export function Wordmark({
  className,
  tagline,
}: {
  className?: string;
  tagline?: string | undefined;
}) {
  return (
    <span className={cn("flex min-w-0 flex-col leading-none", className)}>
      <span className="font-display text-[1.05rem] font-bold tracking-tight">
        <span className="text-foreground">Predi</span>
        <span className="text-gold">Gol</span>
      </span>
      {tagline ? (
        // Under 375 px the tagline gives its room to the header's controls (touch-sized on a phone).
        <span className="mt-1 truncate text-[0.625rem] font-medium uppercase tracking-[0.14em] text-subtle-foreground max-[374px]:hidden">
          {tagline}
        </span>
      ) : null}
    </span>
  );
}

export function BrandLogo({
  size = 32,
  tagline,
  className,
}: {
  size?: number;
  tagline?: string | undefined;
  className?: string;
}) {
  return (
    <span className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <BrandMark size={size} />
      <Wordmark tagline={tagline} />
    </span>
  );
}

/** The large crest for the sign-in screen. */
export function BrandCrest({ size = 168, className }: { size?: number; className?: string }) {
  return (
    <picture>
      <source srcSet="/brand/predigol-logo-512.webp" type="image/webp" />
      <img
        src="/brand/predigol-logo-256.png"
        width={size}
        height={size}
        alt="PrediGol"
        className={cn(
          "select-none object-contain drop-shadow-[0_18px_40px_rgba(0,0,0,0.45)]",
          className,
        )}
        draggable={false}
      />
    </picture>
  );
}
