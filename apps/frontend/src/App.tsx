import { NavLink, Route, Routes } from "react-router-dom";
import { ChatPage } from "./pages/ChatPage";
import { DashboardPage } from "./pages/DashboardPage";
import { useDarkMode } from "./hooks/useDarkMode";

export default function App() {
  const [dark, toggleDark] = useDarkMode();

  return (
    <div className="relative h-full">
      <div className="absolute right-3 top-3 z-10 flex items-center gap-1">
        <IconLink to="/dashboard" title="Dashboard">
          <BarChartIcon />
        </IconLink>
        <button
          onClick={toggleDark}
          aria-label="Toggle theme"
          title="Toggle theme"
          className="grid h-8 w-8 place-items-center rounded-lg border border-zinc-200 text-zinc-500 transition hover:bg-zinc-100 dark:border-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-900"
        >
          {dark ? <SunIcon /> : <MoonIcon />}
        </button>
      </div>

      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/c/:conversationId" element={<ChatPage />} />
        <Route path="/dashboard" element={<DashboardPage />} />
      </Routes>
    </div>
  );
}

function IconLink({ to, title, children }: { to: string; title: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
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
