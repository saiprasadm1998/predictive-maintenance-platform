/**
 * A small trend without axes (PDS §4.8: 7-day DI sparkline on the unit view's cards).
 * Drawn as SVG, so a page of cards stays light; the label says what it shows in words.
 */
export function Sparkline({
  values,
  label,
  width = 160,
  height = 32,
  limit,
}: {
  values: readonly (number | null)[];
  label: string;
  width?: number;
  height?: number;
  /** A reference line (the warning limit), in the same units. */
  limit?: number | null;
}) {
  const finite = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (finite.length < 2) {
    return (
      <span className="sparkline-empty muted" role="img" aria-label={`${label}: no data`}>
        no data
      </span>
    );
  }
  const lo = Math.min(...finite, limit ?? Infinity, 0);
  const hi = Math.max(...finite, limit ?? -Infinity);
  const span = hi - lo || 1;
  const x = (i: number) => (i / (values.length - 1)) * (width - 2) + 1;
  const y = (v: number) => height - 1 - ((v - lo) / span) * (height - 2);
  const segments: string[] = [];
  let current = "";
  values.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) {
      if (current) segments.push(current);
      current = "";
      return;
    }
    current += `${current ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
  });
  if (current) segments.push(current);
  const first = finite[0]!;
  const last = finite[finite.length - 1]!;
  return (
    <svg
      className="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`${label}: from ${first.toFixed(1)} to ${last.toFixed(1)}, highest ${Math.max(...finite).toFixed(1)}`}
    >
      {limit != null && (
        <line
          x1="0"
          x2={width}
          y1={y(limit)}
          y2={y(limit)}
          stroke="var(--watch-text)"
          strokeDasharray="3 2"
          strokeWidth="1"
        />
      )}
      {segments.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="var(--text)" strokeWidth="1.5" />
      ))}
    </svg>
  );
}
