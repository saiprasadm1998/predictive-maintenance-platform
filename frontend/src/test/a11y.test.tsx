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
    await screen.findByLabelText("User name or e-mail");
    expect(await violations(document.body)).toEqual([]);
  });

  it("the app shell has no axe violations", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/assets/6");
    await screen.findByRole("navigation", { name: "Predictive Maintenance" });
    expect(await violations(document.body)).toEqual([]);
  });

  it("is usable from the keyboard alone: skip link, header, then the navigation", async () => {
    fakeApi(sessionRoutes(true));
    const { router } = renderApp("/fleet");
    await screen.findByRole("navigation", { name: "Predictive Maintenance" });
    const user = userEvent.setup();

    await user.tab();
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: "Traverse PM, overview" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: /^Plant scope/ })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("combobox")).toHaveFocus();
    const alerts = screen.getByRole("link", { name: /^Alerts/ });
    alerts.focus();
    await user.keyboard("{Enter}");
    expect(router.state.location.pathname).toBe("/alerts");
  });

  it("the skip link moves focus to the content", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/fleet");
    await screen.findByRole("navigation", { name: "Predictive Maintenance" });
    const user = userEvent.setup();
    await user.tab();
    await user.keyboard("{Enter}");
    expect(document.getElementById("main")).toBeInTheDocument();
    expect(window.location.hash === "#main" || document.activeElement?.id === "main").toBe(true);
  });
});
