import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Asset } from "../../api/assets";
import type { User } from "../../api/auth";
import { ADMIN, ASSETS, type Call, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";
import {
  canEditRegistry,
  childLevel,
  countText,
  emptyTag,
  hierarchyRows,
  parentChoices,
  tagProblems,
} from "./registryModel";

const assets = ASSETS as Asset[];
const SITE = { ...assets[0]!, id: 3, code: "SITE-A", name: "Site A", level: "site", parent_id: 1 };
const TREE = [...assets, SITE];

describe("registry rules", () => {
  it("lays the hierarchy out with each asset under its parent", () => {
    const rows = hierarchyRows(TREE);
    expect(rows.map((r) => `${"  ".repeat(r.depth)}${r.asset.code}`)).toEqual([
      "DEMO",
      "  SITE-A",
      "    SA-AMM",
      "      K-101",
      "      P-104A",
    ]);
    expect(rows[0]!.hasChildren).toBe(true);
  });

  it("moves an asset only under a higher level, never below itself", () => {
    const unit = TREE.find((a) => a.code === "SA-AMM")!;
    expect(parentChoices(TREE, unit).map((a) => a.code)).toEqual(["DEMO", "SITE-A"]);
    expect(childLevel("unit")).toBe("equipment");
    expect(childLevel("equipment")).toBeNull();
  });

  it("lets Model Engineers and Administrators change the registry", () => {
    const as = (role: string) => ({ ...ADMIN, roles: [{ role, scope_asset_id: null }] }) as User;
    expect(canEditRegistry(as("administrator"))).toBe(true);
    expect(canEditRegistry(as("model_engineer"))).toBe(true);
    expect(canEditRegistry(as("analyst"))).toBe(false);
  });

  it("checks a tag before sending it", () => {
    const tag = { ...emptyTag("gw", "X.PV", "K-101"), unit: "°C", range_lo: 5, range_hi: 5 };
    expect(tagProblems(tag)).toEqual(["Range low must be below range high"]);
    expect(tagProblems({ ...tag, range_hi: 10, interval_s: 0.5 })).toEqual([
      "The interval is a whole number of seconds above 0",
    ]);
    expect(countText({ created: 2, updated: 0, unchanged: 14 })).toBe("2 created, 14 unchanged");
  });
});

function registryRoutes() {
  const routes = sessionRoutes(true);
  routes["GET /assets"] = () => ({ status: 200, body: { items: TREE, next_cursor: null } });
  routes["GET /asset-types"] = () => ({
    status: 200,
    body: [
      {
        id: 1,
        code: "centrifugal_pump",
        name: "Centrifugal pump",
        description: "",
        roles: [{ code: "flow", name: "Flow", unit: "m³/h" }],
      },
    ],
  });
  return routes;
}

describe("SCR-13 registry and import", () => {
  it("moves an asset and changes its criticality", async () => {
    const routes = registryRoutes();
    routes["PATCH /assets/7"] = (call) => ({
      status: 200,
      body: { ...TREE.find((a) => a.id === 7), ...(call.body as object) },
    });
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin/registry");

    await user.click(await screen.findByRole("button", { name: "Edit P-104A" }));
    const form = screen.getByRole("region", { name: "Edit P-104A" });
    await user.selectOptions(within(form).getByLabelText("Criticality"), "A");
    await user.selectOptions(within(form).getByLabelText("Asset type"), "centrifugal_pump");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    const patch = calls.find((c: Call) => c.method === "PATCH")!;
    expect(patch.body).toMatchObject({
      criticality: "A",
      asset_type: "centrifugal_pump",
      parent: "SA-AMM",
    });
  });

  it("imports only after a clean validation, listing problems by sheet, line and column", async () => {
    const routes = registryRoutes();
    let attempt = 0;
    routes["POST /tags/import"] = (call) => {
      attempt += 1;
      const dryRun = call.query.get("dry_run") === "true";
      if (attempt === 1)
        return {
          status: 200,
          body: {
            committed: false,
            dry_run: true,
            counts: {},
            problems: [{ sheet: "tags", line: 4, column: "unit", message: "unit is required" }],
          },
        };
      return {
        status: 200,
        body: {
          committed: !dryRun,
          dry_run: dryRun,
          counts: { assets: { created: 1, updated: 0, unchanged: 3 } },
          problems: [],
        },
      };
    };
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin/registry?tab=import");

    const input = await screen.findByLabelText("Files");
    await user.upload(input, new File(["code,name\n"], "tags.csv", { type: "text/csv" }));
    const importButton = screen.getByRole("button", { name: "Import" });
    expect(importButton).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Validate" }));
    const report = await screen.findByRole("table", { name: "Validation report" });
    expect(within(report).getByText("unit is required")).toBeInTheDocument();
    expect(importButton).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Validate" }));
    expect(
      await screen.findByRole("table", { name: "Changes the import will make" }),
    ).toHaveTextContent("1 created, 3 unchanged");
    await user.click(importButton);
    expect(await screen.findByText("Imported.")).toBeInTheDocument();
    const sent = calls.filter((c) => c.path === "/tags/import");
    expect(sent.map((c) => c.query.get("dry_run"))).toEqual(["true", "true", "false"]);
    expect((sent[0]!.body as FormData).get("files")).toBeInstanceOf(File);
  });

  it("registers an unmapped tag with the gateway's name", async () => {
    const routes = registryRoutes();
    routes["GET /unmapped-tags"] = () => ({
      status: 200,
      body: [
        {
          source: "gw-1",
          source_name: "K101.NEW.PV",
          first_seen: "2026-10-20T00:00:00Z",
          last_seen: "2026-10-21T00:00:00Z",
          count: 1440,
        },
      ],
    });
    routes["POST /unmapped-tags/promote"] = (call) => ({
      status: 201,
      body: { id: 99, ...(call.body as object) },
    });
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin/registry?tab=unmapped");

    await user.click(await screen.findByRole("button", { name: "Register K101.NEW.PV" }));
    const form = screen.getByRole("region", { name: "Register an unmapped tag" });
    expect(within(form).getByLabelText("Source name")).toHaveValue("K101.NEW.PV");
    await user.click(within(form).getByRole("button", { name: "Register" }));
    expect(await within(form).findByText("Choose the asset")).toBeInTheDocument();
    await user.selectOptions(within(form).getByLabelText("Asset"), "K-101");
    await user.type(within(form).getByLabelText("Unit"), "°C");
    await user.click(within(form).getByRole("button", { name: "Register" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/unmapped-tags/promote")?.body).toMatchObject({
        source: "gw-1",
        source_name: "K101.NEW.PV",
        asset: "K-101",
        unit: "°C",
      }),
    );
  });

  it("shows the registry without change controls to other roles", async () => {
    const routes = registryRoutes();
    routes["GET /auth/me"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, roles: [{ role: "viewer", scope_asset_id: null }] },
        csrf_token: "c",
      },
    });
    fakeApi(routes);
    renderApp("/admin/registry");
    expect(await screen.findByText(/You can look at the registry/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit/ })).not.toBeInTheDocument();
  });
});
