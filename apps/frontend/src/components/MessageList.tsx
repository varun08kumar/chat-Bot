import { useEffect, useRef, useState } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import type { Message } from "@/lib/types";
import type { Components } from "react-markdown";

// Search-mode images are hotlinked straight from whatever site SearXNG found
// them on — some are slow, and a rare few never resolve at all. Show a
// loading placeholder while it's in flight, and if it hasn't loaded within
// IMAGE_LOAD_TIMEOUT_MS (browsers don't otherwise expose a "just give up"
// signal), fall back to a plain link rather than leaving a broken-image icon
// on screen indefinitely. Generated (data: URI) images load instantly from
// the page itself, so this just resolves immediately for those.
const IMAGE_LOAD_TIMEOUT_MS = 15_000;

function MarkdownImage({ src, alt }: { src?: string; alt?: string }) {
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");
  const imgRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    setStatus("loading");
    // A big data: URI can finish decoding faster than React commits the DOM
    // node and attaches its onLoad listener — the native `load` event fires
    // in that gap and is simply missed, leaving onLoad never called even
    // though the image genuinely loaded (confirmed via img.complete). This
    // check catches that race on mount, in addition to the normal
    // onLoad/onError handlers below for the slower real-network case.
    if (imgRef.current?.complete && imgRef.current.naturalWidth > 0) {
      setStatus("loaded");
      return;
    }
    const timer = setTimeout(() => setStatus((s) => (s === "loading" ? "error" : s)), IMAGE_LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [src]);

  if (status === "error" || !src) {
    return (
      <a href={src} target="_blank" rel="noreferrer" className="text-brand-600 underline dark:text-brand-500">
        {alt || src || "image"}
      </a>
    );
  }

  return (
    <span className="mb-2 block last:mb-0">
      {status === "loading" && (
        <span className="flex h-40 w-full max-w-xs animate-pulse items-center justify-center rounded-lg bg-zinc-100 text-xs text-zinc-400 dark:bg-zinc-800">
          Loading image…
        </span>
      )}
      <img
        ref={imgRef}
        src={src}
        alt={alt}
        onLoad={() => setStatus("loaded")}
        onError={() => setStatus("error")}
        className={`max-w-full rounded-lg ${status === "loading" ? "hidden" : ""}`}
      />
    </span>
  );
}

// Assistant messages come back as markdown (LLM providers write **bold**,
// numbered lists, code fences, etc.) — render it instead of dumping the raw
// syntax as text. Minimal per-tag styling since we don't pull in the
// Tailwind typography plugin for just this.
const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-brand-600 underline dark:text-brand-500">
      {children}
    </a>
  ),
  code: ({ children, className }) =>
    className ? (
      // Fenced code block (has a language className) — handled by <pre> below.
      <code className={className}>{children}</code>
    ) : (
      <code className="rounded bg-zinc-100 px-1 py-0.5 font-mono text-[0.85em] dark:bg-zinc-800">{children}</code>
    ),
  pre: ({ children }) => (
    <pre className="scroll-thin mb-2 overflow-x-auto rounded-lg bg-zinc-100 p-3 font-mono text-[0.85em] last:mb-0 dark:bg-zinc-900">
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-2 border-zinc-300 pl-3 text-zinc-600 last:mb-0 dark:border-zinc-600 dark:text-zinc-400">
      {children}
    </blockquote>
  ),
  img: ({ src, alt }) => <MarkdownImage src={src} alt={alt} />,
  h1: ({ children }) => <h3 className="mb-1.5 mt-2 text-base font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-1.5 mt-2 text-base font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h3 className="mb-1.5 mt-2 text-sm font-semibold first:mt-0">{children}</h3>,
};

// react-markdown's default urlTransform strips any URL scheme outside its
// safe-list (http/https/irc(s)/mailto) — data: URIs get silently blanked
// out, which is exactly how the backend hands back a generated image. Allow
// data:image/* specifically rather than disabling the sanitizer outright,
// so other message content (which can contain arbitrary LLM-authored links)
// keeps the default protection.
const allowDataImages = (url: string) => (url.startsWith("data:image/") ? url : defaultUrlTransform(url));

const SUGGESTIONS = [
  "Explain a complex topic simply",
  "Draft a professional email",
  "Compare two frameworks",
  "Summarize an argument",
];

interface ToolStatus {
  name: string;
  query: string;
}

interface Props {
  messages: Message[];
  streaming: boolean;
  toolStatus: ToolStatus | null;
  onSuggestion: (text: string) => void;
  onEdit: (messageId: string, text: string) => void;
  onContinue: () => void;
}

