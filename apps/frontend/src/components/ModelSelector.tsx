import { useProviders } from "@/hooks/useConversations";

interface Props {
  value: string;
  onChange: (model: string) => void;
  variant?: "default" | "footer";
}

export function ModelSelector({ value, onChange, variant = "default" }: Props) {
  const { data: providers = [] } = useProviders();
  const label = providers.flatMap((p) => p.models).find((m) => m.id === value)?.label ?? value;

  if (variant === "footer") {
    return (
      <div className="relative">
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Model"
          className="w-full cursor-pointer appearance-none bg-transparent font-mono text-xs text-zinc-600 outline-none dark:text-zinc-300"
        >
          {providers.map((p) => (
            <optgroup key={p.id} label={`${p.label}${p.enabled ? "" : " (no API key)"}`}>
              {p.models.map((m) => (
                <option key={m.id} value={m.id} disabled={!p.enabled}>
                  {m.label}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
        <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center text-zinc-400">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            <path d="M6 9l6 6 6-6" />
          </svg>
        </span>
        <span className="sr-only">{label}</span>
      </div>
    );
  }

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-zinc-200 bg-white px-2 py-1.5 text-sm text-zinc-700 outline-none focus:border-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
    >
      {providers.map((p) => (
        <optgroup key={p.id} label={`${p.label}${p.enabled ? "" : " (no API key)"}`}>
          {p.models.map((m) => (
            <option key={m.id} value={m.id} disabled={!p.enabled}>
              {m.label}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
