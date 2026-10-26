import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ModelSummary } from "../../api/types";
import { MODELS, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";
import { alertRate, lifecycleChoices } from "./modelsModel";

const deployed = MODELS[0] as unknown as ModelSummary;
const v = (version: number, status: string) => ({
  id: version,
  version,
  status,
  algorithm: "median",
  created_at: "2026-10-01T00:00:00Z",
  status_changed_at: null,
});

describe("lifecycle choices (ARC Figure 7)", () => {
  it("offers pause and retire on a deployed version", () => {
    expect(lifecycleChoices(deployed).map((c) => c.action)).toEqual(["pause", "retire"]);
  });

  it("offers deploy and reject on a newer validated version, saying what it supersedes", () => {
    const model = { ...deployed, latest: v(2, "Validated"), in_service: v(1, "Deployed") };
    const choices = lifecycleChoices(model);
    expect(choices.map((c) => c.label)).toEqual([
      "Deploy v2",
      "Reject v2",
      "Pause v1",
      "Retire v1",
    ]);
    expect(choices[0]!.consequence).toContain("replaces v1 (kept as Superseded)");
    expect(choices[0]!.consequence).toContain("open alerts carry on");
    expect(choices.find((c) => c.action === "retire")!.danger).toBe(true);
  });

  it("offers resume on a paused version and nothing on a model never deployed", () => {
    expect(
      lifecycleChoices({ ...deployed, in_service: v(1, "Paused") }).map((c) => c.action),
    ).toEqual(["resume", "retire"]);
    expect(lifecycleChoices({ ...deployed, latest: v(1, "Draft"), in_service: null })).toEqual([]);
  });

  it("states the alert rate per week", () => {
    expect(alertRate(30)).toBe("7.0 / week");
  });
});

describe("SCR-10 model management", () => {
  it("lists models and pauses one after confirming the consequence", async () => {
    const routes = sessionRoutes(true);
    routes["GET /models"] = () => ({
      status: 200,
      body: MODELS.map((m) => ({ ...m, alerts_30d: 3 })),
    });
    routes["POST /versions/1/pause"] = () => ({
      status: 200,
      body: { ...MODELS[0], versions: [], alert_rules: [] },
    });
    const { calls } = fakeApi(routes);
    renderApp("/models");
    const table = await screen.findByRole("table");
    const k101 = within(table).getByRole("link", { name: "K-101 / main" }).closest("tr")!;
    expect(k101).toHaveTextContent("v1 · median · Deployed");
    expect(k101).toHaveTextContent("0.7 / week");
    const user = userEvent.setup();
    await user.click(within(k101).getByRole("button", { name: "Pause v1" }));
    const dialog = screen.getByRole("dialog", { name: "Pause v1 of K-101 / main?" });
    expect(dialog).toHaveTextContent("alerts go out of service");
    await user.click(within(dialog).getByRole("button", { name: "Pause v1" }));
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/versions/1/pause")).toBe(true),
    );
  });
});
