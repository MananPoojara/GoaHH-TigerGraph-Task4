import axios from 'axios';
import type {
  ActionsPayload,
  CaseDetail,
  CaseGraph,
  EvidenceItem,
  Health,
  QueueRow,
  TimelineEvent,
} from './types';

// Requests go through the Vite proxy in development, so the browser never
// needs a base URL or a credential of its own.
const http = axios.create({ baseURL: '/api', timeout: 120_000 });

export const api = {
  health: async (): Promise<Health> => (await http.get('/health')).data,

  queue: async (): Promise<QueueRow[]> => (await http.get('/cases')).data,

  startInvestigation: async (caseId: string): Promise<CaseDetail> =>
    (await http.post('/investigations', { case_id: caseId })).data,

  caseDetail: async (caseId: string): Promise<CaseDetail> =>
    (await http.get(`/cases/${caseId}`)).data,

  evidence: async (caseId: string): Promise<EvidenceItem[]> =>
    (await http.get(`/cases/${caseId}/evidence`)).data,

  timeline: async (caseId: string): Promise<TimelineEvent[]> =>
    (await http.get(`/cases/${caseId}/timeline`)).data,

  actions: async (caseId: string): Promise<ActionsPayload> =>
    (await http.get(`/cases/${caseId}/actions`)).data,

  graph: async (caseId: string): Promise<CaseGraph> =>
    (await http.get(`/cases/${caseId}/graph`)).data,

  answer: async (caseId: string): Promise<unknown> =>
    (await http.get(`/cases/${caseId}/answer`)).data,

  approve: async (
    caseId: string,
    action: string,
    decision: 'approved' | 'rejected',
    analyst: string,
    rationale: string,
  ): Promise<ActionsPayload> =>
    (
      await http.post(`/cases/${caseId}/approve`, {
        action,
        decision,
        analyst,
        rationale,
      })
    ).data,

  execute: async (caseId: string, action: string): Promise<unknown> =>
    (await http.post(`/cases/${caseId}/execute`, { action })).data,
};

/** Turn an axios error into something an analyst can read. */
export function describeError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (error.response) return `${error.response.status} ${error.response.statusText}`;
    return 'The API is unreachable. Is the backend running on port 8000?';
  }
  return error instanceof Error ? error.message : 'Unexpected error';
}
