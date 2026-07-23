import { useState } from "react";

type Mode = "chat" | "generate" | "search";

interface Props {
  streaming: boolean;
  onSend: (text: string) => void;
  onSendImage: (prompt: string) => void;
  onSendImageSearch: (query: string) => void;
  onCancel: () => void;
}

const PLACEHOLDERS: Record<Mode, string> = {
  chat: "Message Chat Bot…",
  generate: "Describe the image to generate…",
  search: "What photo are you looking for?",
};

export function Composer({ streaming, onSend, onSendImage, onSendImageSearch, onCancel }: Props) {
  const [text, setText] = useState("");
  const [mode, setMode] = useState<Mode>("chat");

  const toggle = (target: Mode) => setMode((m) => (m === target ? "chat" : target));

  const submit = () => {
    if (!text.trim() || streaming) return;
    if (mode === "generate") onSendImage(text.trim());
    else if (mode === "search") onSendImageSearch(text.trim());
    else onSend(text.trim());
    setText("");
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const modeButtonClass = (active: boolean) =>
    `grid h-9 w-9 shrink-0 place-items-center rounded-xl border transition ${
      active
        ? "border-brand-600 bg-brand-50 text-brand-600 dark:border-brand-500 dark:bg-zinc-800 dark:text-brand-500"
        : "border-transparent text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
    }`;

  return (
    <div className="px-4 pb-4 pt-2">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-2xl border border-zinc-200 bg-white p-2 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <button
            onClick={() => toggle("generate")}
            aria-label="Generate an image instead of a chat reply"
            title={mode === "generate" ? "Image generation on — click to switch back to chat" : "Generate an image"}
            aria-pressed={mode === "generate"}
            className={modeButtonClass(mode === "generate")}
          >
            <GenerateIcon />
          </button>
          <button
            onClick={() => toggle("search")}
            aria-label="Find a real photo from the web instead of a chat reply"
            title={mode === "search" ? "Photo search on — click to switch back to chat" : "Find a real photo"}
            aria-pressed={mode === "search"}
            className={modeButtonClass(mode === "search")}
          >
            <SearchIcon />
          </button>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder={PLACEHOLDERS[mode]}
            className="scroll-thin max-h-40 min-h-[40px] flex-1 resize-y bg-transparent px-2 py-2 text-sm text-zinc-800 outline-none placeholder:text-zinc-400 dark:text-zinc-100"
          />
          {streaming ? (
            <button
              onClick={onCancel}
              aria-label="Stop generating"
              title="Stop generating"
              className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-zinc-900 text-white transition hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
            >
              <StopIcon />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!text.trim()}
              aria-label="Send message"
              title="Send message"
              className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-zinc-900 text-white transition hover:bg-zinc-700 disabled:opacity-30 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
            >
              <SendIcon />
            </button>
          )}
        </div>
        <p className="mt-2 text-center text-[0.7rem] text-zinc-400 dark:text-zinc-600">
          Chat Bot can make mistakes. Verify important information.
        </p>
      </div>
    </div>
  );
}

function GenerateIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="M21 15l-5-5L5 21" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="10" cy="10" r="3.5" />
      <path d="M20 20l-4-4" />
    </svg>
  );
}

function SendIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
      <rect x="3" y="3" width="18" height="18" rx="2" />
    </svg>
  );
}
