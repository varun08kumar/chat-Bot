import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export function RegisterPage() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    register.mutate(
      { email, password },
      { onSuccess: () => navigate("/") },
    );
  };

  return (
    <div className="grid h-full place-items-center bg-zinc-50/60 dark:bg-zinc-950">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-6 flex items-center gap-1.5">
          <span className="text-brand-600 dark:text-zinc-100" aria-hidden>◆</span>
          <span className="text-xs font-bold tracking-widest text-zinc-900 dark:text-zinc-100">CHAT BOT</span>
        </div>
        <h1 className="mb-1 text-lg font-medium text-zinc-900 dark:text-zinc-50">Create an account</h1>
        <p className="mb-5 text-sm text-zinc-500 dark:text-zinc-400">Takes a few seconds.</p>

        <label className="mb-3 block">
          <span className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">Email</span>
          <input
            type="email"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:border-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
        </label>
        <label className="mb-4 block">
          <span className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">Password</span>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 outline-none focus:border-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
          <span className="mt-1 block text-xs text-zinc-400">At least 8 characters.</span>
        </label>

        {register.isError && (
          <p className="mb-4 text-sm text-red-500">
            {(register.error as any)?.response?.data?.detail ?? "Something went wrong."}
          </p>
        )}

        <button
          type="submit"
          disabled={register.isPending}
          className="w-full rounded-xl bg-zinc-900 py-2.5 text-sm font-medium text-white transition hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-white"
        >
          {register.isPending ? "Creating account…" : "Sign up"}
        </button>

        <p className="mt-4 text-center text-sm text-zinc-500 dark:text-zinc-400">
          Already have an account? <Link to="/login" className="text-brand-600 underline dark:text-zinc-200">Log in</Link>
        </p>
      </form>
    </div>
  );
}
