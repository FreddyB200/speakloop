export function NewSessionPage() {
  return (
    <section>
      <h1 className="mb-2 text-2xl font-semibold">New session</h1>
      <p>Recording arrives in W2.</p>
      <p className="mt-2 text-sm text-stone-600 dark:text-stone-400">
        For now, run <code>speakloop audit file.m4a</code> in a terminal.
      </p>
    </section>
  );
}
