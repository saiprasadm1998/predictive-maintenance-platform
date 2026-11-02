# Accessibility: WCAG 2.1 AA check (PDS §8, plan 9.2)

How PMP's screens were checked against WCAG 2.1 level AA, as of 2 November 2026, and
what still needs a person.

## Automated checks (run in CI on every push)

| Check | What it covers | Where |
| ----- | -------------- | ----- |
| axe-core in the browser, WCAG 2.0 and 2.1 A and AA rules, colour contrast included | 12 screens with realistic data, in the light and the dark theme: fleet overview, asset analysis, diagnostics, alert list, cases, model management, model builder, sensor health, failure-mode library, registry and import, users, my notifications | `frontend/e2e/a11y.spec.ts` (`make fe-e2e`) |
| axe-core on the sign-in page and the app shell | landmarks, names, roles | `frontend/src/test/a11y.test.tsx` |
| Keyboard only | skip link, then the navigation rail, then the top bar; the skip link moves focus to the content | `frontend/src/test/a11y.test.tsx` |
| Colour tokens | every text colour 4.5:1 and every graphical colour 3:1 against the panel, both themes (1.4.3, 1.4.11) | `frontend/src/test/contrast.test.ts` |
| Lint | `eslint-plugin-jsx-a11y` rules on every component | `make fe-lint` |

Result: no violations. One was found and fixed in this check: the sensor table's
"Chart" / "Charted" toggle on asset analysis was named "Remove …" for screen readers, so
its spoken name did not contain its visible text (2.5.3 Label in Name). It is now
"Charted …" with its pressed state.

## Built in by design

- Charts have a text alternative: every trend can be shown as a data table ("View data"),
  each chart is a labelled figure, and arrow keys move its cursor (1.1.1, 1.3.1, PDS §8).
- Band and status are never shown by colour alone: each has its word or icon (1.4.1).
- Live changes are announced through a polite live region; status messages use
  `role="status"` (4.1.3).
- Motion is reduced when the system asks for it (`prefers-reduced-motion`).
- Every control is reachable and usable by keyboard, with a visible focus ring (2.1.1,
  2.4.7); dialogs keep focus inside and return it on close.

## Still to check by hand (automated tools cannot)

These need a person and are part of the 9.3 handover review:

- A screen-reader pass (VoiceOver or NVDA) through the main journeys: fleet → asset →
  alert → case.
- Zoom to 200 % and a 320 px wide window: content reflows without loss (1.4.4, 1.4.10).
- Text spacing overrides (1.4.12) and the focus order on the busiest screens (2.4.3).
