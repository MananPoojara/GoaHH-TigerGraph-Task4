import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowLeft,
  BookOpen,
  Clock,
  Database,
  FileText,
  FlaskConical,
  GitBranch,
  HelpCircle,
  Loader2,
  MessageSquareQuote,
  Scale,
  Search,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { api } from '../api/client';
import type { CaseDetail as CaseDetailType, EvidenceItem, TimelineEvent } from '../api/types';
import ActionPanel from '../components/ActionPanel';
import RelationshipGraph from '../components/RelationshipGraph';
import { DirectionBadge, Probability, StatusBadge, VerdictBadge } from '../components/Indicators';

export default function CaseDetail() {
  const { caseId = '' } = useParams();

  const detail = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => api.caseDetail(caseId),
    enabled: Boolean(caseId),
  });
  const evidence = useQuery({
    queryKey: ['evidence', caseId],
    queryFn: () => api.evidence(caseId),
    enabled: Boolean(caseId),
  });
  const timeline = useQuery({
    queryKey: ['timeline', caseId],
    queryFn: () => api.timeline(caseId),
    enabled: Boolean(caseId),
  });
  const actions = useQuery({
    queryKey: ['actions', caseId],
    queryFn: () => api.actions(caseId),
    enabled: Boolean(caseId),
  });
  const graph = useQuery({
    queryKey: ['graph', caseId],
    queryFn: () => api.graph(caseId),
    enabled: Boolean(caseId),
  });

  if (detail.isLoading) {
    return (
      <div className="card">
        <div className="empty">
          <Loader2 size={16} className="spin" /> Loading case…
        </div>
      </div>
    );
  }

  if (detail.isError || !detail.data) {
    return (
      <div className="stack">
        <Link to="/">
          <ArrowLeft size={13} /> Back to queue
        </Link>
        <div className="notice error">
          This case has not been investigated yet. Start it from the queue.
        </div>
      </div>
    );
  }

  const data = detail.data;

  return (
    <div className="stack">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <Link to="/">
          <ArrowLeft size={13} /> Queue
        </Link>
        <h1 style={{ margin: 0, fontSize: 19, letterSpacing: '-0.02em' }}>{data.case_id}</h1>
        <StatusBadge status={data.status} />
        {data.assessment && <VerdictBadge verdict={data.assessment.verdict} />}
      </div>

      <TriggerCard data={data} />

      <div className="grid grid-main">
        <div className="stack">
          <AssessmentCard data={data} />
          <EvidenceCard items={evidence.data ?? []} />
          {graph.data && (
            <div className="card">
              <div className="card-head">
                <GitBranch size={14} />
                Graph relationships
                <span className="count">{graph.data.nodes.length} entities</span>
              </div>
              <div className="card-body">
                <RelationshipGraph graph={graph.data} />
              </div>
            </div>
          )}
          <SarCard data={data} />
        </div>

        <div className="stack">
          {actions.data && <ActionPanel caseId={caseId} actions={actions.data} />}
          <EvidenceRequestCard data={data} />
          <PriorCasesCard data={data} />
          <TimelineCard events={timeline.data ?? []} />
        </div>
      </div>
    </div>
  );
}

