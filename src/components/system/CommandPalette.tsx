import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, type LinkProps } from "@tanstack/react-router";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { adminNav } from "@/components/layout/nav";
import { t } from "@/lib/i18n";
import { DATA_MODE } from "@/lib/api/mode";
import { v1 } from "@/lib/api/v1/client";
import { searchIndex } from "@/mock/research";
import type { SearchHit, SearchHitType } from "@/types/domain";

function typeLabel(type: SearchHitType): string {
  switch (type) {
    case "fixture":
      return t("admin.shell.groups.fixture");
    case "team":
      return t("admin.shell.groups.team");
    case "competition":
      return t("admin.shell.groups.competition");
    case "model":
      return t("admin.shell.groups.model");
  }
}

/** What an empty search says: in demo mode it searched the demo index, in live mode the API. */
export function searchEmpty(): string {
  return DATA_MODE === "mock" ? t("admin.shell.searchEmptyDemo") : t("admin.shell.searchEmptyLive");
}

/**
 * The entity search behind the topbar box and the command palette. Demo mode
 * searches the demo index; live and hybrid mode ask GET /search, so a demo
 * fixture can never be offered - or opened - as if it were stored.
 */
export function useEntitySearch(term: string, limit = 8): SearchHit[] {
  const q = term.trim();
  const live = DATA_MODE !== "mock";
  const res = useQuery({
    queryKey: ["v1", "search", q],
    queryFn: () => v1.search(q),
    enabled: live && q.length >= 2,
    staleTime: 60_000,
  });
  return useMemo(() => {
    if (!live) return searchEntities(term, limit);
    return (res.data?.data ?? []).slice(0, limit).map((h) => ({
      id: `${h.type}-${h.id}`,
      type: h.type,
      label: h.label,
      sublabel: h.sublabel,
      fixtureId: h.type === "fixture" ? String(h.id) : null,
    }));
  }, [live, term, limit, res.data]);
}

/** Demo-mode entity search over the demo index. */
export function searchEntities(term: string, limit = 8): SearchHit[] {
  const q = term.trim().toLowerCase();
  if (!q) return [];
  return searchIndex
    .filter((h) => h.label.toLowerCase().includes(q) || h.sublabel.toLowerCase().includes(q))
    .slice(0, limit);
}

export type Destination = NonNullable<LinkProps["to"]>;

export function destinationFor(hit: SearchHit): Destination {
  if (hit.type === "model") return "/admin/models";
  if (hit.type === "competition") return "/admin/competitions";
  if (hit.type === "team") return "/admin/teams";
  if (hit.fixtureId) return "/matches/$fixtureId";
  return "/matches";
}

export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const [term, setTerm] = useState("");

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key.toLowerCase() === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        onOpenChange(!open);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  const hits = useEntitySearch(term, 12);
  const grouped = useMemo(() => {
    const map = new Map<SearchHitType, SearchHit[]>();
    for (const h of hits) map.set(h.type, [...(map.get(h.type) ?? []), h]);
    return [...map.entries()];
  }, [hits]);

  function go(to: Destination, fixtureId?: string | null) {
    onOpenChange(false);
    setTerm("");
    if (to === "/matches/$fixtureId" && fixtureId) {
      void navigate({ to, params: { fixtureId } });
    } else {
      void navigate({ to });
    }
  }

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange}>
      <CommandInput
        placeholder={t("admin.shell.palettePlaceholder")}
        value={term}
        onValueChange={setTerm}
      />
      <CommandList>
        <CommandEmpty>{searchEmpty()}</CommandEmpty>
        {grouped.map(([type, list]) => (
          <CommandGroup key={type} heading={typeLabel(type)}>
            {list.map((h) => (
              <CommandItem
                key={h.id}
                value={`${h.label} ${h.sublabel}`}
                onSelect={() => go(destinationFor(h), h.fixtureId)}
              >
                <span className="truncate">{h.label}</span>
                <span className="ml-auto truncate text-caption text-subtle-foreground">
                  {h.sublabel}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
        {adminNav.map((group) => (
          <CommandGroup key={group.label} heading={t(group.label)}>
            {group.items.map((item) => (
              <CommandItem
                key={item.to}
                value={`${t(group.label)} ${t(item.label)}`}
                onSelect={() => go(item.to as Destination)}
              >
                {t(item.label)}
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  );
}
