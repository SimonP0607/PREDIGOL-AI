/** How a venue reads on a page: its name and city, and the provider's details when they are known. */
import { t, translateOr } from "@/lib/i18n";
import { int } from "@/lib/format";
import type { VenueRef } from "@/lib/api/v1/types";

/** "Estadio El Campín, Bogotá" — the name as the provider gave it, with the city when known. */
export function venuePlace(v: VenueRef): string {
  return v.city ? `${v.name}, ${v.city}` : v.name;
}

/** The provider's surface text in the reader's language ("grass" -> "césped"); an unknown text stays as sent. */
export function venueSurface(surface: string | null | undefined): string | null {
  if (!surface) return null;
  const key = surface
    .trim()
    .toLowerCase()
    .replace(/[^a-z]+/g, "_");
  return translateOr(`match.venue.surface.${key}`, surface.trim());
}

/** "40.943 espectadores · césped" — only what the provider said; nothing when it said nothing. */
export function venueFacts(v: VenueRef): string[] {
  const out: string[] = [];
  if (v.capacity) out.push(t("match.venue.capacity", { n: int(v.capacity) }));
  const surface = venueSurface(v.surface);
  if (surface) out.push(surface);
  return out;
}