function TriggerCard({ data }: { data: CaseDetailType }) {
  return (
    <div className="card">
      <div className="card-head">
        <Search size={14} />
        What triggered this investigation
      </div>
      <div className="card-body">
        <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          <span className="pill">{data.trigger.type}</span>
          <span className="pill">txn {data.trigger.flagged_txn_id}</span>
          <span className="pill">{data.trigger.card_id}</span>
          <span className="pill">{data.trigger.customer_id}</span>
          <span className="pill">opened {data.trigger.opened_at.replace('T', ' ').slice(0, 16)}</span>
        </div>
        <div className="prose">{data.trigger.text}</div>
      </div>
      <div className="stat-row">
        <div className="stat">
          <div className="label">Model score</div>
          <div className="value">
            {data.trigger.risk_score === null ? '—' : data.trigger.risk_score.toFixed(2)}
          </div>
        </div>
        <div className="stat">
          <div className="label">Our probability</div>
          <div className="value">{data.assessment?.fraud_probability.toFixed(2) ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="label">Exposure</div>
          <div className="value">${data.scope.exposure_usd.toLocaleString()}</div>
        </div>
        <div className="stat">
          <div className="label">Affected txns</div>
          <div className="value">{data.scope.affected_txn_ids.length}</div>
        </div>
        <div className="stat">
          <div className="label">Connected cards</div>
          <div className="value">{data.scope.connected_card_ids.length}</div>
        </div>
        <div className="stat">
          <div className="label">Graph calls</div>
          <div className="value">{data.telemetry.tool_calls}</div>
        </div>
        <div className="stat">
          <div className="label">Latency</div>
          <div className="value">{data.telemetry.latency_s.toFixed(1)}s</div>
        </div>
      </div>
    </div>
  );
}

function AssessmentCard({ data }: { data: CaseDetailType }) {
  const assessment = data.assessment;
  if (!assessment) return null;

  const hypotheses = data.hypotheses
    .filter((item) => item.score > 0)
    .slice(0, 6)
    .map((item) => ({ name: item.pattern.replace(/_/g, ' '), score: Number(item.score.toFixed(2)) }));

  return (
    <div className="card">
      <div className="card-head">
        <Scale size={14} />
        Assessment
        <span className="count">
          {assessment.independent_signal_count} independent evidence famil
          {assessment.independent_signal_count === 1 ? 'y' : 'ies'}
        </span>
      </div>
      <div className="card-body">
        <div style={{ maxWidth: 260, marginBottom: 14 }}>
          <Probability value={assessment.fraud_probability} />
        </div>

        <dl className="kv" style={{ marginBottom: 14 }}>
          <dt>Pattern</dt>
          <dd className="mono">{assessment.pattern}</dd>
          <dt>Confidence</dt>
          <dd>{assessment.confidence.toFixed(2)}</dd>
          <dt>Uncertainty</dt>
          <dd>
            {assessment.uncertainty === 'none' ? (
              <span className="faint">resolved</span>
            ) : (
              <span className="badge badge-uncertain">
                {assessment.uncertainty.replace(/_/g, ' ')}
              </span>
            )}
          </dd>
          {assessment.pattern_description && (
            <>
              <dt>Description</dt>
              <dd>{assessment.pattern_description}</dd>
            </>
          )}
        </dl>

        {hypotheses.length > 0 && (
          <>
            <div className="faint small" style={{ marginBottom: 6 }}>
              COMPETING HYPOTHESES — alternatives stay on the table until ruled out
            </div>
            <div style={{ height: 150 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={hypotheses} layout="vertical" margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="2 4" stroke="#262d38" horizontal={false} />
                  <XAxis
                    type="number"
                    domain={[0, 1]}
                    tick={{ fill: '#6b7480', fontSize: 11 }}
                    stroke="#363e4a"
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={150}
                    tick={{ fill: '#8b949e', fontSize: 11 }}
                    stroke="#363e4a"
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#161b22',
                      border: '1px solid #363e4a',
                      borderRadius: 6,
                      fontSize: 12,
                    }}
                    cursor={{ fill: '#ffffff08' }}
                  />
                  <Bar dataKey="score" fill="#4493f8" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        )}

        <div className="notice" style={{ marginTop: 12 }}>
          <HelpCircle size={14} />
          <span>{assessment.rationale}</span>
        </div>

        <div style={{ marginTop: 14 }}>
          <div className="faint small" style={{ marginBottom: 4 }}>
            SUMMARY
          </div>
          <div className="prose">{data.summary}</div>
        </div>

        <div style={{ marginTop: 14 }}>
          <div className="faint small" style={{ marginBottom: 4 }}>
            WHY THE INVESTIGATION STOPPED
          </div>
          <div className="prose muted">{data.stop_reason}</div>
        </div>

        <div className="notice" style={{ marginTop: 14 }}>
          <Database size={14} />
          <span>
            {data.written_to_graph ? (
              <>
                Case written to the graph as <span className="mono">{data.graph_case_id}</span> and
                verified by read-back. It is now retrievable as memory by later investigations.
              </>
            ) : (
              <>Case was not persisted to the graph; it will not be available as memory.</>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}

function EvidenceCard({ items }: { items: EvidenceItem[] }) {
  const supporting = items.filter((item) => item.direction === 'supports_fraud').length;
  const against = items.filter((item) => item.direction === 'supports_legitimate').length;

  return (
    <div className="card">
      <div className="card-head">
        <BookOpen size={14} />
        Evidence ledger
        <span className="count">
          {items.length} items · {supporting} for fraud · {against} against
        </span>
      </div>
      <div className="card-body tight scroll">
        {items.length === 0 ? (
          <div className="empty">No evidence recorded.</div>
        ) : (
          items.map((item) => (
            <div key={item.seq} className={`evidence-item ${item.direction}`}>
              <div className="evidence-claim">{item.claim}</div>
              <div className="evidence-meta">
                <DirectionBadge direction={item.direction} />
                <span className="pill">{item.source}</span>
                <span className="evidence-ref">{item.ref}</span>
                {item.entity_ids.slice(0, 5).map((id) => (
                  <span key={id} className="pill">
                    {id}
                  </span>
                ))}
                {item.entity_ids.length > 5 && (
                  <span className="faint">+{item.entity_ids.length - 5} more</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function EvidenceRequestCard({ data }: { data: CaseDetailType }) {
  return (
    <div className="card">
      <div className="card-head">
        <MessageSquareQuote size={14} />
        Additional evidence
        <span className="count">{data.evidence_requests.length} request(s)</span>
      </div>
      <div className="card-body tight">
        {data.evidence_requests.length === 0 ? (
          <div className="empty">
            No evidence was requested. No available response would have changed the recommendation.
          </div>
        ) : (
          data.evidence_requests.map((request) => (
            <div key={request.request_no} className="action-row">
              <div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span className="action-name">{request.type}</span>
                  <span className="badge badge-uncertain">
                    <FlaskConical size={10} /> simulated
                  </span>
                  <span className="faint small">after step {request.asked_after_step}</span>
                </div>
                {request.reason && <div className="action-reason">{request.reason}</div>}
                <div className="prose small" style={{ marginTop: 6 }}>
                  &ldquo;{request.assumed_response}&rdquo;
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function PriorCasesCard({ data }: { data: CaseDetailType }) {
  return (
    <div className="card">
      <div className="card-head">
        <Database size={14} />
        Case memory
        <span className="count">{data.prior_cases.length} prior case(s)</span>
      </div>
      <div className="card-body tight">
        {data.prior_cases.length === 0 ? (
          <div className="empty">No comparable closed cases were retrieved.</div>
        ) : (
          data.prior_cases.map((prior) => (
            <div key={prior.case_id} className="action-row">
              <div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span className="action-name">{prior.case_id}</span>
                  <span
                    className={`badge ${
                      prior.outcome === 'confirmed_fraud' ? 'badge-fraud' : 'badge-legitimate'
                    }`}
                  >
                    {prior.outcome}
                  </span>
                  <span className="pill">{prior.pattern}</span>
                </div>
                <div className="action-reason">
                  Linked by {prior.link_reason} · score {prior.structural_score.toFixed(2)}
                </div>
                {prior.analyst_notes && (
                  <div className="prose small muted" style={{ marginTop: 5 }}>
                    {prior.analyst_notes}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function SarCard({ data }: { data: CaseDetailType }) {
  return (
    <div className="card">
      <div className="card-head">
        <FileText size={14} />
        Suspicious activity report
        <span className="count">
          {data.sar.file ? 'filing recommended' : 'no filing required'}
        </span>
      </div>
      <div className="card-body">
        <div className="notice" style={{ marginBottom: data.sar.file ? 12 : 0 }}>
          <Scale size={14} />
          <span>{data.sar.reason}</span>
        </div>
        {data.sar.file && <div className="prose narrative">{data.sar.narrative}</div>}
      </div>
    </div>
  );
}

function TimelineCard({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="card">
      <div className="card-head">
        <Clock size={14} />
        Investigation timeline
        <span className="count">{events.length} steps</span>
      </div>
      <div className="card-body tight scroll">
        <div className="timeline">
          {events.map((event) => (
            <div key={event.step} className="timeline-item">
              <div className="timeline-step">{event.step}</div>
              <div>
                <div className="timeline-event">{event.event}</div>
                {event.detail && <div className="timeline-detail">{event.detail}</div>}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
