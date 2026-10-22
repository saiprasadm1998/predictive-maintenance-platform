import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN, ASSETS, type Call, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";
import {
  changedFields,
  grantText,
  overridesOf,
  passwordProblems,
  ruleForm,
  ruleProblems,
} from "./adminModel";

const ENGINEER = {
  ...ADMIN,
  id: 2,
  username: "eng",
  roles: [{ role: "model_engineer", scope_asset_id: null }],
};

function asUser(user: typeof ADMIN) {
  const routes = sessionRoutes(true);
  routes["GET /auth/me"] = () => ({ status: 200, body: { user, csrf_token: "c" } });
  return routes;
}

describe("administration rules", () => {
  it("checks passwords as the server does", () => {
    expect(passwordProblems("vera", "short")).toEqual([
      "The password needs at least 12 characters",
    ]);
    expect(passwordProblems("vera", "my-name-is-vera!")).toEqual([
      "The password may not contain the username",
    ]);
    expect(passwordProblems("vera", "correct horse battery")).toEqual([]);
  });

  it("names a role with the part of the hierarchy it covers", () => {
    const assets = ASSETS as Parameters<typeof grantText>[1];
    expect(grantText({ role: "analyst", scope_asset_id: 5 }, assets)).toBe(
      "Reliability analyst (SA-AMM)",
    );
    expect(grantText({ role: "administrator", scope_asset_id: null }, assets)).toBe(
      "Administrator",
    );
  });

  it("keeps only the rule parameters this scope overrides", () => {
    const form = ruleForm({ spike_pct: 10, flatline: false });
    expect(form.spike_pct).toBe("10");
    expect(form.stale).toBe("");
    expect(overridesOf({ ...form, stale_factor: "4" })).toEqual({
      spike_pct: 10,
      flatline: false,
      stale_factor: 4,
    });
    expect(ruleProblems({ ...form, spike_pct: "-1" })).toEqual([
      "Spike above must be a number above 0",
    ]);
  });

  it("lists the fields an audited change touched", () => {
    expect(
      changedFields({
        id: 1,
        ts: "",
        user_id: 1,
        actor_type: "user",
        entity: "tag",
        entity_id: "3",
        action: "update",
        before: { unit: "C", range_hi: 100 },
        after: { unit: "°C", range_hi: 100 },
        ip: null,
      }),
    ).toEqual(["unit"]);
  });
});

