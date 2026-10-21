import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";

import { Announcer } from "../app/Announcer";
import { BreadcrumbContext, type BreadcrumbItem } from "../app/breadcrumbs";
import { LiveEvents } from "../app/LiveEvents";
import { useScreen } from "../app/useScreen";
import { NavRail } from "./NavRail";
import { TopBar } from "./TopBar";

export function AppShell() {
  const screen = useScreen();
  const [crumbs, setCrumbs] = useState<BreadcrumbItem[] | null>(null);
  useEffect(() => {
    document.title = screen ? `${screen.title} · PMP` : "PMP";
  }, [screen]);
  return (
    <Announcer>
      <BreadcrumbContext.Provider value={setCrumbs}>
        <LiveEvents>
          <div className="shell">
            <a href="#main" className="skip-link">
              Skip to content
            </a>
            <NavRail />
            <div className="shell-main">
              <TopBar crumbs={crumbs} />
              <main id="main" tabIndex={-1} className="content">
                <Outlet />
              </main>
            </div>
          </div>
        </LiveEvents>
      </BreadcrumbContext.Provider>
    </Announcer>
  );
}
