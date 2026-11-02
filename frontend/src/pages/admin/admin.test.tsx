import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ADMIN, ASSETS, type Call, fakeApi, sessionRoutes } from "../../test/fakeApi";
import { renderApp } from "../../test/renderApp";
import {
  changedFields,
  grantText,
  overridesOf,
  passwordProblems,
  ruleForm,
  ruleProblems,
} from "./adminModel";
import { ageText } from "./ingestionModel";

const ENGINEER = {
  ...ADMIN,
  id: 2,
  username: "eng",
  roles: [{ role: "model_engineer", scope_asset_id: null }],
};

function asUser(user: Omit<typeof ADMIN, "email"> & { email: string | null }) {
  const routes = sessionRoutes(true);
  routes["GET /auth/me"] = () => ({ status: 200, body: { user, csrf_token: "c" } });
  return routes;
}

describe("administration rules", () => {
  it("checks passwords as the server does", () => {
    expect(passwordProblems("vera", "short")).toEqual([
      "The password needs at least 12 characters",
    ]);
    expect(passwordProblems("vera", "my-name-is-vera!")).toEqual([
      "The password may not contain the username",
    ]);
    expect(passwordProblems("vera", "correct horse battery")).toEqual([]);
  });

  it("names a role with the part of the hierarchy it covers", () => {
    const assets = ASSETS as Parameters<typeof grantText>[1];
    expect(grantText({ role: "analyst", scope_asset_id: 5 }, assets)).toBe(
      "Reliability analyst (SA-AMM)",
    );
    expect(grantText({ role: "administrator", scope_asset_id: null }, assets)).toBe(
      "Administrator",
    );
  });

  it("keeps only the rule parameters this scope overrides", () => {
    const form = ruleForm({ spike_pct: 10, flatline: false });
    expect(form.spike_pct).toBe("10");
    expect(form.stale).toBe("");
    expect(overridesOf({ ...form, stale_factor: "4" })).toEqual({
      spike_pct: 10,
      flatline: false,
      stale_factor: 4,
    });
    expect(ruleProblems({ ...form, spike_pct: "-1" })).toEqual([
      "Spike above must be a number above 0",
    ]);
  });

  it("lists the fields an audited change touched", () => {
    expect(
      changedFields({
        id: 1,
        ts: "",
        user_id: 1,
        actor_type: "user",
        entity: "tag",
        entity_id: "3",
        action: "update",
        before: { unit: "C", range_hi: 100 },
        after: { unit: "°C", range_hi: 100 },
        ip: null,
      }),
    ).toEqual(["unit"]);
  });
});

describe("SCR-14 administration", () => {
  it("adds a user with a role limited to part of the hierarchy", async () => {
    const routes = asUser(ADMIN);
    routes["GET /users"] = () => ({ status: 200, body: [] });
    routes["POST /users"] = (call) => ({ status: 201, body: { id: 9, ...(call.body as object) } });
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin");

    await user.click(await screen.findByRole("button", { name: "Add a user" }));
    const form = screen.getByRole("region", { name: "Add a user" });
    await user.type(within(form).getByLabelText("Username"), "vera");
    await user.type(within(form).getByLabelText("Password"), "vera-password-1");
    await user.click(within(form).getByRole("button", { name: "Add user" }));
    expect(
      await within(form).findByText("The password may not contain the username"),
    ).toBeInTheDocument();
    await user.clear(within(form).getByLabelText("Password"));
    await user.type(within(form).getByLabelText("Password"), "correct horse battery");
    await user.selectOptions(within(form).getByLabelText("Role 1"), "analyst");
    await user.selectOptions(within(form).getByLabelText("Where role 1 applies"), "5");
    await user.click(within(form).getByRole("button", { name: "Add user" }));
    await waitFor(() =>
      expect(calls.find((c: Call) => c.method === "POST" && c.path === "/users")?.body).toEqual({
        username: "vera",
        display_name: "vera",
        email: null,
        password: "correct horse battery",
        roles: [{ role: "analyst", scope_asset_id: 5 }],
      }),
    );
  });

  it("shows a new API key once, then only its prefix", async () => {
    const routes = asUser(ADMIN);
    let keys: object[] = [];
    routes["GET /api-keys"] = () => ({ status: 200, body: keys });
    routes["POST /api-keys"] = () => {
      keys = [
        {
          id: 1,
          prefix: "abc123",
          name: "gateway A",
          scope: "ingest",
          created_at: "2026-10-22T08:00:00Z",
          revoked_at: null,
          last_used_at: null,
        },
      ];
      return { status: 201, body: { id: 1, key: "pmp_abc123_secret", prefix: "abc123" } };
    };
    fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin?tab=keys");

    await user.type(await screen.findByLabelText("Name"), "gateway A");
    await user.click(screen.getByRole("button", { name: "Issue key" }));
    expect(await screen.findByLabelText("The new key")).toHaveTextContent("pmp_abc123_secret");
    const table = await screen.findByRole("table", { name: "API keys" });
    expect(within(table).getByText("abc123…")).toBeInTheDocument();
    expect(within(table).queryByText(/secret/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "I have stored it" }));
    expect(screen.queryByText("pmp_abc123_secret")).not.toBeInTheDocument();
  });

  it("previews a data-quality change and asks to confirm when a tag would lose over 20 %", async () => {
    const routes = asUser(ENGINEER);
    routes["GET /dq/rules"] = () => ({
      status: 200,
      body: {
        scope: "global",
        version: 0,
        overrides: {},
        comment: "",
        created_at: null,
        defaults: { spike: true, spike_pct: 25 },
      },
    });
    routes["POST /dq/rules/preview"] = () => ({
      status: 200,
      body: {
        scope: "global",
        start: "",
        end: "",
        excluded_share: 0.05,
        warning: true,
        tags: [
          {
            tag_id: 1,
            source_name: "K101.TI1012.PV",
            asset_code: "K-101",
            cycles: 100,
            excluded: 30,
            excluded_share: 0.3,
            by_rule: { spike: 30 },
          },
        ],
      },
    });
    routes["PUT /dq/rules"] = (call) => ({
      status: 200,
      body: { rules: { version: 1 }, preview: {}, sent: call.body },
    });
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin");

    // A Model Engineer sees only the rules, not the administrator's tabs.
    expect(screen.queryByRole("link", { name: "Users and roles" })).not.toBeInTheDocument();
    await user.type(await screen.findByLabelText("Spike above"), "5");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled(); // preview first
    await user.click(screen.getByRole("button", { name: "Preview" }));
    const table = await screen.findByRole("table", { name: "Tags most affected" });
    expect(within(table).getByText("Spike 30")).toBeInTheDocument();
    expect(save).toBeDisabled();
    await user.click(screen.getByLabelText("Save anyway"));
    await user.click(save);
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
        scope: "global",
        overrides: { spike_pct: 5 },
        confirm: true,
      }),
    );
  });
});

