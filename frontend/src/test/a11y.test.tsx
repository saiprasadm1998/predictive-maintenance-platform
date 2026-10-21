import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";

import { fakeApi, sessionRoutes } from "./fakeApi";
import { renderApp } from "./renderApp";

async function violations(root: Element): Promise<string[]> {
  // jsdom does no layout, so contrast is checked from the tokens instead (contrast.test.ts).
  const result = await axe.run(root, { rules: { "color-contrast": { enabled: false } } });
  return result.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
}

describe("accessibility (PDS §8, WCAG 2.1 AA)", () => {
  it("the sign-in page has no axe violations", async () => {
    fakeApi(sessionRoutes(false));
    renderApp("/sign-in");
    await screen.findByLabelText("Username");
    expect(await violations(document.body)).toEqual([]);
  });

  it("the app shell has no axe violations", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/assets/6");
    await screen.findByRole("navigation", { name: "Main" });
    expect(await violations(document.body)).toEqual([]);
  });

  it("is usable from the keyboard alone: skip link, rail, then the top bar", async () => {
    fakeApi(sessionRoutes(true));
    const { router } = renderApp("/fleet");
    await screen.findByRole("navigation", { name: "Main" });
    const user = userEvent.setup();

    await user.tab();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: "PMP home" })).toHaveFocus();
    for (const label of [
      "Fleet",
      "Alerts",
      "Cases",
      "Models",
      "Sensor health",
      "Library",
      "Administration",
    ]) {
      await user.tab();
      expect(screen.getByRole("link", { name: label })).toHaveFocus();
    }
    await user.keyboard("{Enter}");
    expect(router.state.location.pathname).toBe("/admin");
    await user.tab();
    expect(screen.getByRole("button", { name: /^Time range/ })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("combobox", { name: "Search assets" })).toHaveFocus();
  });

  it("the skip link moves focus to the content", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/fleet");
    await screen.findByRole("navigation", { name: "Main" });
    const user = userEvent.setup();
    await user.tab();
    await user.keyboard("{Enter}");
    expect(document.getElementById("main")).toBeInTheDocument();
    expect(window.location.hash === "#main" || document.activeElement?.id === "main").toBe(true);
  });
});
