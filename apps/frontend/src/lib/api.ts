import axios from "axios";
import type {
  Conversation,
  ConversationDetail,
  Dashboard,
  ProviderInfo,
  User,
} from "./types";

// Base path mirrors the ingress: /api -> chat-service, /api/metrics -> metrics.
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

// A per-session correlation label only — not a security boundary. Real
// identity (`user_id`) comes from the verified access-token cookie the
// backend sets at login; this just distinguishes browser tabs of the same
// logged-in user for observability.
export function sessionId(): string {
  const key = "llmobs.session_id";
  let id = sessionStorage.getItem(key);
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem(key, id);
  }
  return id;
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

const MUTATING_METHODS = new Set(["post", "put", "patch", "delete"]);

const client = axios.create({
  baseURL: API_BASE,
  headers: { "Content-Type": "application/json" },
  // Send the httpOnly session cookies with every request; without this,
  // the browser omits cookies on cross-origin-looking requests even though
  // frontend and backend share an origin behind nginx in this setup.
  withCredentials: true,
});
client.interceptors.request.use((config) => {
  config.headers.set?.("X-Session-Id", sessionId());
  // Double-submit CSRF: the backend rejects any mutating request whose
  // X-CSRF-Token header doesn't match the (non-httpOnly) csrf_token cookie
  // — see apps/chat-service/app/dependencies.py:verify_csrf.
  if (config.method && MUTATING_METHODS.has(config.method)) {
    const csrf = readCookie("csrf_token");
    if (csrf) config.headers.set?.("X-CSRF-Token", csrf);
  }
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
  async cancelChat(requestId: string): Promise<void> {
    await client.post(`/chat/${requestId}/cancel`);
  },
  async getProviders(): Promise<ProviderInfo[]> {
    const { data } = await client.get<ProviderInfo[]>("/providers");
    return data;
  },
  async getDashboard(window: string): Promise<Dashboard> {
    const { data } = await client.get<Dashboard>("/metrics/dashboard", { params: { window } });
    return data;
  },

  async register(email: string, password: string): Promise<User> {
    const { data } = await client.post<User>("/auth/register", { email, password });
    return data;
  },
  async login(email: string, password: string): Promise<User> {
    const { data } = await client.post<User>("/auth/login", { email, password });
    return data;
  },
  async logout(): Promise<void> {
    await client.post("/auth/logout");
  },
  async refresh(): Promise<User> {
    const { data } = await client.post<User>("/auth/refresh");
    return data;
  },
  async me(): Promise<User> {
    const { data } = await client.get<User>("/auth/me");
    return data;
  },
};

export { API_BASE, readCookie };
