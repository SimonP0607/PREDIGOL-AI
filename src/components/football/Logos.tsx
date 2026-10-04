/**
 * Team crests, competition logos and country flags from API-Football's media CDN.
 *
 * The URL is the one the provider published and we stored; nothing is guessed. When
 * there is none, or it fails to load, a neutral initials badge stands in - never a
 * broken image, never a stretched one (object-contain in a fixed square).
 *
 * Licensing: redistribution rights for API-Sports media must be confirmed before a
 * public deployment (docs/RUNNING.md, "Before going public").
 */
import { useState } from "react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";

function initials(name: string): string {
  const words = name
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .split(/\s+/)
    .filter((w) => w.length > 0 && !/^(fc|cf|sc|ac|cd|ud|club|de|the)$/i.test(w));
  const picked = (words.length ? words : name.split(/\s+/)).slice(0, 2);
  return picked.map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";
}

function hue(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) % 360;
  return h;
}

function Fallback({
  name,
  size,
  className,
  round,
}: {
  name: string;
  size: number;
  className?: string | undefined;
  round?: boolean;
}) {
  return (
    <span
      aria-hidden
      data-logo-fallback
      className={cn(
        "inline-flex shrink-0 select-none items-center justify-center border border-border-strong font-display font-semibold text-foreground/85",
        round ? "rounded-full" : "rounded-md",
        className,
      )}
      style={{
        width: size,
        height: size,
        fontSize: Math.max(8, Math.round(size * 0.38)),
        backgroundColor: `oklch(0.3 0.04 ${hue(name)})`,
      }}
    >
      {initials(name)}
    </span>
  );
}

export function TeamLogo({
  src,
  name,
  size = 24,
  className,
}: {
  src: string | null | undefined;
  name: string;
  size?: number;
  className?: string | undefined;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <Fallback name={name} size={size} className={className} round />;
  return (
    <img
      src={src}
      alt={t("common.logoAlt", { name })}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={cn("shrink-0 select-none object-contain", className)}
      style={{ width: size, height: size }}
      draggable={false}
    />
  );
}

/**
 * A player's photo: the URL the provider published in his profile, as stored. None, or one that does
 * not load, shows his initials - never a broken image and never a guessed URL.
 */
export function PlayerPhoto({
  src,
  name,
  size = 28,
  className,
}: {
  src: string | null | undefined;
  name: string;
  size?: number;
  className?: string | undefined;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <Fallback name={name} size={size} className={className} round />;
  return (
    <img
      src={src}
      alt={t("common.photoAlt", { name })}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={cn("shrink-0 select-none rounded-full bg-muted object-cover", className)}
      style={{ width: size, height: size }}
      draggable={false}
    />
  );
}

export function CompetitionLogo({
  src,
  name,
  size = 18,
  className,
}: {
  src: string | null | undefined;
  name: string;
  size?: number;
  className?: string | undefined;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return <Fallback name={name} size={size} className={className} />;
  return (
    <img
      src={src}
      alt={t("common.competitionLogoAlt", { name })}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={cn("shrink-0 select-none rounded-sm bg-white/90 object-contain p-px", className)}
      style={{ width: size, height: size }}
      draggable={false}
    />
  );
}

export function CountryFlag({
  src,
  name,
  height = 12,
  className,
}: {
  src: string | null | undefined;
  name: string | null | undefined;
  height?: number;
  className?: string | undefined;
}) {
  const [failed, setFailed] = useState(false);
  if (!src || failed || !name) return null;
  const width = Math.round((height * 4) / 3);
  return (
    <img
      src={src}
      alt={t("common.flagAlt", { name })}
      width={width}
      height={height}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={cn(
        "shrink-0 select-none rounded-[2px] object-cover ring-1 ring-black/20",
        className,
      )}
      style={{ width, height }}
      draggable={false}
    />
  );
}

/** Crest + name, truncating cleanly. */
export function TeamName({
  name,
  logo,
  size = 20,
  className,
  reverse = false,
  strong = false,
}: {
  name: string;
  logo: string | null | undefined;
  size?: number;
  className?: string | undefined;
  reverse?: boolean;
  strong?: boolean;
}) {
  return (
    <span
      className={cn(
        "flex min-w-0 items-center gap-2",
        reverse && "flex-row-reverse text-right",
        className,
      )}
    >
      <TeamLogo src={logo} name={name} size={size} />
      <span className={cn("truncate", strong && "font-semibold")}>{name}</span>
    </span>
  );
}

/** Competition logo, flag and name: "🏴 LaLiga · Spain". */
export function CompetitionTag({
  name,
  logo,
  flag,
  country,
  className,
  size = 16,
}: {
  name: string;
  logo?: string | null | undefined;
  flag?: string | null | undefined;
  country?: string | null | undefined;
  className?: string | undefined;
  size?: number;
}) {
  return (
    <span
      className={cn(
        "flex min-w-0 items-center gap-1.5 text-caption text-muted-foreground",
        className,
      )}
    >
      <CompetitionLogo src={logo} name={name} size={size} />
      <span className="truncate">{name}</span>
      {flag ? <CountryFlag src={flag} name={country} height={Math.max(9, size - 6)} /> : null}
    </span>
  );
}
