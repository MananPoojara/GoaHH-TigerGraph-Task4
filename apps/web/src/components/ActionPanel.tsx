import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowRight, Check, Gavel, Lock, Play, ShieldX, X } from 'lucide-react';
import { api, describeError } from '../api/client';
import type { ActionsPayload, ActionView } from '../api/types';
import { ActionStateBadge, RouteBadge } from './Indicators';

const DEMO_ANALYST = 'demo.analyst';

/**
 * Initial and final recommendations, with the approval controls.
 *
 * The UI mirrors the policy boundary rather than enforcing it: the buttons
 * hide what is not permitted, and the API refuses it regardless.
 */
export default function ActionPanel({
  caseId,
  actions,
}: {
  caseId: string;
  actions: ActionsPayload;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [rationale, setRationale] = useState('');
  const [deciding, setDeciding] = useState<string | null>(null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['actions', caseId] });
    queryClient.invalidateQueries({ queryKey: ['queue'] });
  };

  const approve = useMutation({
    mutationFn: ({ action, decision }: { action: string; decision: 'approved' | 'rejected' }) =>
      api.approve(
        caseId,
        action,
        decision,
        DEMO_ANALYST,
        rationale.trim() || 'Reviewed the evidence shown in the workbench.',
      ),
    onSuccess: () => {
      refresh();
      setDeciding(null);
      setRationale('');
      setError(null);
    },
    onError: (err) => setError(describeError(err)),
  });

  const execute = useMutation({
    mutationFn: (action: string) => api.execute(caseId, action),
    onSuccess: () => {
      refresh();
      setError(null);
    },
    onError: (err) => setError(describeError(err)),
  });

  const changed = actions.what_changed && actions.what_changed !== 'nothing';

  return (
    <div className="stack">
      {error && (
        <div className="notice error">
          <ShieldX size={14} />
          {error}
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <Gavel size={14} />
          Next best action
          <span className="count">
            {actions.triggered_rules.length > 0
              ? `rules ${actions.triggered_rules.join(', ')}`
              : 'no rule triggered'}
          </span>
        </div>

        <div className="card-body">
          <div className="faint small" style={{ marginBottom: 6 }}>
            INITIAL — before any requested evidence
          </div>
        </div>
        <div className="card-body tight">
          {actions.initial.length === 0 ? (
            <div className="empty">No initial recommendation.</div>
          ) : (
            actions.initial.map((item) => (
              <ActionRow key={`initial-${item.action}`} item={item} readOnly />
            ))
          )}
        </div>

        {changed && (
          <div className="card-body" style={{ borderTop: '1px solid var(--border)' }}>
            <div className="notice">
              <ArrowRight size={14} />
              <span>{actions.what_changed}</span>
            </div>
          </div>
        )}

        <div className="card-body" style={{ borderTop: '1px solid var(--border)' }}>
          <div className="faint small" style={{ marginBottom: 6 }}>
            FINAL — after the assumed response
          </div>
        </div>
        <div className="card-body tight">
          {actions.final.map((item) => (
            <ActionRow
              key={`final-${item.action}`}
              item={item}
              executed={actions.executed.includes(item.action)}
              deciding={deciding === item.action}
              rationale={rationale}
              onRationale={setRationale}
              onStartDecision={() => {
                setDeciding(item.action);
                setError(null);
              }}
              onCancel={() => setDeciding(null)}
              onApprove={() => approve.mutate({ action: item.action, decision: 'approved' })}
              onReject={() => approve.mutate({ action: item.action, decision: 'rejected' })}
              onExecute={() => execute.mutate(item.action)}
              busy={approve.isPending || execute.isPending}
            />
          ))}
        </div>

        {actions.barred_actions.length > 0 && (
          <div className="card-body" style={{ borderTop: '1px solid var(--border)' }}>
            <div className="notice">
              <Lock size={14} />
              <span>
                Barred by policy: {actions.barred_actions.join(', ')}. Recording what the policy
                prevented matters as much as what it permitted.
              </span>
            </div>
          </div>
        )}
      </div>

      {actions.approvals.length > 0 && (
        <div className="card">
          <div className="card-head">
            <Check size={14} />
            Approval record
            <span className="count">{actions.approvals.length} decision(s)</span>
          </div>
          <div className="card-body tight">
            {actions.approvals.map((record, index) => (
              <div key={index} className="action-row">
                <div>
                  <div className="action-name">
                    {record.action}{' '}
                    <span
                      className={`badge ${
                        record.decision === 'approved' ? 'badge-legitimate' : 'badge-fraud'
                      }`}
                    >
                      {record.decision}
                    </span>
                  </div>
                  <div className="action-reason">
                    {record.decided_by} · {record.decided_at.replace('T', ' ')} ·{' '}
                    {record.rationale}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ActionRow({
  item,
  readOnly = false,
  executed = false,
  deciding = false,
  rationale = '',
  busy = false,
  onRationale,
  onStartDecision,
  onCancel,
  onApprove,
  onReject,
  onExecute,
}: {
  item: ActionView;
  readOnly?: boolean;
  executed?: boolean;
  deciding?: boolean;
  rationale?: string;
  busy?: boolean;
  onRationale?: (value: string) => void;
  onStartDecision?: () => void;
  onCancel?: () => void;
  onApprove?: () => void;
  onReject?: () => void;
  onExecute?: () => void;
}) {
  const needsApproval = item.requires_approval;
  const canExecute =
    !readOnly && !executed && (!needsApproval || item.state === 'approved');

  return (
    <div className="action-row">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="action-name">{item.action}</span>
          <RouteBadge route={item.route} />
          {!readOnly && <ActionStateBadge state={item.state} />}
        </div>
        <div className="action-reason">{item.reason}</div>

        {deciding && (
          <div style={{ marginTop: 8 }}>
            <input
              value={rationale}
              onChange={(event) => onRationale?.(event.target.value)}
              placeholder="Rationale for the record (required by the audit trail)"
              style={{
                width: '100%',
                padding: '6px 9px',
                borderRadius: 5,
                border: '1px solid var(--border-strong)',
                background: 'var(--bg-inset)',
                color: 'var(--text)',
                fontFamily: 'inherit',
                fontSize: 13,
              }}
            />
            <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
              <button className="approve small" disabled={busy} onClick={onApprove}>
                <Check size={12} /> Approve
              </button>
              <button className="reject small" disabled={busy} onClick={onReject}>
                <X size={12} /> Reject
              </button>
              <button className="small" disabled={busy} onClick={onCancel}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {!readOnly && !deciding && (
        <div className="action-controls">
          {needsApproval && item.state === 'pending_approval' && (
            <button className="small" onClick={onStartDecision}>
              <Gavel size={12} /> Decide
            </button>
          )}
          {canExecute && (
            <button className="small" disabled={busy} onClick={onExecute}>
              <Play size={12} /> Execute
            </button>
          )}
        </div>
      )}
    </div>
  );
}
