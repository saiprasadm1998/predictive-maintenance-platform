import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { fakeApi, sessionRoutes } from "../test/fakeApi";
import { renderApp } from "../test/renderApp";

describe("sign-in", () => {
  it("sends a signed-out deep link to sign-in and back to the same view afterwards", async () => {
    const { calls } = fakeApi(sessionRoutes(false));
    const { router } = renderApp("/cases/6?range=24h");
    const user = userEvent.setup();

    await screen.findByRole("heading", { name: "Predictive Maintenance Platform" });
    expect(router.state.location.pathname).toBe("/sign-in");

    await user.type(screen.getByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByRole("heading", { name: "Case detail" });
    expect(router.state.location.pathname).toBe("/cases/6");
    expect(router.state.location.search).toBe("?range=24h");
    expect(screen.getByText("6")).toBeInTheDocument(); // the asset ID from the URL
    const login = calls.find((c) => c.path === "/auth/login");
    expect(login?.body).toEqual({ username: "admin", password: "correct-horse-battery" });
  });

  it("states why sign-in failed and clears the password", async () => {
    fakeApi(sessionRoutes(false));
    renderApp("/sign-in");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
});

describe("app shell", () => {
  it("has the seven navigation items of PDS §2.2 and marks the active one", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/alerts?range=30d");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    const labels = [
      "Fleet",
      "Alerts",
      "Cases",
      "Models",
      "Sensor health",
      "Library",
      "Administration",
    ];
    for (const label of labels) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    expect(within(nav).getByRole("link", { name: "Alerts" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Fleet" })).not.toHaveAttribute("aria-current");
    // The global time range follows the user to other screens.
    expect(within(nav).getByRole("link", { name: "Models" })).toHaveAttribute(
      "href",
      "/models?range=30d",
    );
  });

  it("puts the time range in the URL: a preset, or a checked custom range", async () => {
    fakeApi(sessionRoutes(true));
    const { router } = renderApp("/fleet");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^Time range: Last 7 days/ }));
    await user.click(await screen.findByRole("button", { name: "Last 24 hours" }));
    expect(router.state.location.search).toBe("?range=24h");

    await user.click(screen.getByRole("button", { name: /^Time range: Last 24 hours/ }));
    const from = await screen.findByLabelText("From");
    const to = screen.getByLabelText("To");
    await user.clear(from);
    await user.type(from, "2026-10-02T10:00");
    await user.clear(to);
    await user.type(to, "2026-10-01T10:00");
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText("The end must be after the start.")).toBeInTheDocument();
    await user.clear(to);
    await user.type(to, "2026-10-03T10:00");
    await user.click(screen.getByRole("button", { name: "Apply" }));
    const params = router.state.location.search;
    expect(params).toContain("from=");
    expect(params).not.toContain("range=");
    expect(new URLSearchParams(params).get("to")).toBe(new Date("2026-10-03T10:00").toISOString());
  });

  it('focuses asset search with "/" and opens the chosen asset by keyboard', async () => {
    fakeApi(sessionRoutes(true));
    const { router } = renderApp("/fleet?range=7d");
    const user = userEvent.setup();
    const search = await screen.findByRole("combobox", { name: "Search assets" });
    await user.keyboard("/");
    expect(search).toHaveFocus();
    await user.keyboard("p-10");
    const option = await screen.findByRole("option", { name: /P-104A/ });
    expect(option).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(router.state.location.pathname).toBe("/assets/7"));
    expect(router.state.location.search).toBe("?range=7d");
  });

  it("signs out from the user menu", async () => {
    fakeApi(sessionRoutes(true));
    const { router } = renderApp("/fleet");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Administrator/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
  });

  it("sends the user to sign-in when the session ends", async () => {
    const routes = sessionRoutes(true);
    fakeApi(routes);
    const { router } = renderApp("/fleet");
    await screen.findByRole("navigation", { name: "Main" });
    // The session ends on the server: the next read is answered 401.
    const ended = () => ({ status: 401, body: { title: "Session ended", status: 401 } });
    routes["GET /auth/me"] = ended;
    routes["GET /assets"] = ended;
    await userEvent.setup().click(screen.getByRole("combobox", { name: "Search assets" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    expect(router.state.location.search).toBe("?next=%2Ffleet");
  });

  it("switches to the control-room theme", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/fleet");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Administrator/ }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: /dark/ }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("shows a plain message for an unknown address", async () => {
    fakeApi(sessionRoutes(true));
    renderApp("/no/such/screen");
    expect(await screen.findByText(/There is no screen at this address/)).toBeInTheDocument();
  });
});
