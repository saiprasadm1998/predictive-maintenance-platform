import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AlertStateChip } from "./AlertStateChip";
import { ConfirmDialog } from "./ConfirmDialog";
import { HealthBar } from "./HealthBar";
import { HealthScore } from "./HealthScore";
import { StatusChip } from "./StatusChip";
import { ALERT_STATES, BANDS, NE107, SEVERITIES, bandLook } from "./status";

function shapeOf(container: HTMLElement): string | null {
  return container.querySelector(".status-shape")?.getAttribute("data-shape") ?? null;
}

describe("no status by colour alone (PDS §3.2, WCAG 1.4.1)", () => {
  const cases = [
    ...BANDS.map((value) => ({ kind: "band" as const, value })),
    ...SEVERITIES.map((value) => ({ kind: "severity" as const, value })),
    ...NE107.map((value) => ({ kind: "ne107" as const, value })),
  ];

  it.each(cases)("$kind $value has a shape and a text label", (props) => {
    const { container } = render(<StatusChip {...props} />);
    expect(shapeOf(container)).not.toBeNull();
    expect(container.textContent?.trim().length).toBeGreaterThan(2);
  });

  it("gives each health band its own shape, so bands differ in greyscale", () => {
    const shapes = BANDS.map((band) => bandLook(band).shape);
    expect(new Set(shapes).size).toBe(BANDS.length);
  });

  it.each(ALERT_STATES)("alert state %s has a shape and text, for both severities", (state) => {
    for (const severity of SEVERITIES) {
      const { container, unmount } = render(<AlertStateChip state={state} severity={severity} />);
      expect(shapeOf(container)).toBe(severity === "Alert" ? "triangle" : "diamond");
      expect(container.textContent).toContain(severity === "Alert" ? "ALERT" : "WARNING");
      unmount();
    }
  });

  it("uses the labels of the design spec", () => {
    render(
      <>
        <StatusChip kind="band" value="Alert" />
        <StatusChip kind="band" value="Unknown" detail="insufficient data" />
        <StatusChip kind="ne107" value="Failure" detail="flatline" />
      </>,
    );
    expect(screen.getByText("ALERT")).toBeInTheDocument();
    expect(screen.getByText(/Unknown/).textContent).toBe("Unknown — insufficient data");
    expect(screen.getByText(/Failure/).textContent).toBe("Failure: flatline");
  });
});

describe("AlertStateChip (ISA-18.2: state, severity and acknowledgement together)", () => {
  it("shows unacknowledged in bold and acknowledged in regular weight", () => {
    const { container: unack } = render(
      <AlertStateChip state="Active-Unacknowledged" severity="Alert" />,
    );
    const { container: ack } = render(
      <AlertStateChip state="Active-Acknowledged" severity="Alert" />,
    );
    expect(unack.firstElementChild).not.toHaveClass("chip-regular");
    expect(unack.textContent).toContain("Active · unack");
    expect(ack.firstElementChild).toHaveClass("chip-regular");
    expect(ack.textContent).toContain("Active · ack");
  });

  it("shows how long a shelf has left, with a clock badge", () => {
    const now = new Date("2026-10-21T10:00:00Z");
    const { container } = render(
      <AlertStateChip
        state="Shelved"
        severity="Warning"
        shelvedUntil={new Date("2026-10-21T13:20:00Z")}
        now={now}
      />,
    );
    expect(container.textContent).toContain("Shelved · 3 h 20 min left");
    expect(container.querySelector(".chip-badge")).not.toBeNull();
    expect(container.firstElementChild).toHaveClass("tone-unknown");
  });
});

describe("health", () => {
  it("HealthBar is a meter with limit ticks, and a dash without a score", () => {
    const { container } = render(<HealthBar health={41.6} warningAt={60} alertAt={40} />);
    const meter = screen.getByRole("meter", { name: "Health" });
    expect(meter).toHaveAttribute("aria-valuenow", "42");
    expect(container.querySelectorAll(".health-bar-tick")).toHaveLength(2);
    render(<HealthBar health={null} />);
    expect(screen.getByLabelText("Health: no score")).toHaveTextContent("—");
  });

  it("HealthScore reads 'Health 41 · ALERT' with the DI and its limits", () => {
    const { container } = render(
      <HealthScore health={41} band="Alert" di={29.46} diWarning={15} diAlert={25} />,
    );
    const row = container.querySelector(".health-score-row") as HTMLElement;
    expect(within(row).getByText("Health")).toBeInTheDocument();
    expect(within(row).getByText("41")).toBeInTheDocument();
    expect(within(row).getByText("ALERT")).toBeInTheDocument();
    expect(container.textContent).toContain("DI 29.5 %");
    expect(container.firstElementChild).toHaveAttribute(
      "title",
      "Warning at DI 15.0 %, alert at DI 25.0 %",
    );
  });
});

describe("ConfirmDialog (PDS §6)", () => {
  it("states the consequence and needs a reason before confirming", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Shelve 2 alerts"
        consequence="They stop notifying until the shelf ends."
        confirmLabel="Shelve"
        reasonLabel="Reason"
        onConfirm={onConfirm}
      />,
    );
    const dialog = screen.getByRole("dialog", { name: "Shelve 2 alerts" });
    expect(dialog).toHaveAccessibleDescription("They stop notifying until the shelf ends.");
    const confirm = within(dialog).getByRole("button", { name: "Shelve" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByLabelText(/Reason/), "  sensor work on P-104A ");
    await user.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith("sensor work on P-104A");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("keeps the dialog open and says why when the action fails", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    render(
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Retire model"
        consequence="Scoring stops for good."
        confirmLabel="Retire"
        danger
        onConfirm={() => Promise.reject(new Error("Only a Deployed version can be retired."))}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Retire" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only a Deployed version can be retired.",
    );
    expect(onOpenChange).not.toHaveBeenCalled();
  });
});
