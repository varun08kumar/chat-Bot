import { useEffect, useRef, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ChatPage } from "./pages/ChatPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { useAuth } from "./hooks/useAuth";
import { useDarkMode } from "./hooks/useDarkMode";
import type { User } from "./lib/types";

export default function App() {
  const [dark, toggleDark] = useDarkMode();
  const { user, isAuthenticated, isLoading, logout } = useAuth();
  const location = useLocation();
  const onDashboard = location.pathname.startsWith("/dashboard");

  return (
    <div className="relative h-full">
      <div className="absolute right-3 top-3 z-10 flex items-center gap-2">
        {isAuthenticated &&
          (onDashboard ? (
            <IconLink to="/" title="Back to chat">
              <ChatIcon />
            </IconLink>
          ) : (
            <IconLink to="/dashboard" title="Dashboard">
              <BarChartIcon />
            </IconLink>
          ))}
        <button
          onClick={toggleDark}
          aria-label="Toggle theme"
          title="Toggle theme"
          className="grid h-8 w-8 place-items-center rounded-lg border border-zinc-200 text-zinc-500 transition hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900"
        >
          {dark ? <SunIcon /> : <MoonIcon />}
        </button>
        {isAuthenticated && user && (
          <UserMenu user={user} onLogout={() => logout.mutate()} />
        )}
      </div>

      <Routes>
        <Route path="/login" element={isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />} />
        <Route path="/register" element={isAuthenticated ? <Navigate to="/" replace /> : <RegisterPage />} />
        <Route
          path="/"
          element={
            <RequireAuth isAuthenticated={isAuthenticated} isLoading={isLoading}>
              <ChatPage />
            </RequireAuth>
          }
        />
        <Route
          path="/c/:conversationId"
          element={
            <RequireAuth isAuthenticated={isAuthenticated} isLoading={isLoading}>
              <ChatPage />
            </RequireAuth>
          }
        />
        <Route
          path="/dashboard"
          element={
            <RequireAuth isAuthenticated={isAuthenticated} isLoading={isLoading}>
              <DashboardPage />
            </RequireAuth>
          }
        />
      </Routes>
    </div>
  );
}

function RequireAuth({
  isAuthenticated,
  isLoading,
  children,
}: {
  isAuthenticated: boolean;
  isLoading: boolean;
  children: React.ReactNode;
}) {
  if (isLoading) return null; // avoid a login-page flash while the session check is in flight
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

const AVATAR_COLORS = [
  "bg-rose-500",
  "bg-orange-500",
  "bg-amber-500",
  "bg-emerald-500",
  "bg-teal-500",
  "bg-sky-500",
  "bg-indigo-500",
  "bg-violet-500",
];

function avatarColor(email: string): string {
  let hash = 0;
  for (let i = 0; i < email.length; i++) hash = (hash * 31 + email.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

function initials(email: string): string {
  const name = email.split("@")[0] ?? email;
  return name.slice(0, 2).toUpperCase();
}

function UserMenu({ user, onLogout }: { user: User; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Account menu"
        title={user.email}
        className={`grid h-8 w-8 place-items-center rounded-full text-xs font-semibold text-white transition ${avatarColor(
          user.email
        )} ${open ? "ring-2 ring-zinc-400 ring-offset-2 dark:ring-offset-zinc-950" : "hover:opacity-90"}`}
      >
        {initials(user.email)}
      </button>
      {open && (
        <div className="absolute right-0 top-10 w-56 rounded-lg border border-zinc-200 bg-white py-1 shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center gap-2 border-b border-zinc-100 px-3 py-2 dark:border-zinc-800">
            <div
              className={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-white ${avatarColor(
                user.email
              )}`}
            >
              {initials(user.email)}
            </div>
            <span className="truncate text-sm text-zinc-700 dark:text-zinc-300">{user.email}</span>
          </div>
          <button
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-zinc-600 transition hover:bg-zinc-50 dark:text-zinc-400 dark:hover:bg-zinc-800"
          >
            <LogoutIcon />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

function IconLink({ to, title, children }: { to: string; title: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      title={title}
      aria-label={title}
      className={({ isActive }) =>
        `grid h-8 w-8 place-items-center rounded-lg border transition ${
          isActive
            ? "border-zinc-900 bg-zinc-900 text-white dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
            : "border-zinc-200 text-zinc-500 hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900"
        }`
      }
    >
      {children}
    </NavLink>
  );
}

function BarChartIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M4 20V10M12 20V4M20 20v-6" />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function SunIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function LogoutIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5M21 12H9" />
    </svg>
  );
}
