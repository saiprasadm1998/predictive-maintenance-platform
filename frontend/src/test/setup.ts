import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

import { FakeEventSource } from "./fakeEventSource";

// findBy and waitFor wait up to 1 s by default; the CI runners are slower than a laptop
// and a first render of a lazily loaded screen can take longer (plan 9.3).
configure({ asyncUtilTimeout: 5000 });

// jsdom lacks these browser APIs.
class NoResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

// jsdom has no canvas; tools that probe for one (axe-core) get "none" instead of a warning.
HTMLCanvasElement.prototype.getContext = (() =>
  null) as typeof HTMLCanvasElement.prototype.getContext;

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("ResizeObserver", NoResizeObserver);
});

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  vi.unstubAllGlobals();
});
