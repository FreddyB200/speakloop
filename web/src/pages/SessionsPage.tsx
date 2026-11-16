import { Link } from "react-router-dom";
import { listSessions } from "../api/client";
import { formatDate, roundHalfEven, formatDuration, kindLabel } from "../lib/format";
import { useAsync } from "../lib/useAsync";

export function SessionsPage() {
  const state = useAsync(listSessions, []);
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Sessions</h1>
      {state.status === "loading" && <p>Loading...</p>}
      {state.status === "error" && (
        <p role="alert" className="text-red-700 dark:text-red-300">
          Could not load sessions: {state.error.message}
        </p>
      )}
      {state.status === "ready" && state.data.length === 0 && (
        <div className="rounded border border-dashed border-stone-400 p-6">
          <p className="font-medium">No sessions yet.</p>
          <p className="mt-2">
            Create one today from a terminal with{" "}
            <code className="rounded bg-stone-200 px-1 dark:bg-stone-800">
              speakloop audit file.m4a
            </code>
            , then reload this page.
          </p>
        </div>
      )}
      {state.status === "ready" && state.data.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-stone-300 dark:border-stone-700">
                <th className="py-2 pr-4">Date</th>
                <th className="py-2 pr-4">Kind</th>
                <th className="py-2 pr-4">Duration</th>
                <th className="py-2 pr-4">Pace</th>
                <th className="py-2 pr-4">Fillers/100w</th>
                <th className="py-2 pr-4">Findings</th>
              </tr>
            </thead>
            <tbody>
              {state.data.map((s) => (
                <tr key={s.id} className="border-b border-stone-200 dark:border-stone-800">
                  <td className="py-2 pr-4">
                    <Link
                      to={`/sessions/${s.id}`}
                      className="font-medium text-blue-800 underline dark:text-blue-300"
                    >
                      {formatDate(s.created_at)}
                    </Link>
                  </td>
                  <td className="py-2 pr-4">{kindLabel(s.kind)}</td>
                  <td className="py-2 pr-4">{formatDuration(s.duration_s)}</td>
                  <td className="py-2 pr-4">
                    {s.wpm_mean === null ? "n/a" : `${roundHalfEven(s.wpm_mean)} wpm`}
                  </td>
                  <td className="py-2 pr-4">
                    {s.fillers_per_100w === null ? "n/a" : s.fillers_per_100w.toFixed(1)}
                  </td>
                  <td className="py-2 pr-4">
                    {s.findings_count}
                    {s.audit_error && (
                      <span
                        title={s.audit_error}
                        className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-900 dark:text-amber-100"
                      >
                        Audit failed
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
