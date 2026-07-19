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

  // Reset local state when the selected conversation changes — but never while
  // a stream is actively populating `messages` ourselves. Sending a message on
  // a brand-new chat navigates to the newly-created conversation id (changing
  // the `conversationId` prop) and the "GET conversation" query can resolve
  // mid-stream (changing `initialMessages`) — either would otherwise wipe the
  // in-flight optimistic messages and silently drop every subsequent token.
  useEffect(() => {
    if (streaming) return;
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
      pendingRef.current = "";
      networkDoneRef.current = false;

      const userMsg: Message = { id: localId(), role: "user", content: text, created_at: new Date().toISOString() };
      const assistantMsg: Message = { id: localId(), role: "assistant", content: "", created_at: new Date().toISOString() };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setStreaming(true);
      startRef.current = performance.now();

      cancelRef.current = streamChat(
        { message: text, conversation_id: conversationId, model },
        {
          onStart: (data) => {
            if (!conversationId) onConversationCreated(data.conversation_id);
          },
          onToken: (token) => {
            pendingRef.current += token;
            ensureTypingLoop();
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
    setStreaming(false);
    setLatencyMs(performance.now() - startRef.current);
  }, [stopTypingLoop, appendToLastAssistant]);

  // Abort any in-flight stream and stop the typing timer on unmount.
  useEffect(() => () => {
    cancelRef.current?.();
    stopTypingLoop();
  }, [stopTypingLoop]);

  return { messages, streaming, usage, latencyMs, error, send, cancel } as ChatState & {
    send: (text: string, model: string | null) => void;
    cancel: () => void;
  };
}