export function MessageList({ messages, streaming, toolStatus, onSuggestion, onEdit, onContinue }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming, toolStatus]);

  const visible = messages.filter((m) => m.role !== "system");

  return (
    <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-4 py-6">
      <div className="mx-auto flex max-w-3xl flex-col gap-4">
        {visible.length === 0 && (
          <div className="mt-24 grid grid-cols-2 gap-3">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => onSuggestion(s)}
                className="rounded-xl border border-zinc-200 bg-white px-4 py-3 text-left text-sm text-zinc-700 shadow-sm transition hover:border-zinc-300 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {visible.map((m, i) => {
          const isLast = i === visible.length - 1;
          return (
            <Bubble
              key={m.id}
              message={m}
              streaming={streaming && isLast && m.role === "assistant"}
              toolStatus={streaming && isLast && m.role === "assistant" ? toolStatus : null}
              isLast={isLast}
              busy={streaming}
              onEdit={onEdit}
              onContinue={onContinue}
            />
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

interface BubbleProps {
  message: Message;
  streaming: boolean;
  toolStatus: ToolStatus | null;
  isLast: boolean;
  busy: boolean;
  onEdit: (messageId: string, text: string) => void;
  onContinue: () => void;
}

function Bubble({ message, streaming, toolStatus, isLast, busy, onEdit, onContinue }: BubbleProps) {
  const isUser = message.role === "user";
  const empty = message.content.length === 0;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const [copied, setCopied] = useState(false);

  // Edits are only meaningful once the backend has assigned a real message
  // id (see useChat.ts's onStart reconciliation) — a still-optimistic
  // "local-..." id has nothing on the server yet to truncate from.
  const editable = isUser && !busy && !message.id.startsWith("local-");
  const canContinue = !isUser && isLast && !busy && !empty;

  const startEdit = () => {
    setDraft(message.content);
    setEditing(true);
  };

  const saveEdit = () => {
    const text = draft.trim();
    setEditing(false);
    if (text && text !== message.content) onEdit(message.id, text);
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can be unavailable (permissions, insecure context) —
      // silently no-op rather than surface an error for a non-critical action.
    }
  };

  if (editing) {
    return (
      <div className="flex justify-end">
        <div className="w-full max-w-[85%] rounded-2xl border border-zinc-300 bg-white p-2 shadow-sm dark:border-zinc-700 dark:bg-zinc-900">
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                saveEdit();
              } else if (e.key === "Escape") {
                setEditing(false);
              }
            }}
            rows={Math.min(8, Math.max(2, draft.split("\n").length))}
            className="scroll-thin max-h-60 w-full resize-y bg-transparent px-2 py-1.5 text-sm text-zinc-900 outline-none dark:text-zinc-50"
          />
          <div className="flex justify-end gap-2 px-1 pb-1">
            <button
              onClick={() => setEditing(false)}
              className="rounded-lg px-2.5 py-1 text-xs text-zinc-500 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              onClick={saveEdit}
              disabled={!draft.trim()}
              className="rounded-lg bg-zinc-900 px-2.5 py-1 text-xs text-white disabled:opacity-30 dark:bg-zinc-100 dark:text-zinc-900"
            >
              Save & submit
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`group flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? "whitespace-pre-wrap bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50"
            : "text-zinc-800 dark:text-zinc-100"
        }`}
      >
        {streaming && toolStatus ? (
          <span className="flex items-center gap-2 text-zinc-500 dark:text-zinc-400">
            <span className="typing-dots">
              <span />
              <span />
              <span />
            </span>
            Searching the web for "{toolStatus.query}"…
          </span>
        ) : streaming && empty ? (
          // Nothing has arrived yet — show a "thinking" indicator. Once
          // tokens start landing, the growing text itself (plus the
          // typewriter reveal) is the "still generating" signal; a glued-on
          // trailing cursor can't sit inline with markdown's block-level
          // output (headings, list items, code fences) without landing on
          // its own line, so we don't try.
          <span className="typing-dots">
            <span />
            <span />
            <span />
          </span>
        ) : isUser ? (
          message.content
        ) : (
          <ReactMarkdown components={markdownComponents} urlTransform={allowDataImages}>{message.content}</ReactMarkdown>
        )}
      </div>

      {!streaming && !empty && (editable || !isUser) && (
        <div className="mt-1 flex items-center gap-1 px-1 opacity-0 transition-opacity group-hover:opacity-100">
          {editable && (
            <button
              onClick={startEdit}
              aria-label="Edit message"
              title="Edit message"
              className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            >
              <EditIcon />
            </button>
          )}
          {!isUser && (
            <button
              onClick={copy}
              aria-label="Copy response"
              title={copied ? "Copied" : "Copy response"}
              className="rounded-md p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            >
              {copied ? <CheckIcon /> : <CopyIcon />}
            </button>
          )}
          {canContinue && (
            <button
              onClick={onContinue}
              aria-label="Continue generating"
              title="Continue this response"
              className="flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            >
              <ContinueIcon />
              Continue
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function EditIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

function CopyIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function ContinueIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 3v18l15-9L5 3Z" />
    </svg>
  );
}
