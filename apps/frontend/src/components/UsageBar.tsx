import type { TokenUsage } from "@/lib/types";

interface Props {
  usage: TokenUsage | null;
  latencyMs: number | null;
  model: string;
}

export function UsageBar({ usage, latencyMs, model }: Props) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center gap-x-4 gap-y-1 px-4 py-1.5 font-mono text-[0.7rem] text-zinc-400 dark:text-zinc-600">
      <span>{model}</span>
      {latencyMs != null && <Stat label="latency" value={`${latencyMs.toFixed(0)} ms`} />}
      {usage && (
        <>
          <Stat label="prompt" value={usage.prompt_tokens} />
          <Stat label="completion" value={usage.completion_tokens} />
          <Stat label="total" value={usage.total_tokens} />
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <span>
      <span className="text-zinc-400 dark:text-zinc-600">{label}:</span> <span>{value}</span>
    </span>
  );
}
