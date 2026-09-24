import type { EvidenceDirection, Route, Verdict } from '../api/types';

/** Verdict, coloured so it reads at a glance. */
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return <span className={`badge badge-${verdict}`}>{verdict}</span>;
}

/** Approval route. The colour ramp matches customer impact: auto → L1 → L2. */
export function RouteBadge({ route }: { route: Route }) {
  const title =
    route === 'auto'
      ? 'The agent may execute this action alone'
      : route === 'L1'
        ? 'Requires team lead approval'
        : 'Requires fraud manager approval';
  return (
    <span className={`route route-${route}`} title={title}>
      {route}
    </span>
  );
}

function probabilityColour(value: number): string {
  if (value >= 0.7) return 'var(--fraud)';
  if (value >= 0.3) return 'var(--uncertain)';
  return 'var(--legit)';
}

/** A probability with a meter, because the band matters more than the digits. */
export function Probability({ value, showLabel = true }: { value: number; showLabel?: boolean }) {
  const colour = probabilityColour(value);
  return (
    <div>
      {showLabel && (
        <div
          className="mono"
          style={{ color: colour, fontWeight: 650, marginBottom: 3, fontSize: 13 }}
        >
          {value.toFixed(2)}
        </div>
      )}
      <div className="meter" title={`Assessed fraud probability ${value.toFixed(2)}`}>
        <span style={{ width: `${Math.round(value * 100)}%`, background: colour }} />
      </div>
    </div>
  );
}

/** Whether an evidence item argues for fraud, against it, or neither. */
export function DirectionBadge({ direction }: { direction: EvidenceDirection }) {
  const map: Record<EvidenceDirection, { label: string; cls: string }> = {
    supports_fraud: { label: 'supports fraud', cls: 'badge-fraud' },
    supports_legitimate: { label: 'supports legitimate', cls: 'badge-legitimate' },
    context: { label: 'context', cls: 'badge-neutral' },
  };
  const entry = map[direction];
  return <span className={`badge ${entry.cls}`}>{entry.label}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const cls =
    status === 'closed_fraud'
      ? 'badge-fraud'
      : status === 'closed_legitimate'
        ? 'badge-legitimate'
        : status === 'escalated'
          ? 'badge-uncertain'
          : 'badge-neutral';
  return <span className={`badge ${cls}`}>{status.replace(/_/g, ' ')}</span>;
}

/** The state of a recommended action in its approval lifecycle. */
export function ActionStateBadge({ state }: { state: string }) {
  const cls =
    state === 'executed'
      ? 'badge-legitimate'
      : state === 'rejected'
        ? 'badge-fraud'
        : state === 'pending_approval'
          ? 'badge-uncertain'
          : 'badge-neutral';
  return <span className={`badge ${cls}`}>{state.replace(/_/g, ' ')}</span>;
}
