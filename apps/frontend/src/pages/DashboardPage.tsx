import { useState } from "react";
import { useDashboard } from "@/hooks/useDashboard";
import { ErrorChart, LatencyChart, ThroughputChart } from "@/components/Charts";
import type { ModelRow, ProviderRow } from "@/lib/types";

const WINDOWS = ["15m", "1h", "6h", "24h", "7d", "30d"];

export function DashboardPage() {
  const [window, setWindow] = useState("24h");
  const { data, isLoading, isError } = useDashboard(window);

  return (
    <div className="scroll-thin h-full overflow-y-auto p-4">
      <div className="mx-auto max-w-6xl space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold">LLM Overview</h1>
          <div className="flex gap-1">
            {WINDOWS.map((w) => (
              <button
                key={w}
                onClick={() => setWindow(w)}
                className={`rounded-md px-2.5 py-1 text-sm ${
                  window === w
                    ? "bg-brand-600 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:hover:bg-slate-700"
                }`}
              >
                {w}
              </button>
            ))}
          </div>
        </div>

        {isError && <p className="text-red-500">Failed to load metrics. Is the metrics service running?</p>}
        {isLoading && !data && <p className="text-slate-400">Loading metrics…</p>}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Card label="Requests" value={fmt(data.summary.total_requests)} sub={`${data.summary.requests_per_second}/s`} />
              <Card label="Error rate" value={`${(data.summary.error_rate * 100).toFixed(2)}%`} sub={`${fmt(data.summary.total_errors)} errors`} accent={data.summary.error_rate > 0.05 ? "red" : undefined} />
              <Card label="P95 latency" value={`${data.summary.p95_latency_ms.toFixed(0)} ms`} sub={`p99 ${data.summary.p99_latency_ms.toFixed(0)} ms`} />
              <Card label="Tokens" value={fmt(data.summary.total_tokens)} sub={`${fmt(data.summary.conversations)} conversations`} />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Latency (avg / p95 / p99)">
                <LatencyChart data={data.latency.series} />
              </Panel>
              <Panel title="Throughput (requests)">
                <ThroughputChart data={data.throughput} />
              </Panel>
              <Panel title="Error rate">
                <ErrorChart data={data.errors} />
              </Panel>
              <Panel title="Providers">
                <ProviderTable rows={data.providers} />
              </Panel>
            </div>

            <Panel title="Models">
              <ModelTable rows={data.models} />
            </Panel>
          </>
        )}
      </div>
    </div>
  );
}

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n ?? 0);
}

function Card({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: "red" }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className={`mt-1 text-2xl font-semibold ${accent === "red" ? "text-red-500" : ""}`}>{value}</p>
      {sub && <p className="text-xs text-slate-400">{sub}</p>}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">{title}</h2>
      {children}
    </div>
  );
}

function ProviderTable({ rows }: { rows: ProviderRow[] }) {
  if (rows.length === 0) return <Empty />;
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs uppercase text-slate-400">
        <tr>
          <th className="py-1">Provider</th>
          <th>Requests</th>
          <th>Err %</th>
          <th>Avg ms</th>
          <th>Tokens</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.provider} className="border-t border-slate-100 dark:border-slate-800">
            <td className="py-1 font-medium">{r.provider}</td>
            <td>{fmt(r.requests)}</td>
            <td>{(r.error_rate * 100).toFixed(1)}%</td>
            <td>{r.avg_latency_ms.toFixed(0)}</td>
            <td>{fmt(r.total_tokens)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ModelTable({ rows }: { rows: ModelRow[] }) {
  if (rows.length === 0) return <Empty />;
  return (
    <table className="w-full text-left text-sm">
      <thead className="text-xs uppercase text-slate-400">
        <tr>
          <th className="py-1">Model</th>
          <th>Provider</th>
          <th>Requests</th>
          <th>Err %</th>
          <th>Avg ms</th>
          <th>Tokens</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.provider}/${r.model}`} className="border-t border-slate-100 dark:border-slate-800">
            <td className="py-1 font-mono text-xs">{r.model}</td>
            <td>{r.provider}</td>
            <td>{fmt(r.requests)}</td>
            <td>{(r.error_rate * 100).toFixed(1)}%</td>
            <td>{r.avg_latency_ms.toFixed(0)}</td>
            <td>{fmt(r.total_tokens)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Empty() {
  return <p className="py-6 text-center text-sm text-slate-400">No data in this window yet.</p>;
}
