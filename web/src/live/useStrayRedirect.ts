/**
 * Plan F13: on Operación or Aprendizaje, a link that names a tab of the OTHER of the two pages (/admin/operation#tab=calibration, or an old address
 * whose hash was kept) is moved to the page that has it. The hash is read from the window, where the browser keeps it: a fragment never reaches the server.
 */
import { useEffect } from "react";
import { useNavigate } from "@tanstack/react-router";
import { strayAddress, type AdminAiPath } from "./adminAi";

/** At the start and whenever the address changes: a hash that names a tab of the other page goes to the page that has it. */
export function useStrayRedirect(path: AdminAiPath): void {
  const navigate = useNavigate();
  useEffect(() => {
    const move = () => {
      const stray = strayAddress(path, window.location.hash);
      if (stray) void navigate({ to: stray.to, hash: stray.hash, replace: true });
    };
    move();
    window.addEventListener("hashchange", move);
    return () => window.removeEventListener("hashchange", move);
  }, [navigate, path]);
}
