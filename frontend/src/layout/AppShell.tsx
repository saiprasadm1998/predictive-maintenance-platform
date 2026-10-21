import { useEffect } from "react";
import { Outlet } from "react-router-dom";

import { Announcer } from "../app/Announcer";
import { LiveEvents } from "../app/LiveEvents";
import { useScreen } from "../app/useScreen";
import { NavRail } from "./NavRail";
import { TopBar } from "./TopBar";

export function AppShell() {
  const screen = useScreen();
  useEffect(() => {
    document.title = screen ? `${screen.title} · PMP` : "PMP";
  }, [screen]);
  return (
    <Announcer>
      <LiveEvents>
        <div className="shell">
          <a href="#main" className="skip-link">
            Skip to content
          </a>
          <NavRail />
          <div className="shell-main">
            <TopBar />
            <main id="main" tabIndex={-1} className="content">
              <Outlet />
            </main>
          </div>
        </div>
      </LiveEvents>
    </Announcer>
  );
}
