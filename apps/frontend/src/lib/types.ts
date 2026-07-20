export interface User {
  id: string;
  email: string;
  is_admin: boolean;
  created_at: string;
}

export type Role = "system" | "user" | "assistant";

export interface Message {
  id: string;
  role: Role;
  content: string;
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface ModelInfo {
  id: string;
  label: string;
  context_window: number;
}

export interface ProviderInfo {
  id: string;
  label: string;
  enabled: boolean;
  models: ModelInfo[];
}

// ---- Dashboard shapes ----
export interface Summary {
  total_requests: number;
  total_errors: number;
  conversations: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  p99_latency_ms: number;
  total_tokens: number;
  error_rate: number;
  requests_per_second: number;
}

export interface LatencyPoint {
  bucket: string;
  avg_ms: number;
  p95_ms: number;
  p99_ms: number;
}

export interface ThroughputPoint {
  bucket: string;
  requests: number;
  rps: number;
}

export interface ErrorPoint {
  bucket: string;
  total: number;
  errors: number;
  error_rate: number;
}

export interface ProviderRow {
  provider: string;
  requests: number;
  errors: number;
  avg_latency_ms: number;
  total_tokens: number;
  error_rate: number;
}

export interface ModelRow {
  model: string;
  provider: string;
  requests: number;
  total_tokens: number;
  avg_latency_ms: number;
  error_rate: number;
}

export interface Dashboard {
  window: string;
  available_windows: string[];
  summary: Summary;
  latency: { summary: Record<string, number>; series: LatencyPoint[] };
  throughput: ThroughputPoint[];
  errors: ErrorPoint[];
  providers: ProviderRow[];
  models: ModelRow[];
  tokens: { totals: TokenUsage; by_provider: Array<{ provider: string } & TokenUsage> };
}
