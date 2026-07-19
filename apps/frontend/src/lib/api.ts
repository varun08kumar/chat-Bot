import axios from "axios";
import type {
  Conversation,
  ConversationDetail,
  Dashboard,
  ProviderInfo,
} from "./types";

// Base path mirrors the ingress: /api -> chat-service, /api/metrics -> metrics.
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

// A stable per-browser identity so conversations belong to "this user".
function userId(): string {
  const key = "llmobs.user_id";
  let id = localStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem(key, id);
  }
  return id;
}

export function sessionId(): string {
  const key = "llmobs.session_id";
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
  }
  return id;
}

export function authHeaders(): Record<string, string> {
  return { "X-User-Id": userId(), "X-Session-Id": sessionId() };
}

const client = axios.create({ baseURL: API_BASE, headers: { "Content-Type": "application/json" } });
client.interceptors.request.use((config) => {
  config.headers.set?.("X-User-Id", userId());
  config.headers.set?.("X-Session-Id", sessionId());
  return config;
});

export const api = {
  async listConversations(search?: string): Promise<Conversation[]> {
    const { data } = await client.get<Conversation[]>("/conversations", {
      params: search ? { search } : undefined,
    });
    return data;
  },
  async getConversation(id: string): Promise<ConversationDetail> {
    const { data } = await client.get<ConversationDetail>(`/conversation/${id}`);
    return data;
  },
  async deleteConversation(id: string): Promise<void> {
    await client.delete(`/conversation/${id}`);
  },
  async getProviders(): Promise<ProviderInfo[]> {
    const { data } = await client.get<ProviderInfo[]>("/providers");
    return data;
  },
  async getDashboard(window: string): Promise<Dashboard> {
    const { data } = await client.get<Dashboard>("/metrics/dashboard", { params: { window } });
    return data;
  },
};

export { API_BASE };
