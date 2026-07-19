import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { Message } from "@/lib/types";
import type { Components } from "react-markdown";

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
  h1: ({ children }) => <h3 className="mb-1.5 mt-2 text-base font-semibold first:mt-0">{children}</h3>,
  h2: ({ children }) => <h3 className="mb-1.5 mt-2 text-base font-semibold first:mt-0">{children}</h3>,
  h3: ({ children }) => <h3 className="mb-1.5 mt-2 text-sm font-semibold first:mt-0">{children}</h3>,
};

const SUGGESTIONS = [
  "Explain a complex topic simply",
  "Draft a professional email",
  "Compare two frameworks",
  "Summarize an argument",
];

interface Props {
  messages: Message[];
  streaming: boolean;
  onSuggestion: (text: string) => void;
}

export function MessageList({ messages, streaming, onSuggestion }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streaming]);

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
        {visible.map((m, i) => (
          <Bubble
            key={m.id}
            message={m}
            streaming={streaming && i === visible.length - 1 && m.role === "assistant"}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function Bubble({ message, streaming }: { message: Message; streaming: boolean }) {
  const isUser = message.role === "user";
  const empty = message.content.length === 0;
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? "whitespace-pre-wrap bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50"
            : "text-zinc-800 dark:text-zinc-100"
        } ${streaming && empty ? "cursor-blink" : ""}`}
      >
        {isUser ? message.content : <ReactMarkdown components={markdownComponents}>{message.content}</ReactMarkdown>}
        {streaming && !empty && <span className="cursor-blink" />}
      </div>
    </div>
  );
}
