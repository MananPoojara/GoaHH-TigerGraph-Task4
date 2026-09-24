import { Link, Route, Routes } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ShieldAlert, Database, Cpu, FlaskConical } from 'lucide-react';
import { api } from './api/client';
import CaseQueue from './pages/CaseQueue';
import CaseDetail from './pages/CaseDetail';

/** Backend status, so it is never ambiguous which graph is answering. */
function BackendStatus() {
  const { data } = useQuery({ queryKey: ['health'], queryFn: api.health, staleTime: 15_000 });
  if (!data) return null;

  const live = data.graph_live;
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'center', fontSize: 12 }}>
      <span className="badge badge-neutral" title="Graph backend answering queries">
        <Database size={11} />
        {live ? 'TigerGraph' : `${data.graph_backend} backend`}
      </span>
      <span className="badge badge-neutral" title="LLM provider for synthesis and explanation">
        <Cpu size={11} />
        {data.llm_available ? 'LLM on' : 'deterministic'}
      </span>
      {data.simulate_external_actions && (
        <span className="badge badge-uncertain" title="No real financial action is taken">
          <FlaskConical size={11} />
          simulated actions
        </span>
      )}
      <span className="faint">policy v{data.policy_version}</span>
    </div>
  );
}

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          <ShieldAlert size={19} />
          FraudLens
          <span className="brand-sub">Analyst Workbench</span>
        </Link>
        <div className="topbar-spacer" />
        <BackendStatus />
      </header>
      <main className="content">
        <Routes>
          <Route path="/" element={<CaseQueue />} />
          <Route path="/cases/:caseId" element={<CaseDetail />} />
        </Routes>
      </main>
    </div>
  );
}
