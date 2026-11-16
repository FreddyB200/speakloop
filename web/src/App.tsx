import { NavLink, Route, Routes } from "react-router-dom";
import { NewSessionPage } from "./pages/NewSessionPage";
import { SessionPage } from "./pages/SessionPage";
import { SessionsPage } from "./pages/SessionsPage";
import { SettingsPage } from "./pages/SettingsPage";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `rounded px-3 py-1.5 text-sm font-medium ${
    isActive
      ? "bg-stone-200 dark:bg-stone-800"
      : "text-stone-700 hover:bg-stone-100 dark:text-stone-300 dark:hover:bg-stone-900"
  }`;

export function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 dark:border-stone-800">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-4 px-4 py-3">
          <span className="text-lg font-semibold">SpeakLoop</span>
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-900 dark:text-amber-100">
            Pre-alpha
          </span>
          <nav aria-label="Main" className="flex gap-1">
            <NavLink to="/" end className={linkClass}>
              Sessions
            </NavLink>
            <NavLink to="/new" className={linkClass}>
              New session
            </NavLink>
            <NavLink to="/settings" className={linkClass}>
              Settings
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6">
        <Routes>
          <Route path="/" element={<SessionsPage />} />
          <Route path="/sessions/:id" element={<SessionPage />} />
          <Route path="/new" element={<NewSessionPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<p>Page not found.</p>} />
        </Routes>
      </main>
    </div>
  );
}
