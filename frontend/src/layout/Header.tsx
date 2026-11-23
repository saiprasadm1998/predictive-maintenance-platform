import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { find, nodesOfLevel, useScope } from "../app/scope";
import { useMe, useSignOut } from "../app/session";
import { type Theme, applyTheme, storedTheme } from "../app/theme";
import { Icon } from "../components/ui";
import { AssetSearch } from "./AssetSearch";

function ScopePicker() {
  const scope = useScope();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(scope.choice);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const sites = nodesOfLevel(scope.tree, "site");
  const site = find(scope.tree, draft.site);
  const areas = site ? nodesOfLevel([site], "area") : [];
  const area = find(scope.tree, draft.area);
  const units = area ? nodesOfLevel([area], "unit") : site ? nodesOfLevel([site], "unit") : [];
  const num = (v: string) => (v === "all" ? null : Number(v));

  return (
    <div style={{ position: "relative" }} ref={box}>
      <button
        className="scopebtn"
        type="button"
        aria-expanded={open}
        aria-controls="scope-pop"
        aria-label={`Plant scope: ${scope.label}`}
        onClick={() => {
          if (!open) setDraft(scope.choice);
          setOpen(!open);
        }}
      >
        <Icon d="M4 11l8-7 8 7v9h-5v-6H9v6H4z" />
        <span>{scope.label}</span>
        <Icon d="M6 9l6 6 6-6" size={16} />
      </button>
      {open && (
        <div
          className="pop"
          id="scope-pop"
          role="dialog"
          aria-label="Plant scope"
          style={{ left: 0 }}
        >
          <div className="fld">
            <label htmlFor="sc-site">Site</label>
            <select
              id="sc-site"
              className="sl"
              value={draft.site ?? "all"}
              onChange={(e) => setDraft({ site: num(e.target.value), area: null, unit: null })}
            >
              <option value="all">All sites</option>
              {sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </div>
          <div className="fld">
            <label htmlFor="sc-area">Area</label>
            <select
              id="sc-area"
              className="sl"
              value={draft.area ?? "all"}
              disabled={!site || areas.length === 0}
              onChange={(e) => setDraft({ ...draft, area: num(e.target.value), unit: null })}
            >
              <option value="all">{site ? "All areas" : "Select a site first"}</option>
              {areas.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
          <div className="fld">
            <label htmlFor="sc-unit">Unit</label>
            <select
              id="sc-unit"
              className="sl"
              value={draft.unit ?? "all"}
              disabled={!site || units.length === 0}
              onChange={(e) => setDraft({ ...draft, unit: num(e.target.value) })}
            >
              <option value="all">{site ? "All units" : "Select a site first"}</option>
              {units.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name}
                </option>
              ))}
            </select>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <button
              className="btn btn-g btn-sm"
              type="button"
              onClick={() => {
                const none = { site: null, area: null, unit: null };
                setDraft(none);
                scope.setChoice(none);
              }}
            >
              Reset
            </button>
            <button
              className="btn btn-p btn-sm"
              type="button"
              onClick={() => {
                scope.setChoice(draft);
                setOpen(false);
              }}
            >
              Apply to all pages
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const me = useMe();
  const signOut = useSignOut();
  const navigate = useNavigate();
  const user = me.data;
  if (!user) return null;
  const name = user.display_name || user.username;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger className="userbtn" aria-label={`Account menu: ${name}`}>
        <svg className="ico ico20" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <circle cx="12" cy="10" r="3" />
          <path d="M6.5 18.5a6.5 6.5 0 0 1 11 0" />
        </svg>
        <span>{name}</span>
        <Icon d="M6 9l6 6 6-6" size={16} />
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="menu" align="end" sideOffset={6}>
          <DropdownMenu.Label className="menu-label">
            <b>{user.username}</b>
            <span className="meta">
              {user.roles.map((r) => r.role.replace("_", " ")).join(", ")}
            </span>
          </DropdownMenu.Label>
          <DropdownMenu.Separator className="menu-sep" />
          <DropdownMenu.Item
            className="menu-item"
            onSelect={() => void navigate("/system/notifications")}
          >
            My notifications
          </DropdownMenu.Item>
          <DropdownMenu.Item className="menu-item" onSelect={() => void navigate("/coverage")}>
            Use-case coverage
          </DropdownMenu.Item>
          <DropdownMenu.Item
            className="menu-item"
            onSelect={() => {
              void signOut().finally(() => navigate("/sign-in", { replace: true }));
            }}
          >
            Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export function Header() {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  const day = theme === "day";
  return (
    <header className="hd">
      <Link className="brand" to="/fleet" aria-label="Traverse PM, overview">
        <b>Traverse</b> <span>PM</span>
      </Link>
      <ScopePicker />
      <AssetSearch />
      <div className="grow" />
      <span className="env" aria-label="Environment: proof of concept">
        PoC
      </span>
      <button
        className="iconbtn"
        type="button"
        aria-label={day ? "Switch to night mode" : "Switch to day mode"}
        aria-pressed={!day}
        onClick={() => {
          const next: Theme = day ? "night" : "day";
          applyTheme(next);
          setTheme(next);
        }}
      >
        {day ? (
          <Icon d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" size={20} />
        ) : (
          <svg className="ico ico20" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
          </svg>
        )}
      </button>
      <Link className="iconbtn" to="/system/notifications" aria-label="Notifications">
        <Icon d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0" size={20} />
      </Link>
      <UserMenu />
    </header>
  );
}
