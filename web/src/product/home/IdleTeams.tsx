/**
 * The followed teams with no match of a league PrediGol follows (plan UX, AP-B06): they stay in the reader's favourites, but
 * none of their matches can appear in «Tus favoritos» until one does. The strip says so rather than leave the reader to wonder
 * where their team is. Nothing for anyone but a reader with such a team; it changes no pick, probability or price.
 */
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import { t } from "@/lib/i18n";
import { idleTeamNames } from "@/product/favorites/follow";

export function IdleTeamsNote({ reader }: { reader: boolean }) {
  const favorites = useQuery({ ...live.favorites, enabled: reader });
  const names = idleTeamNames(favorites.data);
  if (names.length === 0) return null;
  return (
    <p className="text-caption text-muted-foreground" data-testid="home-idle-teams">
      {t("home.idleTeams", { teams: names.join(", "), count: names.length })}
    </p>
  );
}