describe("notifications", () => {
  const EVENTS = [
    { value: "alert_raised", label: "Alert raised" },
    { value: "alert_escalated", label: "Alert escalated to Alert" },
    { value: "case_assigned", label: "Case assigned to me" },
    { value: "case_overdue", label: "My case overdue" },
    { value: "model_review", label: "False alert to review (model engineers)" },
    { value: "source_stale", label: "Data source stale (administrators)" },
  ];

  it("lets any user subscribe to their own e-mail notifications", async () => {
    const analyst = {
      ...ADMIN,
      email: "ana@plant.test",
      roles: [{ role: "analyst", scope_asset_id: null }],
    };
    const routes = asUser(analyst);
    let subs: object[] = [];
    routes["GET /notifications/events"] = () => ({ status: 200, body: EVENTS });
    routes["GET /notifications/subscriptions"] = () => ({ status: 200, body: subs });
    routes["GET /assets"] = () => ({ status: 200, body: { items: ASSETS, next_cursor: null } });
    routes["POST /notifications/subscriptions"] = (call) => {
      subs = [
        {
          id: 1,
          scope_code: "K-101",
          channel: "email",
          created_at: "2026-10-28T00:00:00Z",
          updated_at: "2026-10-28T00:00:00Z",
          ...(call.body as object),
        },
      ];
      return { status: 201, body: subs[0] };
    };
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin?tab=notifications");

    expect(await screen.findByText(/You have no subscriptions/)).toBeInTheDocument();
    expect(screen.getByText(/E-mails go to ana@plant.test/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add a subscription" }));
    const form = screen.getByRole("form", { name: "New subscription" });
    // model engineers' and administrators' events are not offered to an analyst
    expect(within(form).queryByLabelText(/False alert to review/)).toBeNull();
    expect(within(form).queryByLabelText(/Data source stale/)).toBeNull();
    await user.selectOptions(within(form).getByLabelText("Minimum priority"), "P1");
    await user.click(within(form).getByLabelText("Case assigned to me"));
    await user.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(calls.find((c: Call) => c.method === "POST")?.body).toEqual({
        scope_asset_id: null,
        min_priority: "P1",
        events: ["alert_raised", "alert_escalated", "case_assigned"],
        enabled: true,
      }),
    );
    expect(
      await screen.findByText(
        "P1 only · K-101 · Alert raised, Alert escalated to Alert, Case assigned to me",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Notification log" })).toBeNull();
  });

  it("shows administrators the delivery log and sends a test e-mail", async () => {
    const routes = asUser(ADMIN);
    routes["GET /notifications/log"] = () => ({
      status: 200,
      body: [
        {
          id: 3,
          user_id: 2,
          event: "alert_raised",
          alert_id: 1,
          case_id: null,
          recipient: "ana@plant.test",
          subject: "[PMP] P1 Alert raised · K-101 · DI",
          status: "failed",
          attempts: 6,
          next_attempt_at: null,
          last_error: "ConnectionRefusedError: relay down",
          summary_id: null,
          created_at: "2026-10-28T08:00:00Z",
          sent_at: null,
        },
      ],
    });
    routes["POST /notifications/test"] = () => ({ status: 204, body: null });
    const { calls } = fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin?tab=notification-log");

    const table = await screen.findByRole("table", { name: "Notifications, newest first" });
    expect(within(table).getByText("ConnectionRefusedError: relay down")).toBeInTheDocument();
    expect(within(table).getByText("failed")).toBeInTheDocument();
    await user.type(screen.getByLabelText("To"), "ops@plant.test");
    await user.click(screen.getByRole("button", { name: "Send test e-mail" }));
    expect(await screen.findByText("Sent to ops@plant.test.")).toBeInTheDocument();
    expect(calls.find((c: Call) => c.path === "/notifications/test")?.body).toEqual({
      to: "ops@plant.test",
    });
  });
});

describe("ingestion health (FR-ING-07)", () => {
  it("says how long ago, from the server clock", () => {
    const now = "2026-10-29T12:00:00Z";
    expect(ageText(null, now)).toBe("never");
    expect(ageText("2026-10-29T11:59:15Z", now)).toBe("45 s ago");
    expect(ageText("2026-10-29T11:57:00Z", now)).toBe("3 min ago");
    expect(ageText("2026-10-29T09:55:00Z", now)).toBe("2 h 5 min ago");
  });

  it("warns administrators of a stale source and clock skew, tag by tag", async () => {
    const routes = asUser(ADMIN);
    const source = {
      accepted_total: 1200,
      rejected_total: 3,
      per_minute: 4,
      interval_s: 60,
      tags: 2,
      stale_after_s: 120,
    };
    routes["GET /ingest/health"] = () => ({
      status: 200,
      body: {
        checked_at: "2026-10-29T12:00:00Z",
        sources: [
          {
            ...source,
            source: "gw-1",
            last_received_at: "2026-10-29T11:57:00Z",
            last_sample_ts: "2026-10-29T11:57:00Z",
            stale: true,
            skew_s: 0,
            skewed: false,
          },
          {
            ...source,
            source: "gw-2",
            last_received_at: "2026-10-29T11:59:50Z",
            last_sample_ts: "2026-10-29T11:58:20Z",
            stale: false,
            skew_s: 90,
            skewed: true,
          },
        ],
        tags: [
          {
            tag_id: 1,
            source: "gw-1",
            source_name: "K101.TT01",
            asset_code: "K-101",
            interval_s: 60,
            last_sample_ts: "2026-10-29T11:57:00Z",
            stale: true,
          },
          {
            tag_id: 2,
            source: "gw-2",
            source_name: "P104.FT01",
            asset_code: "P-104A",
            interval_s: 60,
            last_sample_ts: "2026-10-29T11:58:20Z",
            stale: false,
          },
        ],
      },
    });
    fakeApi(routes);
    const user = userEvent.setup();
    renderApp("/admin?tab=ingestion");

    const sources = await screen.findByRole("table", { name: "Gateway sources" });
    expect(screen.getByText("2 sources need attention.", { exact: false })).toBeInTheDocument();
    const gw1 = within(sources).getByRole("row", { name: /gw-1/ });
    expect(within(gw1).getByText("Stale: nothing for over 120 s")).toBeInTheDocument();
    expect(within(gw1).getAllByText("3 min ago")).toHaveLength(2);
    const gw2 = within(sources).getByRole("row", { name: /gw-2/ });
    expect(within(gw2).getByText("Receiving · clock skew")).toBeInTheDocument();
    expect(within(gw2).getByText("+90 s")).toBeInTheDocument();

    const tags = screen.getByRole("table", { name: "Tags and their newest sample" });
    expect(within(tags).getAllByRole("row")).toHaveLength(3);
    await user.click(screen.getByLabelText("Stale only"));
    expect(within(tags).getAllByRole("row")).toHaveLength(2);
    expect(within(tags).getByText("K101.TT01")).toBeInTheDocument();
  });
});

describe("operational alerts (ARC §10.3)", () => {
  it("shows administrators what needs attention, linked where it can be seen", async () => {
    const routes = asUser(ADMIN);
    routes["GET /ops/alerts"] = () => ({
      status: 200,
      body: [
        {
          kind: "source_stale",
          severity: "critical",
          text: "Source gw-1 has sent nothing for 12 min.",
          since: "2026-11-02T10:00:00Z",
          link: "/admin?tab=ingestion",
        },
        {
          kind: "job_queue",
          severity: "warning",
          text: "2 jobs waiting, the oldest for 14 min: is the worker running?",
          since: "2026-11-02T10:00:00Z",
          link: null,
        },
      ],
    });
    fakeApi(routes);
    renderApp("/admin?tab=retention");

    const panel = await screen.findByRole("region", { name: "Operational alerts" });
    expect(within(panel).getByText(/Source gw-1 has sent nothing/)).toBeInTheDocument();
    expect(within(panel).getByText(/2 jobs waiting/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/admin?tab=ingestion",
    );
  });
});
