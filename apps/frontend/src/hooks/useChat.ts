import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { streamChat } from "@/lib/chatStream";
import type { Message, TokenUsage } from "@/lib/types";

export interface ChatState {
  messages: Message[];
  streaming: boolean;
  usage: TokenUsage | null;
  latencyMs: number | null;
  error: string | null;
  toolStatus: { name: string; query: string } | null;
}

let localCounter = 0;
const localId = () => `local-${Date.now()}-${localCounter++}`;

// Typewriter pacing for the reveal buffer below: tokens can arrive from the
// backend in bursts (a fast provider may hand back a whole paragraph in one
// SSE frame), but we still want a steady per-character typing feel. Revealing
// a fraction of whatever is buffered — rather than a fixed count — means
// small bursts trickle out character-by-character while large backlogs
// self-accelerate instead of leaving the UI "typing" for tens of seconds
// after the network side already finished.
const TYPING_TICK_MS = 20;
const TYPING_REVEAL_FRACTION = 0.12;

export function useChat(
  conversationId: string | null,
  initialMessages: Message[],
  onConversationCreated: (id: string) => void,
) {
  const qc = useQueryClient();
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [streaming, setStreaming] = useState(false);
  const [usage, setUsage] = useState<TokenUsage | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toolStatus, setToolStatus] = useState<{ name: string; query: string } | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);
  const startRef = useRef<number>(0);

  // Reveal buffer: tokens land here as they arrive over SSE and a timer
  // drains them onto the screen at typing pace. Being plain refs owned by
  // this hook instance (never module-level), the buffer is implicitly scoped
  // to one conversation in one browser tab — nothing here is shared across
  // users or even across tabs of the same user.
  const pendingRef = useRef("");
  const networkDoneRef = useRef(false);
  const typingTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Mirrors `toolStatus` for the onToken closure below — avoids a stale
  // read of state from inside a callback created once per `send()` call.
  const toolStatusRef = useRef<{ name: string; query: string } | null>(null);

  const appendToLastAssistant = useCallback((text: string) => {
    if (!text) return;
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === "assistant") next[next.length - 1] = { ...last, content: last.content + text };
      return next;
    });
  }, []);

  const stopTypingLoop = useCallback(() => {
    if (typingTimerRef.current) {
      clearInterval(typingTimerRef.current);
      typingTimerRef.current = null;
    }
  }, []);

  // Only flips `streaming` off once both the network stream has finished AND
  // every buffered character has been typed out — so the composer stays
  // disabled for the full "typing" duration, not just the network duration.
  const maybeFinish = useCallback(() => {
    if (pendingRef.current.length === 0 && networkDoneRef.current) {
      stopTypingLoop();
      setStreaming(false);
      setLatencyMs(performance.now() - startRef.current);
    }
  }, [stopTypingLoop]);

  const ensureTypingLoop = useCallback(() => {
    if (typingTimerRef.current) return;
    typingTimerRef.current = setInterval(() => {
      if (pendingRef.current.length === 0) {
        maybeFinish();
        return;
      }
      const revealCount = Math.max(1, Math.ceil(pendingRef.current.length * TYPING_REVEAL_FRACTION));
      const chunk = pendingRef.current.slice(0, revealCount);
      pendingRef.current = pendingRef.current.slice(revealCount);
      appendToLastAssistant(chunk);
      if (pendingRef.current.length === 0) maybeFinish();
    }, TYPING_TICK_MS);
  }, [appendToLastAssistant, maybeFinish]);

  // The conversation id our local state currently takes precedence over a
  // background refetch for. Set whenever we start (or just finished) sending
  // into a conversation; cleared the moment the user navigates to a
  // different one. Guards two races, both against `initialMessages`:
  //  1. Mid-stream: sending on a brand-new chat navigates to the newly
  //     created id, and the "GET conversation" query can resolve while
  //     tokens are still arriving.
  //  2. Just-finished: that same query can also resolve *after* streaming
  //     already flipped to false (a slow request, or the stream ending very
  //     quickly on an error) — for a brand-new conversation this snapshot is
  //     often incomplete (e.g. the assistant turn isn't persisted at all if
  //     the call failed before any tokens arrived), and without this guard
  //     it would silently wipe the error message and the empty assistant
  //     bubble the user just saw, leaving the screen looking like nothing
  //     happened at all.
  // Either way, once this ref matches `conversationId`, `initialMessages`
  // updates for that same id are ignored until the user navigates away.
  const trustLocalForRef = useRef<string | null>(null);

  useEffect(() => {
    if (streaming) return;
    if (conversationId !== null && conversationId === trustLocalForRef.current) return;
    trustLocalForRef.current = null;
    setMessages(initialMessages);
    setUsage(null);
    setLatencyMs(null);
    setError(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, initialMessages]);

  const send = useCallback(
    (text: string, model: string | null) => {
      if (streaming || !text.trim()) return;
      setError(null);
      setUsage(null);
      setLatencyMs(null);
      setToolStatus(null);
      toolStatusRef.current = null;
      pendingRef.current = "";
      networkDoneRef.current = false;
      if (conversationId) trustLocalForRef.current = conversationId;

      const userMsg: Message = { id: localId(), role: "user", content: text, created_at: new Date().toISOString() };
      const assistantMsg: Message = { id: localId(), role: "assistant", content: "", created_at: new Date().toISOString() };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setStreaming(true);
      startRef.current = performance.now();

      cancelRef.current = streamChat(
        { message: text, conversation_id: conversationId, model },
        {
          onStart: (data) => {
            if (!conversationId) {
              trustLocalForRef.current = data.conversation_id;
              onConversationCreated(data.conversation_id);
            }
          },
          onToken: (token) => {
            if (toolStatusRef.current) setToolStatus(null);
            pendingRef.current += token;
            ensureTypingLoop();
          },
          onToolCall: (data) => {
            toolStatusRef.current = data;
            setToolStatus(data);
          },
          onUsage: (u) => setUsage(u),
          onDone: () => {
            networkDoneRef.current = true;
            cancelRef.current = null;
            qc.invalidateQueries({ queryKey: ["conversations"] });
            maybeFinish();
          },
          onError: (message) => {
            stopTypingLoop();
            pendingRef.current = "";
            networkDoneRef.current = true;
            toolStatusRef.current = null;
            setToolStatus(null);
            setError(message);
            setStreaming(false);
            cancelRef.current = null;
          },
        },
      );
    },
    [conversationId, streaming, onConversationCreated, qc, ensureTypingLoop, maybeFinish, stopTypingLoop],
  );

  const cancel = useCallback(() => {
    cancelRef.current?.();
    cancelRef.current = null;
    stopTypingLoop();
    // Flush whatever was already buffered but not yet "typed" — it did
    // arrive, cancelling just means no more will.
    appendToLastAssistant(pendingRef.current);
    pendingRef.current = "";
    networkDoneRef.current = true;
    toolStatusRef.current = null;
    setToolStatus(null);
    setStreaming(false);
    setLatencyMs(performance.now() - startRef.current);
  }, [stopTypingLoop, appendToLastAssistant]);

  // Abort any in-flight stream and stop the typing timer on unmount.
  useEffect(() => () => {
    cancelRef.current?.();
    stopTypingLoop();
  }, [stopTypingLoop]);

  return { messages, streaming, usage, latencyMs, error, toolStatus, send, cancel } as ChatState & {
    send: (text: string, model: string | null) => void;
    cancel: () => void;
  };
}
