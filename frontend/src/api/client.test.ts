import { afterEach, describe, expect, it, vi } from "vitest";

import { fakeApi } from "../test/fakeApi";
import { ApiError, api, apiUrl, setCsrfToken } from "./client";

afterEach(() => setCsrfToken(null));

describe("api client", () => {
  it("sends the CSRF token on changes only", async () => {
    const { calls } = fakeApi({
      "GET /things": () => ({ status: 200, body: [] }),
      "POST /things": () => ({ status: 201, body: { id: 1 } }),
    });
    setCsrfToken("token-1");
    await api("/things");
    await api("/things", { method: "POST", body: { name: "x" } });
    expect(calls[0]?.headers["X-CSRF-Token"]).toBeUndefined();
    expect(calls[1]?.headers["X-CSRF-Token"]).toBe("token-1");
    expect(calls[1]?.body).toEqual({ name: "x" });
  });

  it("turns problem details into ApiError with the detail as message", async () => {
    fakeApi({
      "GET /models/9": () => ({
        status: 404,
        body: {
          title: "Not found",
          status: 404,
          detail: "Model 9 does not exist.",
          code: "not_found",
        },
      }),
    });
    const error = await api("/models/9").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("Model 9 does not exist.");
    expect((error as ApiError).problem.code).toBe("not_found");
    expect((error as ApiError).unauthenticated).toBe(false);
  });

  it("explains a network failure in plain terms", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    const error = await api("/fleet/kpis").catch((e: unknown) => e);
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).message).toMatch(/did not answer/);
  });

  it("builds query strings and leaves out empty values", () => {
    expect(apiUrl("/assets", { limit: 500, cursor: null, tree: true })).toBe(
      "/api/v1/assets?limit=500&tree=true",
    );
  });
});
