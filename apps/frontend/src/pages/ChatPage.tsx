import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Sidebar } from "@/components/Sidebar";
import { MessageList } from "@/components/MessageList";
import { Composer } from "@/components/Composer";
import { UsageBar } from "@/components/UsageBar";
import { useConversation } from "@/hooks/useConversations";
import { useChat } from "@/hooks/useChat";
import type { Message } from "@/lib/types";

const DEFAULT_MODEL = "gpt-4o-mini";
const EMPTY: Message[] = [];

export function ChatPage() {
  const { conversationId = null } = useParams();
  const navigate = useNavigate();
  const [model, setModel] = useState<string>(() => localStorage.getItem("llmobs.model") ?? DEFAULT_MODEL);

  const { data: detail } = useConversation(conversationId);
  const initialMessages = useMemo(() => detail?.messages ?? EMPTY, [detail]);

  const { messages, streaming, usage, latencyMs, error, toolStatus, send, sendImage, sendImageSearch, cancel } = useChat(
    conversationId,
    initialMessages,
    (id) => navigate(`/c/${id}`),
  );

  useEffect(() => {
    localStorage.setItem("llmobs.model", model);
  }, [model]);

  const selectConversation = (id: string | null) => navigate(id ? `/c/${id}` : "/");

  return (
    <div className="flex h-full">
      <Sidebar activeId={conversationId} onSelect={selectConversation} model={model} onModelChange={setModel} />
      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-3 dark:border-zinc-800">
          <div className="flex min-w-0 items-center gap-2">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" aria-hidden />
            <h1 className="truncate text-sm font-medium text-zinc-800 dark:text-zinc-100">
              {detail?.title ?? "New conversation"}
            </h1>
          </div>
        </div>

        <MessageList
          messages={messages}
          streaming={streaming}
          toolStatus={toolStatus}
          onSuggestion={(text) => send(text, model)}
          onEdit={(messageId, text) => send(text, model, messageId)}
          onContinue={() =>
            send(
              "Continue exactly where you left off. Do not repeat anything you already said, and do not restart the answer.",
              model,
            )
          }
        />

        {error && (
          <div className="mx-auto w-full max-w-3xl px-4 py-1 text-sm text-red-500">⚠ {error}</div>
        )}

        <UsageBar usage={usage} latencyMs={latencyMs} model={model} />
        <Composer
          streaming={streaming}
          onSend={(t) => send(t, model)}
          onSendImage={sendImage}
          onSendImageSearch={sendImageSearch}
          onCancel={cancel}
        />
      </section>
    </div>
  );
}
