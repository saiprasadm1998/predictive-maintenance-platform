import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fakeChart = {
  group: "",
  setOption: vi.fn(),
  dispatchAction: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
  on: vi.fn(),
  off: vi.fn(),
  getZr: () => ({ on: vi.fn(), off: vi.fn() }),
};

vi.mock("./charting", () => ({
  echarts: { init: vi.fn(() => fakeChart), connect: vi.fn() },
  chartColors: () => ({
    text: "#t",
    textMuted: "#m",
    line: "#l",
    lineSoft: "#s",
    band: "#b",
    panel: "#p",
    alert: "#a",
    watch: "#w",
    watchText: "#wt",
    fault: "#f",
    unknown: "#u",
  }),
}));

import { echarts } from "./charting";
import { TrendChart } from "./TrendChart";

const T0 = Date.UTC(2026, 9, 21, 8, 0);
const DATA = {
  actual: [
    [T0, 80.5],
    [T0 + 60_000, null],
    [T0 + 120_000, 81.25],
  ] as [number, number | null][],
};
const SETTINGS = { unit: "°C", from: T0, to: T0 + 180_000 };

describe("TrendChart", () => {
  beforeEach(() => vi.clearAllMocks());

  it("joins the page's chart group so cursor and zoom are shared", () => {
    render(<TrendChart title="TI-1012 DE bearing temperature" data={DATA} settings={SETTINGS} />);
    expect(fakeChart.group).toBe("page");
    expect(echarts.connect).toHaveBeenCalledWith("page");
    expect(fakeChart.setOption).toHaveBeenCalledTimes(1);
  });

  it("moves the cursor with the arrow keys and says where it is", () => {
    render(<TrendChart title="TI-1012" data={DATA} settings={SETTINGS} />);
    const cursor = screen.getByRole("slider", { name: /TI-1012/ });
    expect(cursor).toHaveAttribute("aria-valuetext", "No point selected");
    fireEvent.keyDown(cursor, { key: "ArrowRight" });
    expect(fakeChart.dispatchAction).toHaveBeenLastCalledWith({
      type: "showTip",
      seriesIndex: 0,
      dataIndex: 0,
    });
    expect(cursor.getAttribute("aria-valuetext")).toMatch(/: 80\.5 °C$/);
    fireEvent.keyDown(cursor, { key: "ArrowRight" });
    expect(cursor.getAttribute("aria-valuetext")).toMatch(/: no value$/);
    fireEvent.keyDown(cursor, { key: "End" });
    expect(cursor).toHaveAttribute("aria-valuenow", "2");
    fireEvent.keyDown(cursor, { key: "Escape" });
    expect(fakeChart.dispatchAction).toHaveBeenLastCalledWith({ type: "hideTip" });
  });

  it("offers the data as a table (View data)", async () => {
    const user = userEvent.setup();
    render(<TrendChart title="TI-1012" data={DATA} settings={SETTINGS} />);
    await user.click(screen.getByRole("button", { name: "View data" }));
    const table = screen.getByRole("table", { name: "TI-1012" });
    expect(table.querySelectorAll("tbody tr")).toHaveLength(3);
    expect(screen.getByRole("columnheader", { name: "Actual (°C)" })).toBeInTheDocument();
    expect(table.textContent).toContain("—");
  });

  it("redraws with the theme's colours when the theme changes", async () => {
    render(<TrendChart title="TI-1012" data={DATA} settings={SETTINGS} />);
    document.documentElement.dataset.theme = "dark";
    await vi.waitFor(() => expect(fakeChart.setOption).toHaveBeenCalledTimes(2));
  });
});
