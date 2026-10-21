import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * PDS §3.1, §8 (WCAG 1.4.3, 1.4.11): text colours reach 4.5:1 and graphical colours 3:1
 * against --panel, in the light and the dark theme. Checked from the token file itself.
 */
const css = readFileSync(resolve(__dirname, "../styles/tokens.css"), "utf8");

function tokens(selector: string): Record<string, string> {
  const start = css.lastIndexOf(`${selector} {`);
  const block = css.slice(start, css.indexOf("}", start));
  const found: Record<string, string> = {};
  for (const m of block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    found[m[1]!] = m[2]!.toLowerCase();
  }
  return found;
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}

function ratio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

const TEXT = ["text", "text-muted", "alert", "watch-text", "fault", "unknown-text"];
// --watch itself is 2.4:1 on white (PDS §3.1 value), so Watch shapes are outlined and the
// warning limit drawn in --watch-text, which is what has to reach 3:1 (decision 6.1).
const GRAPHICS = ["alert", "watch-text", "fault", "unknown", "text-muted"];

describe.each([
  ["light", ":root"],
  ["dark", ':root[data-theme="dark"]'],
])("%s theme contrast", (_name, selector) => {
  const t = tokens(selector);
  it("reads the tokens", () => expect(Object.keys(t).length).toBeGreaterThan(10));
  it.each(TEXT)("text --%s reaches 4.5:1 on --panel", (name) => {
    expect(ratio(t[name]!, t.panel!)).toBeGreaterThanOrEqual(4.5);
  });
  it.each(GRAPHICS)("graphic --%s reaches 3:1 on --panel", (name) => {
    expect(ratio(t[name]!, t.panel!)).toBeGreaterThanOrEqual(3);
  });
});
