import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { useRowKeys } from "./tableKeys";

function Table() {
  const rowKeys = useRowKeys();
  return (
    <table ref={rowKeys}>
      <tbody>
        {["A", "B", "C"].map((n, i) => (
          <tr key={n}>
            <td>
              <a href={`#${n}`}>{n}</a>
            </td>
            <td>{i !== 1 && <button type="button">Act {n}</button>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

describe("arrow keys in tables", () => {
  it("move to the same column of the next row, or that row's first control", async () => {
    const user = userEvent.setup();
    render(<Table />);
    screen.getByRole("link", { name: "A" }).focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("link", { name: "B" })).toHaveFocus();
    screen.getByRole("button", { name: "Act A" }).focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("link", { name: "B" })).toHaveFocus(); // no button in row B
    screen.getByRole("button", { name: "Act C" }).focus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("link", { name: "B" })).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("link", { name: "A" })).toHaveFocus();
  });
});
