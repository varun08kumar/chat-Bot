import { API_BASE, authHeaders } from "./api";
import type { TokenUsage } from "./types";

export interface StreamHandlers {
  onStart?: (data: { conversation_id: string; request_id: string; model: string; provider: string }) => void;
  onToken?: (token: string) => void;
  onUsage?: (usage: TokenUsage) => void;
  onDone?: (data: { conversation_id: string; usage: TokenUsage }) => void;
  onError?: (message: string) => void;
}

export interface StreamRequest {
  message: string;
  conversation_id?: string | null;
  model?: string | null;
}

/**
 * POST /chat and parse the Server-Sent Events stream.
 *
 * EventSource only supports GET, so we stream the POST response body ourselves
 * and parse the `event:`/`data:` frames. The returned function aborts the
 * in-flight request (wired to the UI "cancel" button).
 */
export function streamChat(req: StreamRequest, handlers: StreamHandlers): () => void {
  const controller = new AbortController();

  (async () => {
    let response: Response;
    try {
      response = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...authHeaders() },
        body: JSON.stringify({ ...req, stream: true }),
        signal: controller.signal,
      });
    } catch (err) {
      if (!controller.signal.aborted) handlers.onError?.(String(err));
      return;
    }

    if (!response.ok || !response.body) {
      handlers.onError?.(`Request failed: ${response.status}`);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        // Normalize CRLF to LF — sse-starlette (the backend) terminates
        // events with "\r\n\r\n", which contains no bare "\n\n", so frame
        // boundaries would never be found without this.
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

        // SSE frames are separated by a blank line.
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          dispatchFrame(frame, handlers);
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) handlers.onError?.(String(err));
    }
  })();

  return () => controller.abort();
}

function dispatchFrame(frame: string, handlers: StreamHandlers) {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;

  let payload: any = {};
  try {
    payload = JSON.parse(dataLines.join("\n"));
  } catch {
    return;
  }

  switch (event) {
    case "start":
      handlers.onStart?.(payload);
      break;
    case "token":
      handlers.onToken?.(payload.content ?? "");
      break;
    case "usage":
      handlers.onUsage?.(payload);
      break;
    case "done":
      handlers.onDone?.(payload);
      break;
    case "error":
      handlers.onError?.(payload.message ?? "stream error");
      break;
  }
}
