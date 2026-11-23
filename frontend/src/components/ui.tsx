/**
 * Building blocks of the Traverse Predictive Maintenance screens. Each one renders the
 * markup and classes defined in styles/tpm.css, so screens stay consistent with the design.
 */
import * as RadixDialog from "@radix-ui/react-dialog";
import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import type { Band } from "./status";
import { bandTone } from "./tones";

export type ToneName = "danger" | "warning" | "info" | "success" | "unknown" | "neutral";

/** Outline icon, 24 x 24 path data. */
export function Icon({ d, size }: { d: string; size?: 16 | 20 }) {
  return (
    <svg
      className={`ico${size ? ` ico${size}` : ""}`}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <path d={d} />
    </svg>
  );
}

import { ICONS } from "./icons";

export { ICONS };

/** Status pill with a dot: bands, states, causes. */
export function Pill({
  tone,
  children,
  title,
  trunc,
}: {
  tone?: ToneName | null;
  children: ReactNode;
  title?: string;
  trunc?: boolean;
}) {
  return (
    <span
      className={`pill${tone && tone !== "neutral" ? ` p-${tone}` : ""}${trunc ? " trunc" : ""}`}
      title={title}
    >
      <span className="d" />
      {children}
    </span>
  );
}

/** Small square badge: priorities, counts, criticality, roles. */
export function Badge({ tone, children }: { tone?: ToneName | "ai" | null; children: ReactNode }) {
  return <span className={`bdg${tone && tone !== "neutral" ? ` b-${tone}` : ""}`}>{children}</span>;
}

export function BandPill({ band }: { band: Band | null | undefined }) {
  return <Pill tone={bandTone(band)}>{band ?? "Not monitored"}</Pill>;
}

/** Health bar with the number; hatched when there is no score. */
export function HealthBar({ health, band }: { health: number | null; band?: Band | null }) {
  const fill =
    health === null ? "unknown" : band === "Alert" ? "danger" : band === "Watch" ? "warning" : "";
  return (
    <span className="hb">
      <span className="tr">
        <span className={`fl ${fill}`} style={{ width: `${health ?? 100}%` }} />
      </span>
      <span className="num" style={{ minWidth: 32, textAlign: "right" }}>
        {health === null ? "n/a" : Math.round(health)}
      </span>
    </span>
  );
}

/** Identifier chip that opens the record: "K-101 →". */
export function IdChip({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link className="idc" to={to}>
      {children} →
    </Link>
  );
}

export function PageHeader({
  title,
  sub,
  crumbs,
  actions,
}: {
  title: ReactNode;
  sub?: ReactNode;
  crumbs?: { label: string; to?: string }[];
  actions?: ReactNode;
}) {
  return (
    <>
      {crumbs && crumbs.length > 0 && (
        <nav className="crumb" aria-label="Breadcrumb">
          {crumbs.map((c, i) => (
            <span key={i} style={{ display: "inline-flex", gap: 6 }}>
              {i > 0 && <span aria-hidden="true">/</span>}
              {c.to ? <Link to={c.to}>{c.label}</Link> : <span>{c.label}</span>}
            </span>
          ))}
        </nav>
      )}
      <div className="phd">
        <div className="t">
          <h1>{title}</h1>
          {sub && <div className="sec s13">{sub}</div>}
        </div>
        {actions && <div className="acts">{actions}</div>}
      </div>
    </>
  );
}

/** "How to read" button with its explanation. */
export function HowTo({
  title,
  children,
  label = "How to read",
}: {
  title: string;
  children: ReactNode;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <span style={{ position: "relative" }}>
      <button className="qbtn" type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        <Icon d={ICONS.help} size={16} />
        {label}
      </button>
      {open && (
        <div className="tt" role="dialog" aria-label={title} style={{ right: "auto", left: 0 }}>
          <b>{title}</b>
          <span>{children}</span>
        </div>
      )}
    </span>
  );
}

