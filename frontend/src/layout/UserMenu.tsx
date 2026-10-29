import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useMe, useSignOut } from "../app/session";
import { type Theme, applyTheme, storedTheme } from "../app/theme";

export function UserMenu() {
  const me = useMe();
  const signOut = useSignOut();
  const navigate = useNavigate();
  const [theme, setTheme] = useState<Theme>(storedTheme);
  const user = me.data;
  if (!user) return null;

  function toggleTheme() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    applyTheme(next);
    setTheme(next);
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger className="control user-trigger">
        {user.display_name || user.username} <span aria-hidden="true">▾</span>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="menu" align="end" sideOffset={6}>
          <DropdownMenu.Label className="menu-label">
            Signed in as {user.username}
            <span className="muted">
              {" "}
              · {user.roles.map((r) => r.role.replace("_", " ")).join(", ")}
            </span>
          </DropdownMenu.Label>
          <DropdownMenu.Separator className="menu-separator" />
          <DropdownMenu.CheckboxItem
            className="menu-item"
            checked={theme === "dark"}
            onCheckedChange={toggleTheme}
          >
            <DropdownMenu.ItemIndicator className="menu-check">✓</DropdownMenu.ItemIndicator>
            Control-room (dark) theme
          </DropdownMenu.CheckboxItem>
          <DropdownMenu.Item
            className="menu-item"
            onSelect={() => void navigate("/admin?tab=notifications")}
          >
            My notifications
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
