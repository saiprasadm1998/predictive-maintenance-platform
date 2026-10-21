import type { Shape, Tone } from "./status";

/** The shape half of a status (PDS §3.2), drawn in the tone's colour token. */
export function StatusShape({
  shape,
  tone,
  size = 12,
}: {
  shape: Shape;
  tone: Tone;
  size?: number;
}) {
  const color = `var(--status-${tone})`;
  // --watch is too light on white for a graphic (2.4:1): outline it in --watch-text.
  const edge = tone === "watch" ? { stroke: "var(--watch-text)", strokeWidth: 0.9 } : {};
  let mark;
  switch (shape) {
    case "triangle":
      mark = <path d="M6 0.8 11.4 11H0.6Z" fill={color} {...edge} />;
      break;
    case "diamond":
      mark = <path d="M6 1 11 6 6 11 1 6Z" fill={color} {...edge} />;
      break;
    case "circle":
      mark = <circle cx="6" cy="6" r="4.6" fill="none" stroke={color} strokeWidth="1.8" />;
      break;
    case "dashed-square":
      mark = (
        <rect
          x="1.2"
          y="1.2"
          width="9.6"
          height="9.6"
          rx="1"
          fill="none"
          stroke={color}
          strokeWidth="1.6"
          strokeDasharray="2.4 1.6"
        />
      );
      break;
    case "square":
      mark = <rect x="1" y="1" width="10" height="10" rx="1" fill={color} {...edge} />;
      break;
    case "hollow-square":
      mark = (
        <rect
          x="1.2"
          y="1.2"
          width="9.6"
          height="9.6"
          rx="1"
          fill="none"
          stroke={color}
          strokeWidth="1.8"
        />
      );
      break;
  }
  return (
    <svg
      className="status-shape"
      data-shape={shape}
      width={size}
      height={size}
      viewBox="0 0 12 12"
      aria-hidden="true"
      focusable="false"
    >
      {mark}
    </svg>
  );
}