describe("SCR-14 administration", () => {
  it("adds a user with a role limited to part of the hierarchy", async () => {
    const routes = asUser(ADMIN);
    routes["GET /users"] = () => ({ status: 200, body: [] });
    routes["POST /users"] = (call) => ({ status: 201, body: { id: 9, ...(call.body as object) } });
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin");

    await user.click(await screen.findByRole("button", { name: "Add a user" }));
    const form = screen.getByRole("region", { name: "Add a user" });
    await user.type(within(form).getByLabelText("Username"), "vera");
    await user.type(within(form).getByLabelText("Password"), "vera-password-1");
    await user.click(within(form).getByRole("button", { name: "Add user" }));
    expect(
      await within(form).findByText("The password may not contain the username"),
    ).toBeInTheDocument();
    await user.clear(within(form).getByLabelText("Password"));
    await user.type(within(form).getByLabelText("Password"), "correct horse battery");
    await user.selectOptions(within(form).getByLabelText("Role 1"), "analyst");
    await user.selectOptions(within(form).getByLabelText("Where role 1 applies"), "5");
    await user.click(within(form).getByRole("button", { name: "Add user" }));
    await waitFor(() =>
      expect(calls.find((c: Call) => c.method === "POST" && c.path === "/users")?.body).toEqual({
        username: "vera",
        display_name: "vera",
        email: null,
        password: "correct horse battery",
        roles: [{ role: "analyst", scope_asset_id: 5 }],
      }),
    );
  });

  it("shows a new API key once, then only its prefix", async () => {
    const routes = asUser(ADMIN);
    let keys: object[] = [];
    routes["GET /api-keys"] = () => ({ status: 200, body: keys });
    routes["POST /api-keys"] = () => {
      keys = [
        {
          id: 1,
          prefix: "abc123",
          name: "gateway A",
          scope: "ingest",
          created_at: "2026-10-22T08:00:00Z",
          revoked_at: null,
          last_used_at: null,
        },
      ];
      return { status: 201, body: { id: 1, key: "pmp_abc123_secret", prefix: "abc123" } };
    };
    fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin?tab=keys");

    await user.type(await screen.findByLabelText("Name"), "gateway A");
    await user.click(screen.getByRole("button", { name: "Issue key" }));
    expect(await screen.findByLabelText("The new key")).toHaveTextContent("pmp_abc123_secret");
    const table = await screen.findByRole("table", { name: "API keys" });
    expect(within(table).getByText("abc123…")).toBeInTheDocument();
    expect(within(table).queryByText(/secret/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "I have stored it" }));
    expect(screen.queryByText("pmp_abc123_secret")).not.toBeInTheDocument();
  });

  it("previews a data-quality change and asks to confirm when a tag would lose over 20 %", async () => {
    const routes = asUser(ENGINEER);
    routes["GET /dq/rules"] = () => ({
      status: 200,
      body: {
        scope: "global",
        version: 0,
        overrides: {},
        comment: "",
        created_at: null,
        defaults: { spike: true, spike_pct: 25 },
      },
    });
    routes["POST /dq/rules/preview"] = () => ({
      status: 200,
      body: {
        scope: "global",
        start: "",
        end: "",
        excluded_share: 0.05,
        warning: true,
        tags: [
          {
            tag_id: 1,
            source_name: "K101.TI1012.PV",
            asset_code: "K-101",
            cycles: 100,
            excluded: 30,
            excluded_share: 0.3,
            by_rule: { spike: 30 },
          },
        ],
      },
    });
    routes["PUT /dq/rules"] = (call) => ({
      status: 200,
      body: { rules: { version: 1 }, preview: {}, sent: call.body },
    });
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin");

    // A Model Engineer sees only the rules, not the administrator's tabs.
    expect(screen.queryByRole("link", { name: "Users and roles" })).not.toBeInTheDocument();
    await user.type(await screen.findByLabelText("Spike above"), "5");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // preview first
    await user.click(screen.getByRole("button", { name: "Preview" }));
    const table = await screen.findByRole("table", { name: "Tags most affected" });
    expect(within(table).getByText("Spike 30")).toBeInTheDocument();
    expect(save).toBeDisabled();
    await user.click(screen.getByLabelText("Save anyway"));
    await user.click(save);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
        scope: "global",
        overrides: { spike_pct: 5 },
        confirm: true,
      }),
    );
  });

  it("lists sensors that are not Good, filtered from a figure", async () => {
    const routes = asUser(ADMIN);
    const sensor = (id: number, name: string, status: string, rule: string) => ({
      tag_id: id,
      source: "gw",
      source_name: name,
      asset_code: "K-101",
      status,
      rule,
      effect: status === "Good" ? "used" : "excluded",
      since: "2026-10-22T06:00:00Z",
      evaluated_at: "2026-10-22T08:00:00Z",
    });
    routes["GET /sensors/health"] = () => ({
      status: 200,
      body: [
        sensor(1, "K101.TI1018.PV", "Failure", "flatline"),
        sensor(2, "K101.PI1001.PV", "Good", "none"),
        sensor(3, "K101.TI1030.PV", "Out of specification", "out_of_range"),
      ],
    });
    routes["GET /tags"] = () => ({ status: 200, body: { items: [], next_cursor: null } });
    fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/sensors");

    const table = await screen.findByRole("table", { name: "NAMUR NE 107 status per sensor" });
    expect(within(table).getAllByRole("row")).toHaveLength(3); // header + 2 non-Good
    expect(within(table).getByText("Flatline")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Out of specification/ }));
    await waitFor(() =>
      expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2),
    );
    expect(
      screen.getByRole("heading", { name: /Sensors in Out of specification/ }),
    ).toBeInTheDocument();
  });
});
