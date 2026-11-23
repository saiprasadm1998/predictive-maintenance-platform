import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { fetchFleetKpis } from "../api/fleet";
import { NAV } from "../app/screens";
import { findScreen } from "../app/useScreen";
import { Icon } from "../components/ui";

const COLLAPSE_KEY = "pmp.sidebar";

function sum(record: Record<string, number> | undefined): number {
  return Object.values(record ?? {}).reduce((a, b) => a + b, 0);
}

export function Sidebar() {
  const location = useLocation();
  const active = findScreen(location.pathname)?.nav;
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const kpis = useQuery({
    queryKey: ["fleet", "kpis"],
    queryFn: ({ signal }) => fetchFleetKpis(signal),
  });
  const counts: Partial<Record<string, number>> = {
    al: sum(kpis.data?.open_alerts),
    ca: kpis.data?.open_cases ?? 0,
  };

  function toggle() {
    const next = !collapsed;
    setCollapsed(next);
    try {
      localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
    } catch {
      // storage blocked
    }
  }

  return (
    <nav className={`sb${collapsed ? " sb-collapsed" : ""}`} aria-label="Predictive Maintenance">
      {NAV.map((group) => (
        <div key={group.label} style={{ display: "contents" }}>
          <div className="sbg">{group.label}</div>
          {group.links.map((link) => {
            const on = link.key === active;
            const count = counts[link.key];
            return (
              <Link
                key={link.key}
                className={`sbi${on ? " on" : ""}`}
                to={link.to}
                aria-current={on ? "page" : undefined}
                title={collapsed ? link.label : undefined}
              >
                <Icon d={link.icon} />
                <span className="sbl">{link.label}</span>
                {count ? <span className="bdg cnt">{count}</span> : null}
              </Link>
            );
          })}
        </div>
      ))}
      <div className="sbfoot">
        <button className="sbi" type="button" onClick={toggle} aria-expanded={!collapsed}>
          <Icon d={collapsed ? "M9 6l6 6-6 6" : "M15 6l-6 6 6 6"} />
          <span className="sbl">{collapsed ? "Expand" : "Collapse"}</span>
        </button>
      </div>
    </nav>
  );
}
