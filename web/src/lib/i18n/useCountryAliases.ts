/**
 * The country aliases (AP-B02) without their weight in the first visit: the table and the merge are a chunk of their own,
 * downloaded the first time a search has three letters to look at (the global search lives in the header, so a direct import
 * would travel with every page; bundle budget, plan de cierre UX 5.2).
 */
import { useEffect, useMemo, useState } from "react";
import { intlTag } from "@/lib/i18n";

type Aliasing = typeof import("./countryAliases");

let loaded: Aliasing | null = null;
let loading: Promise<Aliasing> | null = null;

function load(): Promise<Aliasing> {
  loading ??= import("./countryAliases").then((m) => {
    loaded = m;
    return m;
  });
  return loading;
}

/** Until the chunk arrives, nothing is aliased and the merge keeps the typed text's own answers. */
const merge: Aliasing["mergeAliased"] = (own) => [...own];

export function useCountryAliases(
  typed: string,
  on: boolean,
): { aliases: string[]; merge: Aliasing["mergeAliased"] } {
  const [mod, setMod] = useState<Aliasing | null>(loaded);
  const wanted = on && typed.trim().length >= 3;
  useEffect(() => {
    if (!wanted || mod) return;
    let live = true;
    void load().then((m) => {
      if (live) setMod(m);
    });
    return () => {
      live = false;
    };
  }, [wanted, mod]);
  const tag = intlTag();
  const aliases = useMemo(
    () => (mod && wanted ? mod.countryAliases(typed) : []),
    // the names follow the reader's language
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mod, wanted, typed, tag],
  );
  return { aliases, merge: mod?.mergeAliased ?? merge };
}