export function Panel({
  title,
  actions,
  children,
  className,
  id,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`pnl${className ? ` ${className}` : ""}`} aria-labelledby={id}>
      {(title || actions) && (
        <div className="pnlh">
          <span className="pt" id={id}>
            {title}
          </span>
          {actions && <div className="acts">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export interface KpiItem {
  label: string;
  value: ReactNode;
  tone?: ToneName;
  icon: string;
  to?: string;
  onClick?: () => void;
  pressed?: boolean;
  sub?: ReactNode;
}

export function Kpis({ items, cols, label }: { items: KpiItem[]; cols?: 3 | 4; label: string }) {
  return (
    <section className={`kpis${cols ? ` k${cols}` : ""}`} aria-label={label}>
      {items.map((k) => {
        const body = (
          <>
            <span className="kh">
              <span className="kl">{k.label}</span>
              <span className="ki">
                <Icon d={k.icon} />
              </span>
            </span>
            <span className="kv">{k.value}</span>
            {k.sub && <span className="ks">{k.sub}</span>}
          </>
        );
        const cls = `kpi${k.tone ? ` k-${k.tone}` : ""}`;
        if (k.to)
          return (
            <Link key={k.label} className={cls} to={k.to}>
              {body}
            </Link>
          );
        if (k.onClick)
          return (
            <button
              key={k.label}
              type="button"
              className={cls}
              aria-pressed={k.pressed}
              onClick={k.onClick}
              style={k.pressed ? { background: "var(--traverse-surface-selected)" } : undefined}
            >
              {body}
            </button>
          );
        return (
          <div key={k.label} className={cls}>
            {body}
          </div>
        );
      })}
    </section>
  );
}

/** Segmented control. */
export function Seg<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: readonly { value: T; label: string }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={o.value === value ? "on" : ""}
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  tabs,
  onChange,
  label,
}: {
  value: T;
  tabs: readonly { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          role="tab"
          aria-selected={t.value === value}
          className={`tab${t.value === value ? " on" : ""}`}
          onClick={() => onChange(t.value)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="empty">
      <span>{children}</span>
    </div>
  );
}

export function KeyValues({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kvs">
      {rows.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export interface StepItem {
  label: string;
  state: "done" | "on" | "todo";
  onClick?: () => void;
}

export function Steps({ steps, label }: { steps: StepItem[]; label: string }) {
  return (
    <nav className="steps" aria-label={label} style={{ ["--n" as string]: String(steps.length) }}>
      {steps.map((s, i) => (
        <button
          key={s.label}
          type="button"
          className={`stp${s.state === "on" ? " on" : s.state === "done" ? " done" : ""}`}
          aria-current={s.state === "on" ? "step" : undefined}
          disabled={!s.onClick}
          onClick={s.onClick}
        >
          <span className="n">{s.state === "done" ? "✓" : i + 1}</span>
          <span>{s.label}</span>
        </button>
      ))}
    </nav>
  );
}

/** Modal dialog with the design's coloured title bar. */
export function Dialog({
  open,
  onOpenChange,
  title,
  children,
  footer,
  wide,
  description,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  description?: string;
}) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="scrim">
          <RadixDialog.Content
            className={`dlg${wide ? " wide" : ""}`}
            aria-describedby={description ? undefined : undefined}
            style={{ fontFamily: "var(--app-font)", fontSize: 14, lineHeight: 1.5 }}
          >
            <div className="dlgh">
              <RadixDialog.Title asChild>
                <h2>{title}</h2>
              </RadixDialog.Title>
              <RadixDialog.Close className="iconbtn" aria-label="Close">
                <Icon d={ICONS.close} size={20} />
              </RadixDialog.Close>
            </div>
            {description && (
              <RadixDialog.Description className="sr">{description}</RadixDialog.Description>
            )}
            <div className="dlgb">{children}</div>
            {footer && <div className="dlgf">{footer}</div>}
          </RadixDialog.Content>
        </RadixDialog.Overlay>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

/** Problems from the API, shown in place. */
export function Problems({ messages }: { messages: string[] }) {
  if (!messages.length) return null;
  return (
    <div
      className="notice"
      role="alert"
      style={{ borderLeftColor: "var(--traverse-status-danger-fg)" }}
    >
      {messages.map((m, i) => (
        <div key={i}>{m}</div>
      ))}
    </div>
  );
}

export function Loading({ what }: { what?: string }) {
  return <p className="sec s13">Loading{what ? ` ${what}` : ""}…</p>;
}
