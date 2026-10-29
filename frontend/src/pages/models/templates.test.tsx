import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN, type Call, MODELS, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";

const PUMP = (code: string, id: number) => ({
  id,
  code,
  name: `Pump ${code}`,
  level: "equipment",
  parent_id: 1,
  criticality: "B",
  asset_type: "centrifugal_pump",
  description: "",
});

const TEMPLATE = {
  id: 4,
  asset_type: "centrifugal_pump",
  name: "standard",
  model_name: "template",
  description: "",
  definition: {},
  required_roles: ["motor_current", "de_bearing_temp"],
  optional_roles: ["flow", "de_vibration"],
  updated_at: "2026-10-29T00:00:00Z",
  updated_by: 1,
};

function result(asset: string, outcome: string, extra: object = {}) {
  return {
    asset,
    outcome,
    reason: null,
    tags: { motor_current: `${asset}.II`, de_bearing_temp: `${asset}.TI` },
    missing_required: [],
    missing_optional: [],
    model_id: null,
    version_id: null,
    job_id: null,
    ...extra,
  };
}

describe("Apply template (UC-07)", () => {
  it("previews the gaps, then creates a model per eligible asset", async () => {
    const r = sessionRoutes(true);
    r["GET /auth/me"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, roles: [{ role: "model_engineer", scope_asset_id: null }] },
        csrf_token: "c",
      },
    });
    r["GET /models"] = () => ({ status: 200, body: MODELS });
    r["GET /asset-types"] = () => ({
      status: 200,
      body: [
        { id: 1, code: "centrifugal_pump", name: "Centrifugal pump", description: "", roles: [] },
      ],
    });
    r["GET /assets"] = () => ({
      status: 200,
      body: { items: [PUMP("P-104A", 7), PUMP("P-104B", 8), PUMP("P-205", 9)], next_cursor: null },
    });
    r["GET /model-templates"] = () => ({ status: 200, body: [TEMPLATE] });
    r["POST /model-templates/4/apply"] = (call) => {
      const { preview } = call.body as { preview: boolean };
      return {
        status: 200,
        body: [
          result("P-104A", preview ? "ready" : "created", preview ? {} : { model_id: 11 }),
          result("P-205", preview ? "ready" : "created", {
            missing_optional: ["de_vibration"],
            ...(preview ? {} : { model_id: 12 }),
          }),
        ],
      };
    };
    const { calls } = fakeApi(r);
    const user = userEvent.setup();
    renderApp("/models");

    await user.click(await screen.findByRole("button", { name: "Apply template…" }));
    const panel = screen.getByRole("region", { name: "Apply a template" });
    await user.selectOptions(within(panel).getByLabelText("Asset type"), "centrifugal_pump");
    expect(
      await within(panel).findByText(/Required roles: motor_current, de_bearing_temp/),
    ).toBeInTheDocument();
    await user.click(within(panel).getByLabelText("P-104B"));
    expect(within(panel).getByRole("button", { name: /Create/ })).toBeDisabled(); // preview first
    await user.click(within(panel).getByRole("button", { name: "Preview" }));
    const preview = await within(panel).findByRole("table", { name: "Preview per asset" });
    expect(within(preview).getAllByText("will be created")).toHaveLength(2);
    expect(within(preview).getByText("de_vibration")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Create 2 models" }));
    const done = await within(panel).findByRole("table", { name: "Results per asset" });
    expect(within(done).getAllByRole("link", { name: "Training…" })[1]).toHaveAttribute(
      "href",
      "/models/12/versions/1",
    );
    await waitFor(() =>
      expect(
        calls.filter((c: Call) => c.path === "/model-templates/4/apply").map((c) => c.body),
      ).toEqual([
        { assets: ["P-104A", "P-205"], preview: true },
        { assets: ["P-104A", "P-205"], preview: false },
      ]),
    );
  });
});
