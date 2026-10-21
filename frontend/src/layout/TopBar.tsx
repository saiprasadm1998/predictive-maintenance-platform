import { useScreen } from "../app/useScreen";
import { TimeRangePicker } from "../components/TimeRangePicker";
import { AssetSearch } from "./AssetSearch";
import { LiveIndicator } from "./LiveIndicator";
import { UserMenu } from "./UserMenu";

/** PDS §2.2: breadcrumb, global time range, asset search, live indicator, user menu.
 * The breadcrumb grows the hierarchy path when the asset screens arrive (6.2, 6.3). */
export function TopBar() {
  const screen = useScreen();
  return (
    <header className="topbar">
      <nav aria-label="Breadcrumb" className="crumbs">
        <ol>
          <li aria-current="page">
            <h1 className="page-title">{screen?.title ?? "Page not found"}</h1>
          </li>
        </ol>
      </nav>
      <div className="topbar-tools">
        <TimeRangePicker />
        <AssetSearch />
        <LiveIndicator />
        <UserMenu />
      </div>
    </header>
  );
}
