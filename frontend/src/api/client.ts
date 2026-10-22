/**
 * The one way the front end talks to the web role (ARC §7). Everything goes through
 * /api/v1 on the same origin: the browser sends the session cookie itself, and every change
 * (POST, PUT, PATCH, DELETE) carries the CSRF token in X-CSRF-Token (ARC §9.3).
 * Errors arrive as RFC 9457 problem details and are thrown as ApiError.
 */

export const API_BASE = "/api/v1";

let csrfToken: string | null = null;

/** Set from the sign-in and /auth/me responses; cleared on sign-out. */
export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem;

  constructor(status: number, problem: Problem) {
    super(problem.detail ?? problem.title ?? `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }

  /** The session has ended or never started: the user must sign in. */
  get unauthenticated(): boolean {
    return this.status === 401;
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  method?: Method;
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

export function apiUrl(path: string, query?: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const search = params.toString();
  return `${API_BASE}${path}${search ? `?${search}` : ""}`;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  // A FormData body (file uploads) sets its own multipart Content-Type with the boundary.
  const form = options.body instanceof FormData;
  if (options.body !== undefined && !form) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(apiUrl(path, options.query), {
      method,
      headers,
      credentials: "same-origin",
      body:
        options.body === undefined
          ? undefined
          : form
            ? (options.body as FormData)
            : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, {
      title: "Cannot reach the server",
      detail: "The PMP server did not answer. Check the connection and try again.",
      code: "network",
    });
  }

  if (!response.ok) throw new ApiError(response.status, await readProblem(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function readProblem(response: Response): Promise<Problem> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object") return body as Problem;
  } catch {
    // not JSON: fall through
  }
  return { status: response.status, title: response.statusText || "Request failed" };
}

/** The messages of a failed request: the problem's list when it has one, else its detail. */
export function errorMessages(error: unknown): string[] {
  if (error instanceof ApiError && Array.isArray(error.problem.problems))
    return error.problem.problems.map(String);
  return error instanceof Error ? [error.message] : [];
}
