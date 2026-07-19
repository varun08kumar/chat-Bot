import { useEffect, useMemo, useState } from "react";
import { useConversations, useDeleteConversation } from "@/hooks/useConversations";
import { ModelSelector } from "@/components/ModelSelector";
import type { Conversation } from "@/lib/types";

interface Props {
  activeId: string | null;
  onSelect: (id: string | null) => void;
  model: string;
  onModelChange: (model: string) => void;
}

export function Sidebar({ activeId, onSelect, model, onModelChange }: Props) {
  const [search, setSearch] = useState("");
  const { data: conversations = [], isLoading } = useConversations(search || undefined);
  const del = useDeleteConversation();

  // ⌘K / Ctrl+K starts a new conversation from anywhere.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onSelect(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onSelect]);

  const groups = useMemo(() => groupByDate(conversations), [conversations]);

  const handleDelete = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    del.mutate(id, {
      onSuccess: () => {
        if (activeId === id) onSelect(null);
      },
    });
  };

  return (
    <aside className="flex h-full w-64 flex-col border-r border-zinc-200 bg-zinc-50/60 dark:border-zinc-800 dark:bg-zinc-900/40">
      <div className="flex items-center gap-1.5 px-4 py-4">
        <span className="text-brand-600 dark:text-zinc-100" aria-hidden>
          ◆
        </span>
        <span className="text-xs font-bold tracking-widest text-zinc-900 dark:text-zinc-100">CHAT BOT</span>
      </div>

      <div className="px-3">
        <button
          onClick={() => onSelect(null)}
          className="flex w-full items-center justify-between rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-700 shadow-sm transition hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
        >
          <span>New conversation</span>
          <kbd className="rounded border border-zinc-200 px-1.5 py-0.5 font-mono text-[0.65rem] text-zinc-400 dark:border-zinc-700 dark:text-zinc-500">
            ⌘K
          </kbd>
        </button>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search conversations…"
          className="mt-2 w-full rounded-lg border border-transparent bg-transparent px-3 py-1.5 text-sm text-zinc-600 outline-none placeholder:text-zinc-400 focus:border-zinc-200 focus:bg-white dark:text-zinc-300 dark:focus:border-zinc-700 dark:focus:bg-zinc-900"
        />
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 pb-3 pt-2">
        {isLoading && <p className="px-1 py-2 text-sm text-zinc-400">Loading…</p>}
        {!isLoading && conversations.length === 0 && <p className="px-1 py-2 text-sm text-zinc-400">No conversations yet.</p>}
        {groups.map(([label, items]) => (
          <div key={label} className="mb-3">
            <p className="mb-1 px-1 text-[0.68rem] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
              {label}
            </p>
            <ul className="space-y-0.5">
              {items.map((c) => (
                <li key={c.id}>
                  <button
                    onClick={() => onSelect(c.id)}
                    className={`group flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition ${
                      activeId === c.id
                        ? "bg-zinc-200/70 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-50"
                        : "text-zinc-600 hover:bg-zinc-200/40 dark:text-zinc-400 dark:hover:bg-zinc-800/60"
                    }`}
                  >
                    <span className="truncate">{c.title}</span>
                    <span
                      role="button"
                      aria-label="Delete conversation"
                      onClick={(e) => handleDelete(c.id, e)}
                      className="ml-2 hidden shrink-0 text-zinc-400 hover:text-red-500 group-hover:inline"
                    >
                      ✕
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="border-t border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <p className="mb-1 text-[0.65rem] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-500">Model</p>
        <ModelSelector value={model} onChange={onModelChange} variant="footer" />
      </div>
    </aside>
  );
}

function groupByDate(conversations: Conversation[]): Array<[string, Conversation[]]> {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const startOfYesterday = startOfToday - 86_400_000;

  const buckets = new Map<string, Conversation[]>();
  const order = ["Today", "Yesterday", "Previous 7 days", "Older"];
  for (const c of conversations) {
    const t = new Date(c.updated_at).getTime();
    const label = t >= startOfToday ? "Today" : t >= startOfYesterday ? "Yesterday" : t >= startOfToday - 7 * 86_400_000 ? "Previous 7 days" : "Older";
    if (!buckets.has(label)) buckets.set(label, []);
    buckets.get(label)!.push(c);
  }
  return order.filter((label) => buckets.has(label)).map((label) => [label, buckets.get(label)!]);
}
