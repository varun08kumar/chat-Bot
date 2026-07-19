import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ErrorPoint, LatencyPoint, ThroughputPoint } from "@/lib/types";

const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

const axisProps = { stroke: "#94a3b8", fontSize: 11 } as const;

export function LatencyChart({ data }: { data: LatencyPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" />
        <XAxis dataKey="bucket" tickFormatter={fmtTime} {...axisProps} />
        <YAxis {...axisProps} unit="ms" />
        <Tooltip labelFormatter={fmtTime} contentStyle={{ fontSize: 12 }} />
        <Line type="monotone" dataKey="avg_ms" name="avg" stroke="#6366f1" dot={false} strokeWidth={2} />
        <Line type="monotone" dataKey="p95_ms" name="p95" stroke="#f59e0b" dot={false} strokeWidth={2} />
        <Line type="monotone" dataKey="p99_ms" name="p99" stroke="#ef4444" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function ThroughputChart({ data }: { data: ThroughputPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" />
        <XAxis dataKey="bucket" tickFormatter={fmtTime} {...axisProps} />
        <YAxis {...axisProps} />
        <Tooltip labelFormatter={fmtTime} contentStyle={{ fontSize: 12 }} />
        <Area type="monotone" dataKey="requests" name="requests" stroke="#22c55e" fill="#22c55e33" strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function ErrorChart({ data }: { data: ErrorPoint[] }) {
  const pct = data.map((d) => ({ ...d, error_pct: +(d.error_rate * 100).toFixed(2) }));
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={pct} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f033" />
        <XAxis dataKey="bucket" tickFormatter={fmtTime} {...axisProps} />
        <YAxis {...axisProps} unit="%" />
        <Tooltip labelFormatter={fmtTime} contentStyle={{ fontSize: 12 }} />
        <Area type="monotone" dataKey="error_pct" name="error %" stroke="#ef4444" fill="#ef444433" strokeWidth={2} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
