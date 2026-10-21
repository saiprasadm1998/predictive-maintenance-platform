import * as Popover from "@radix-ui/react-popover";
import { useState } from "react";

import { formatDateTime } from "../app/format";
import {
  PRESETS,
  PRESET_LABELS,
  type Preset,
  displayTimeZone,
  useTimeRange,
} from "../app/timeRange";

/** "2026-10-21T14:05" for a datetime-local input, in the browser's (display) time zone. */
function toLocalInput(date: Date): string {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}

const SHORT: Record<Preset, string> = {
  "1h": "1 h",
  "24h": "24 h",
  "7d": "7 d",
  "30d": "30 d",
  "90d": "90 d",
};

/**
 * The global time range (PDS §2.2, §5): presets 1 h, 24 h, 7 d, 30 d, 90 d and a custom
 * range, always labelled with the time zone. The choice lives in the URL.
 */
export function TimeRangePicker() {
  const { range, setPreset, setCustom } = useTimeRange();
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const zone = displayTimeZone();

  const label = range.preset
    ? PRESET_LABELS[range.preset]
    : `${formatDateTime(range.from)} – ${formatDateTime(range.to)}`;

  function onOpenChange(next: boolean) {
    if (next) {
      setFrom(toLocalInput(range.from));
      setTo(toLocalInput(range.to));
      setProblem(null);
    }
    setOpen(next);
  }

  function apply(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const start = new Date(from);
    const end = new Date(to);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
      setProblem("Enter both a start and an end.");
      return;
    }
    if (start >= end) {
      setProblem("The end must be after the start.");
      return;
    }
    if (end.getTime() > Date.now() + 60_000) {
      setProblem("The end cannot be in the future.");
      return;
    }
    setCustom(start, end);
    setOpen(false);
  }

  return (
    <Popover.Root open={open} onOpenChange={onOpenChange}>
      <Popover.Trigger
        className="control time-range-trigger"
        aria-label={`Time range: ${label}, ${zone}`}
      >
        {label} <span className="muted">· {zone}</span> <span aria-hidden="true">▾</span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          className="picker"
          align="end"
          sideOffset={6}
          aria-label="Choose a time range"
        >
          <div className="picker-presets" role="group" aria-label="Presets">
            {PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                className="control picker-preset"
                aria-pressed={range.preset === preset}
                aria-label={PRESET_LABELS[preset]}
                onClick={() => {
                  setPreset(preset);
                  setOpen(false);
                }}
              >
                {SHORT[preset]}
              </button>
            ))}
          </div>
          <form className="picker-custom" onSubmit={apply} noValidate>
            <span className="muted">Custom range ({zone})</span>
            <label className="field">
              <span>From</span>
              <input
                className="control"
                type="datetime-local"
                value={from}
                onChange={(event) => setFrom(event.target.value)}
              />
            </label>
            <label className="field">
              <span>To</span>
              <input
                className="control"
                type="datetime-local"
                value={to}
                onChange={(event) => setTo(event.target.value)}
              />
            </label>
            <div role="alert" className="form-error">
              {problem}
            </div>
            <button type="submit" className="button button-primary">
              Apply
            </button>
          </form>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
