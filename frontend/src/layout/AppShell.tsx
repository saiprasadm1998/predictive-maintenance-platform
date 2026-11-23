import { useEffect } from "react";
import { Outlet } from "react-router-dom";

import { Announcer } from "../app/Announcer";
import { LiveEvents } from "../app/LiveEvents";
import { ScopeProvider } from "../app/ScopeProvider";
import { useScreen } from "../app/useScreen";
import { Header } from "./Header";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  const screen = useScreen();
  useEffect(() => {
    document.title = screen ? `${screen.title} · Traverse PM` : "Traverse PM";
  }, [screen]);
  return (
    <Announcer>
      <LiveEvents>
        <ScopeProvider>
          <div className="app">
            <a href="#main" className="skip-link">
              Skip to content
            </a>
            <Header />
            <div className="shell">
              <Sidebar />
              <main id="main" tabIndex={-1} className="pg">
                <Outlet />
              </main>
            </div>
          </div>
        </ScopeProvider>
      </LiveEvents>
    </Announcer>
  );
}
