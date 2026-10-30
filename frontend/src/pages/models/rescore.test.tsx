import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { ModelDetail, VersionSummary } from "../../api/types";
import { createQueryClient } from "../../app/queryClient";
import { fakeApi } from "../../test/fakeApi";
import { RescorePanel } from "./RescorePanel";
import { canRescore, toLocalInput } from "./modelsModel";

const version = {
  id: 7,
  version: 3,
  status: "Deployed",
  algorithm: "median",
  created_at: "2026-10-01T00:00:00Z",
  status_changed_at: null,
} as VersionSummary;
const model = { id: 1, asset_code: "K-101", name: "main" } as unknown as ModelDetail;

describe("re-score (FR-RUN-05)", () => {
  it("is offered for versions with a trained model", () => {
    expect(canRescore(version)).toBe(true);
    expect(canRescore({ ...version, status: "Retired" })).toBe(true);
    expect(canRescore({ ...version, status: "Training" })).toBe(false);
    expect(canRescore({ ...version, status: "Draft" })).toBe(false);
  });

  it("queues the shown period and follows the job to the end", async () => {
    let polls = 0;
    const { calls } = fakeApi({
      "POST /versions/7/rescore": () => ({ status: 202, body: { job_id: 41 } }),
      "GET /jobs/41": () => {
        polls += 1;
        return {
          status: 200,
          body: {
            id: 41,
            type: "scoring.rescore",
            status: polls > 1 ? "succeeded" : "running",
            progress: polls > 1 ? 100 : 40,
            attempts: 1,
            result: polls > 1 ? { cycles: 1440, end: "2026-10-29T12:00:00Z" } : null,
            error: null,
            created_at: "2026-10-29T12:00:00Z",
            finished_at: null,
          },
        };
      },
    });
    const client = createQueryClient();
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter
          initialEntries={["/?from=2026-10-28T12:00:00.000Z&to=2026-10-29T12:00:00.000Z"]}
        >
          <RescorePanel model={model} version={version} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await user.click(screen.getByRole("button", { name: "Re-score…" }));
    expect(screen.getByLabelText("From")).toHaveValue(
      toLocalInput(new Date("2026-10-28T12:00:00Z")),
    );
    expect(screen.getByText(/No alert changes and no e-mail is sent/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Re-score" }));
    expect(await screen.findByText("Re-scoring… 40 %")).toBeInTheDocument();
    expect(
      await screen.findByText(/Done: 1440 cycles re-scored/, {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/versions/7/rescore")?.body).toEqual({
      start: "2026-10-28T12:00:00.000Z",
      end: "2026-10-29T12:00:00.000Z",
    });
  });
});
