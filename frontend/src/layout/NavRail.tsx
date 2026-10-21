import { Link, useLocation } from "react-router-dom";

import { NAV_ITEMS } from "../app/screens";
import { timeRangeParams } from "../app/timeRange";
import { findScreen } from "../app/useScreen";
import { NavIcon } from "../components/NavIcon";

/** PDS §2.2: icons with labels on hover; the active item is shown by fill, not colour alone. */
export function NavRail() {
  const location = useLocation();
  const active = findScreen(location.pathname)?.section;
  const carried = timeRangeParams(new URLSearchParams(location.search)).toString();
  return (
    <nav className="rail" aria-label="Main">
      <Link
        to={`/fleet${carried ? `?${carried}` : ""}`}
        className="rail-brand"
        aria-label="PMP home"
      >
        <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
          <path
            d="M5 18h6l3-8 4 14 3-6h6"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </Link>
      <ul className="rail-items">
        {NAV_ITEMS.map((item) => {
          const current = item.section === active;
          return (
            <li key={item.section}>
              <Link
                to={`${item.to}${carried ? `?${carried}` : ""}`}
                className={current ? "rail-item rail-item-active" : "rail-item"}
                aria-current={current ? "page" : undefined}
                aria-label={item.label}
              >
                <NavIcon section={item.section} />
                <span className="rail-label" aria-hidden="true">
                  {item.label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
