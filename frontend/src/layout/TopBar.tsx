import { Link, useLocation } from "react-router-dom";

import type { BreadcrumbItem } from "../app/breadcrumbs";
import { timeRangeParams } from "../app/timeRange";
import { useScreen } from "../app/useScreen";
import { TimeRangePicker } from "../components/TimeRangePicker";
import { AssetSearch } from "./AssetSearch";
import { LiveIndicator } from "./LiveIndicator";
import { UserMenu } from "./UserMenu";

/** PDS §2.2: breadcrumb, global time range, asset search, live indicator, user menu.
 * The breadcrumb grows the hierarchy path when the asset screens arrive (6.2, 6.3). */
export function TopBar({ crumbs }: { crumbs: BreadcrumbItem[] | null }) {
  const screen = useScreen();
  const location = useLocation();
  const carried = timeRangeParams(new URLSearchParams(location.search)).toString();
  const items: BreadcrumbItem[] = crumbs ?? [{ label: screen?.title ?? "Page not found" }];
  return (
    <header className="topbar">
      <nav aria-label="Breadcrumb" className="crumbs">
        <ol>
          {items.map((item, i) =>
            i < items.length - 1 ? (
              <li key={i} className="crumb">
                {item.to ? (
                  <Link to={`${item.to}${carried ? `?${carried}` : ""}`}>{item.label}</Link>
                ) : (
                  item.label
                )}
                <span aria-hidden="true" className="crumb-sep">
                  ›
                </span>
              </li>
            ) : (
              <li key={i} aria-current="page">
                <h1 className="page-title">{item.label}</h1>
              </li>
            ),
          )}
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
