import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fakeApi, sessionRoutes } from "../test/fakeApi";
import { FakeEventSource } from "../test/fakeEventSource";
import { renderApp } from "../test/renderApp";
import { formatTime } from "./format";

async function signedInApp(path = "/fleet") {
  const api = fakeApi(sessionRoutes(true));
  const view = renderApp(path);
  await screen.findByRole("navigation", { name: "Main" });
  const stream = FakeEventSource.latest();
  return { ...api, ...view, stream };
}

describe("live events (ARC §7.4, PDS §6)", () => {
  it("opens the stream and shows the last scoring cycle", async () => {
    const { stream } = await signedInApp();
    expect(stream.url).toBe("/api/v1/events");
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
    act(() => stream.open());
    const before = formatTime(new Date("2026-10-21T08:15:00Z"));
    expect(await screen.findByText(new RegExp(`Live · scored ${before}`))).toBeInTheDocument();

    act(() =>
      stream.emit("score.updated", {
        type: "score.updated",
        model_id: 3,
        ts: "2026-10-21T08:16:00Z",
      }),
    );
    const after = formatTime(new Date("2026-10-21T08:16:00Z"));
    expect(await screen.findByText(new RegExp(`Live · scored ${after}`))).toBeInTheDocument();
  });

  it("marks the affected reads stale, once per burst of events", async () => {
    const { stream, calls } = await signedInApp();
    act(() => stream.open());
    await waitFor(() => expect(calls.filter((c) => c.path === "/fleet/kpis")).toHaveLength(1));
    act(() => {
      for (const id of [1, 2, 3])
        stream.emit("score.updated", {
          type: "score.updated",
          model_id: id,
          ts: "2026-10-21T08:16:00Z",
        });
    });
    await waitFor(() => expect(calls.filter((c) => c.path === "/fleet/kpis")).toHaveLength(2), {
      timeout: 3000,
    });
  });

  it("announces a new alert to screen readers", async () => {
    const { stream } = await signedInApp();
    act(() => stream.open());
    act(() =>
      stream.emit("alert.changed", {
        type: "alert.changed",
        alert_id: 9,
        model_id: 3,
        state: "Active-Unacknowledged",
        severity: "Alert",
        priority: "P1",
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("New Alert alert, priority P1"),
    );
  });

  it("reads everything again after a reconnect", async () => {
    const { stream, calls } = await signedInApp();
    act(() => stream.open());
    await waitFor(() => expect(calls.filter((c) => c.path === "/fleet/kpis")).toHaveLength(1));
    act(() => stream.drop());
    expect(await screen.findByText("Connecting…")).toBeInTheDocument();
    act(() => stream.open());
    await waitFor(() => expect(calls.filter((c) => c.path === "/fleet/kpis")).toHaveLength(2));
  });

  it("goes to sign-in when the stream says the session ended", async () => {
    const { stream, router } = await signedInApp("/alerts");
    act(() => stream.open());
    act(() => stream.emit("session.ended", { type: "session.ended" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
    expect(stream.readyState).toBe(FakeEventSource.CLOSED);
  });
});
