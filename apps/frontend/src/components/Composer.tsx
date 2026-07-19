import { useState } from "react";

interface Props {
  streaming: boolean;
  onSend: (text: string) => void;
  onCancel: () => void;
}

export function Composer({ streaming, onSend, onCancel }: Props) {
  const [text, setText] = useState("");

  const submit = () => {
    if (!text.trim() || streaming) return;
    onSend(text.trim());
    setText("");
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="px-4 pb-4 pt-2">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-2xl border border-zinc-200 bg-white p-2 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKeyDown}
            rows={1}
            placeholder="Message Chat Bot…"
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
