import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { fakeApi, sessionRoutes } from "../test/fakeApi";
import { renderApp } from "../test/renderApp";

describe("sign-in", () => {
  it("sends a signed-out deep link to sign-in and back to the same view afterwards", async () => {
    const { calls } = fakeApi(sessionRoutes(false));
    const { router } = renderApp("/coverage?x=1");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("User name or e-mail"), "admin");
    expect(router.state.location.pathname).toBe("/sign-in");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByRole("heading", { name: "Use-case coverage" });
    expect(router.state.location.pathname).toBe("/coverage");
    expect(router.state.location.search).toBe("?x=1");
    const login = calls.find((c) => c.path === "/auth/login");
    expect(login?.body).toEqual({ username: "admin", password: "correct-horse-battery" });
  });

  it("states why sign-in failed and clears the password", async () => {
    fakeApi(sessionRoutes(false));
    renderApp("/sign-in");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("User name or e-mail"), "admin");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in failed");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
});

describe("app shell", () => {
  it("groups the navigation by task and marks the active page", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/alerts");
    const nav = await screen.findByRole("navigation", { name: "Predictive Maintenance" });
    for (const group of ["Find problems", "Check equipment", "Act", "Set up", "System"])
      expect(within(nav).getByText(group)).toBeInTheDocument();
    for (const label of [
      "Overview",
      "Equipment",
      "Alerts",
      "Equipment analysis",
      "Sensor health",
      "Cases",
      "Setup overview",
      "Equipment register",
      "Historical data",
      "Models",
      "Users and access",
      "Audit log",
    ])
      expect(
        within(nav).getByRole("link", { name: new RegExp(`^${label}( \\d+)?$`) }),
      ).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /^Alerts( \d+)?$/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it('focuses the search with "/" and opens the chosen equipment by keyboard', async () => {
    fakeApi(sessionRoutes(true));
    const { router } = renderApp("/fleet");
    const user = userEvent.setup();
    const search = await screen.findByRole("combobox");
    await user.keyboard("/");
    expect(search).toHaveFocus();
    await user.keyboard("p-10");
    const option = await screen.findByRole("option", { name: /P-104A/ });
    expect(option).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(router.state.location.pathname).toBe("/assets/7"));
  });

  it("signs out from the account menu", async () => {
    fakeApi(sessionRoutes(true));
    const { router } = renderApp("/fleet");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Account menu/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
  });

  it("switches between the day and night themes", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/fleet");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Switch to night mode" }));
    expect(document.documentElement.dataset.theme).toBe("night");
    await user.click(screen.getByRole("button", { name: "Switch to day mode" }));
    expect(document.documentElement.dataset.theme).toBe("day");
  });

  it("shows a plain message for an unknown address", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/no/such/screen");
    expect(await screen.findByText(/There is no page at this address/)).toBeInTheDocument();
  });
});
