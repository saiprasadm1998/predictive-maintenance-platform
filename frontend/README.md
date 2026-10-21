# Front end

React 18, TypeScript and Vite single-page app (PMP-PDS-001, ARC §11). Everything it shows is
read through the REST API (`/api/v1`); in development Vite passes `/api` on to the web role,
so the session cookie and CSRF token work without any CORS setup.

```
make fe-install          # once, and after package.json changes
make web                 # terminal 1: the web role on :8000
make fe-dev              # terminal 2: http://localhost:5173
make fe-check            # lint, format check, tests, type check and build
```

Layout:

- `src/api/` the API client (`client.ts`: CSRF header, problem details as `ApiError`) and
  typed calls per resource.
- `src/app/` routing (`screens.ts` is the route table: one entry per SCR-nn screen),
  session, time range in the URL, theme, formatting, and the live event stream
  (`LiveEvents.tsx`: which reads each event refreshes is in `liveContext.ts`).
- `src/layout/` the app shell: navigation rail, top bar, asset search, user menu.
- `src/components/` shared components: StatusChip, AlertStateChip, HealthScore, HealthBar,
  TrendChart (all chart conventions live in `trendOptions.ts`), TimeRangePicker, ConfirmDialog.
  See them at `/design` in development.
- `src/pages/` screens; until a screen's sub-phase builds it, a placeholder shows the state
  it was opened with.
- `src/styles/tokens.css` the PDS §3.1 design tokens, light and dark (control-room) themes.
  Components use the tokens only, never raw colours.
