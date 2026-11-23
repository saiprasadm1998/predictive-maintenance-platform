import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useMemo, useState } from "react";

import { fetchAssetTree } from "../api/assets";
import {
  KEY,
  ScopeContext,
  type ScopeChoice,
  type ScopeState,
  find,
  flatten,
  stored,
} from "./scope";

export function ScopeProvider({ children }: { children: ReactNode }) {
  const [choice, setChoiceState] = useState<ScopeChoice>(stored);
  const tree = useQuery({
    queryKey: ["assets", "tree"],
    queryFn: ({ signal }) => fetchAssetTree(signal),
  });

  const value = useMemo<ScopeState>(() => {
    const roots = tree.data ?? [];
    const node =
      find(roots, choice.unit) ?? find(roots, choice.area) ?? find(roots, choice.site) ?? null;
    const inside = node ? flatten([node]) : flatten(roots);
    const equipment = inside.filter((n) => n.level === "equipment");
    const site = find(roots, choice.site);
    const area = find(roots, choice.area);
    const unit = find(roots, choice.unit);
    const where = unit
      ? `${site?.name ?? ""} / ${unit.name}`
      : area
        ? `${site?.name ?? ""} / ${area.name}`
        : site
          ? site.name
          : "All sites";
    return {
      choice,
      setChoice: (next) => {
        setChoiceState(next);
        try {
          localStorage.setItem(KEY, JSON.stringify(next));
        } catch {
          // storage blocked: the scope lasts for this page only
        }
      },
      tree: roots,
      node,
      ids: node ? new Set(inside.map((n) => n.id)) : null,
      equipment,
      label: `${where} · ${equipment.length} equipment`,
    };
  }, [choice, tree.data]);

  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}
