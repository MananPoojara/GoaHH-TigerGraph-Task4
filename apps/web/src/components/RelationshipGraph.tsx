import { useMemo } from 'react';
import type { CaseGraph, GraphNode } from '../api/types';

/** Visual treatment per entity kind. Colour carries meaning, not decoration. */
const KIND_STYLE: Record<GraphNode['kind'], { fill: string; stroke: string; label: string }> = {
  customer: { fill: '#1f6feb33', stroke: '#4493f8', label: 'Customer' },
  card: { fill: '#8957e533', stroke: '#a371f7', label: 'Card' },
  transaction: { fill: '#f8514922', stroke: '#f85149', label: 'Transaction' },
  device: { fill: '#d2992222', stroke: '#d29922', label: 'Device profile' },
  connected_card: { fill: '#db6d2822', stroke: '#db6d28', label: 'Connected card' },
  prior_case: { fill: '#3fb95022', stroke: '#3fb950', label: 'Prior case' },
};

// Entities are laid out in fixed columns by kind. A deterministic layout means
// the same case always draws the same picture, which matters when an analyst
// is comparing two investigations or watching a demo twice.
const COLUMN_ORDER: GraphNode['kind'][] = [
  'customer',
  'card',
  'transaction',
  'device',
  'connected_card',
  'prior_case',
];

const NODE_WIDTH = 150;
const NODE_HEIGHT = 30;
const COLUMN_GAP = 210;
const ROW_GAP = 42;
const PADDING = 26;

interface Placed extends GraphNode {
  x: number;
  y: number;
}

export default function RelationshipGraph({ graph }: { graph: CaseGraph }) {
  const { placed, width, height } = useMemo(() => layout(graph), [graph]);

  if (placed.length === 0) {
    return <div className="empty">No relationships to display for this case.</div>;
  }

  const byId = new Map(placed.map((node) => [node.id, node]));
  const kindsPresent = COLUMN_ORDER.filter((kind) => placed.some((node) => node.kind === kind));

  return (
    <div>
      <div style={{ overflowX: 'auto' }}>
        <svg
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="Case relationship graph"
          style={{ display: 'block', minWidth: '100%' }}
        >
          <defs>
            <marker
              id="arrow"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#4a5462" />
            </marker>
          </defs>

          {graph.edges.map((edge, index) => {
            const from = byId.get(edge.source);
            const to = byId.get(edge.target);
            if (!from || !to) return null;

            const x1 = from.x + NODE_WIDTH;
            const y1 = from.y + NODE_HEIGHT / 2;
            const x2 = to.x;
            const y2 = to.y + NODE_HEIGHT / 2;
            const midX = (x1 + x2) / 2;

            return (
              <g key={`${edge.source}-${edge.target}-${index}`}>
                <path
                  d={`M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`}
                  fill="none"
                  stroke="#363e4a"
                  strokeWidth={1.2}
                  markerEnd="url(#arrow)"
                />
                <text
                  x={midX}
                  y={(y1 + y2) / 2 - 4}
                  fill="#6b7480"
                  fontSize={9}
                  textAnchor="middle"
                  fontFamily="ui-monospace, monospace"
                >
                  {edge.label}
                </text>
              </g>
            );
          })}

          {placed.map((node) => {
            const style = KIND_STYLE[node.kind];
            return (
              <g key={node.id}>
                <rect
                  x={node.x}
                  y={node.y}
                  width={NODE_WIDTH}
                  height={NODE_HEIGHT}
                  rx={5}
                  fill={style.fill}
                  stroke={style.stroke}
                  strokeWidth={node.affected ? 1.8 : 1}
                />
                <text
                  x={node.x + NODE_WIDTH / 2}
                  y={node.y + NODE_HEIGHT / 2 + 3.5}
                  fill="#e6edf3"
                  fontSize={10.5}
                  textAnchor="middle"
                  fontFamily="ui-monospace, monospace"
                >
                  {truncate(node.label, 21)}
                </text>
                <title>{node.label}</title>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="chips" style={{ marginTop: 12 }}>
        {kindsPresent.map((kind) => (
          <span key={kind} className="badge badge-neutral">
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 2,
                background: KIND_STYLE[kind].fill,
                border: `1px solid ${KIND_STYLE[kind].stroke}`,
                display: 'inline-block',
              }}
            />
            {KIND_STYLE[kind].label}
          </span>
        ))}
      </div>
    </div>
  );
}

function layout(graph: CaseGraph): { placed: Placed[]; width: number; height: number } {
  const columns = new Map<GraphNode['kind'], GraphNode[]>();
  for (const node of graph.nodes) {
    const bucket = columns.get(node.kind) ?? [];
    bucket.push(node);
    columns.set(node.kind, bucket);
  }

  const activeColumns = COLUMN_ORDER.filter((kind) => (columns.get(kind)?.length ?? 0) > 0);
  const tallest = Math.max(1, ...activeColumns.map((kind) => columns.get(kind)!.length));

  const placed: Placed[] = [];
  activeColumns.forEach((kind, columnIndex) => {
    const nodes = columns.get(kind)!;
    // Centre each column vertically against the tallest one.
    const offset = ((tallest - nodes.length) * ROW_GAP) / 2;
    nodes.forEach((node, rowIndex) => {
      placed.push({
        ...node,
        x: PADDING + columnIndex * COLUMN_GAP,
        y: PADDING + offset + rowIndex * ROW_GAP,
      });
    });
  });

  return {
    placed,
    width: PADDING * 2 + Math.max(1, activeColumns.length) * COLUMN_GAP,
    height: PADDING * 2 + tallest * ROW_GAP,
  };
}

function truncate(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max - 1)}…`;
}
