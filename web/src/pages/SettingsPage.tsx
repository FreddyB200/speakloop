import { getSettings } from "../api/client";
import { useAsync } from "../lib/useAsync";

export function SettingsPage() {
  const state = useAsync(getSettings, []);
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Settings</h1>
      <p className="mb-4 text-sm text-stone-600 dark:text-stone-400">
        Read-only for now.
      </p>
      {state.status === "loading" && <p>Loading...</p>}
      {state.status === "error" && (
        <p role="alert" className="text-red-700 dark:text-red-300">
          Could not load settings: {state.error.message}
        </p>
      )}
      {state.status === "ready" && (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2">
          <dt className="font-medium">Obsidian folder</dt>
          <dd>{state.data.obsidian_dir ?? "Not set"}</dd>
          <dt className="font-medium">Glossary</dt>
          <dd>{state.data.glossary.length ? state.data.glossary.join(", ") : "Empty"}</dd>
          <dt className="font-medium">Model size</dt>
          <dd>{state.data.model_size}</dd>
          <dt className="font-medium">Language</dt>
          <dd>{state.data.language}</dd>
        </dl>
      )}
    </section>
  );
}
