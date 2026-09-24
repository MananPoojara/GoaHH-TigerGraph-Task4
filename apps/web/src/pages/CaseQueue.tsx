import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, Inbox, Loader2, Play, TriangleAlert } from 'lucide-react';
import { api, describeError } from '../api/client';
import type { QueueRow } from '../api/types';
import { VerdictBadge, Probability } from '../components/Indicators';

/** The analyst queue: every benchmark trigger and where its case stands. */
export default function CaseQueue() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: rows, isLoading } = useQuery({ queryKey: ['queue'], queryFn: api.queue });

  const investigate = useMutation({
    mutationFn: (caseId: string) => api.startInvestigation(caseId),
    onMutate: (caseId) => {
      setRunning(caseId);
      setError(null);
    },
    onSuccess: (_data, caseId) => {
      queryClient.invalidateQueries({ queryKey: ['queue'] });
      navigate(`/cases/${caseId}`);
    },
    onError: (err) => setError(describeError(err)),
    onSettled: () => setRunning(null),
  });

  if (isLoading) {
    return (
      <div className="card">
        <div className="empty">
          <Loader2 size={16} className="spin" /> Loading the queue…
        </div>
      </div>
    );
  }

  const queue = rows ?? [];
  const investigated = queue.filter((row) => row.investigated);
  const pendingApprovals = queue.reduce((total, row) => total + row.pending_approvals, 0);

  return (
    <div className="stack">
      {error && (
        <div className="notice error">
          <AlertCircle size={14} />
          {error}
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <Inbox size={14} />
          Alert queue
          <span className="count">
            {investigated.length} of {queue.length} investigated
            {pendingApprovals > 0 && ` · ${pendingApprovals} awaiting approval`}
          </span>
        </div>

        {queue.length === 0 ? (
          <div className="empty">
            No cases loaded. Place <span className="mono">case_pack.csv</span> in{' '}
            <span className="mono">data/raw/</span> and restart the API.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Trigger</th>
                <th>Card</th>
                <th>Model score</th>
                <th>Verdict</th>
                <th>Our probability</th>
                <th>Exposure</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {queue.map((row) => (
                <QueueRowView
                  key={row.case_id}
                  row={row}
                  busy={running === row.case_id}
                  anyRunning={running !== null}
                  onOpen={() => row.investigated && navigate(`/cases/${row.case_id}`)}
                  onInvestigate={() => investigate.mutate(row.case_id)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="notice">
        <TriangleAlert size={14} />
        <span>
          A model risk score is a reason to look, not a verdict. Roughly half of these alerts
          resolve as legitimate, and the agent&rsquo;s own probability is assessed independently
          of the score shown here.
        </span>
      </div>
    </div>
  );
}

function QueueRowView({
  row,
  busy,
  anyRunning,
  onOpen,
  onInvestigate,
}: {
  row: QueueRow;
  busy: boolean;
  anyRunning: boolean;
  onOpen: () => void;
  onInvestigate: () => void;
}) {
  return (
    <tr className={row.investigated ? 'clickable' : undefined} onClick={onOpen}>
      <td>
        <div className="mono" style={{ fontWeight: 650 }}>
          {row.case_id}
        </div>
        <div className="faint small">{row.opened_at.replace('T', ' ').slice(0, 16)}</div>
      </td>
      <td style={{ maxWidth: 340 }}>
        <span className="pill">{row.trigger_type}</span>
        <div className="muted small" style={{ marginTop: 4 }}>
          {row.trigger_text}
        </div>
      </td>
      <td className="mono">
        {row.card_id}
        <div className="faint small">{row.customer_id}</div>
      </td>
      <td>
        {row.risk_score === null ? (
          <span className="faint">—</span>
        ) : (
          <span className="mono">{row.risk_score.toFixed(2)}</span>
        )}
      </td>
      <td>
        {row.verdict ? <VerdictBadge verdict={row.verdict} /> : <span className="faint">—</span>}
      </td>
      <td style={{ minWidth: 110 }}>
        {row.fraud_probability === null ? (
          <span className="faint">—</span>
        ) : (
          <Probability value={row.fraud_probability} />
        )}
      </td>
      <td className="mono">
        {row.exposure_usd ? `$${row.exposure_usd.toLocaleString()}` : <span className="faint">—</span>}
      </td>
      <td style={{ textAlign: 'right' }}>
        <button
          className={row.investigated ? 'small' : 'primary small'}
          disabled={anyRunning}
          onClick={(event) => {
            event.stopPropagation();
            onInvestigate();
          }}
        >
          {busy ? <Loader2 size={12} className="spin" /> : <Play size={12} />}
          {busy ? 'Investigating' : row.investigated ? 'Re-run' : 'Investigate'}
        </button>
      </td>
    </tr>
  );
}
