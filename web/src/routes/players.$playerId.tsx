import { createFileRoute } from "@tanstack/react-router";
import { PlayerPage } from "@/product/teams/PlayerPage";
import { titled } from "@/lib/i18n/head";

/** The profile of a player (plan maestro unificado, UX-156; maqueta 13): shown only while FBI_PROFILES is on. */
export const Route = createFileRoute("/players/$playerId")({
  head: titled("profiles.playerTitle"),
  component: Player,
});

function Player() {
  const { playerId } = Route.useParams();
  return <PlayerPage playerId={playerId} />;
}
