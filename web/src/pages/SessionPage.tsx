import { useCallback, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError, audioUrl, exportSession, getSession } from "../api/client";
import type { Evidence, Metrics, SessionDetail } from "../api/types";
import { formatClock, roundHalfEven, formatDate, formatDuration, kindLabel, median } from "../lib/format";
import { useAsync } from "../lib/useAsync";

function metricCards(m: Metrics): { label: string; value: string; meaning: string }[] {
  return [
    { label: "Duration", value: formatDuration(m.duration_s), meaning: "Length of the recording." },
    { label: "Words", value: String(m.word_count), meaning: "Words you spoke." },
    { label: "Pace", value: `${roundHalfEven(m.wpm_mean)} wpm`, meaning: "Average words per minute." },
    {
      label: "Pace variation",
      value: m.wpm_cv === null ? "n/a" : m.wpm_cv.toFixed(2),
      meaning: "How much the pace changes between windows; higher means less even.",
    },
    {
      label: "Fillers",
      value: `${m.fillers_per_100w.toFixed(1)} per 100 words`,
      meaning: "Filler words and phrases such as um, uh or you know.",
    },
    {
      label: "Long pauses",
      value: `${m.long_pauses.length} (over ${m.long_pause_threshold_s} s)`,
      meaning: "Silences longer than the threshold.",
    },
    { label: "Repetitions", value: String(m.repetitions), meaning: "Words or phrases repeated back to back." },
    { label: "False starts", value: String(m.false_starts), meaning: "Sentences begun and then abandoned." },
    {
      label: "Lexical diversity",
      value: m.mattr === null ? "n/a" : m.mattr.toFixed(2),
      meaning: "MATTR: share of distinct words in a sliding window; higher means more varied.",
    },
    {
      label: "Response latency",
      value:
        m.response_latencies_s && m.response_latencies_s.length > 0
          ? `${median(m.response_latencies_s).toFixed(1)} s (median)`
          : "n/a",
      meaning: "Time between the other person finishing and you starting.",
    },
  ];
}

function QuoteButton({ ev, onSeek }: { ev: Evidence; onSeek: (t: number) => void }) {
  return (
    <button
      type="button"
      onClick={() => onSeek(ev.start)}
      className="block w-full cursor-pointer border-l-4 border-stone-400 py-1 pl-3 text-left italic hover:bg-stone-100 dark:hover:bg-stone-900"
    >
      &ldquo;{ev.quote}&rdquo;{" "}
      <span className="not-italic text-stone-600 dark:text-stone-400">
        ({formatClock(ev.start)}, {ev.track})
      </span>
    </button>
  );
}

function Detail({ data }: { data: SessionDetail }) {
  const { session, metrics, findings, audit, transcript, audio_tracks } = data;
  const audioRef = useRef<HTMLAudioElement>(null);
  const [now, setNow] = useState(0);
  const [exportState, setExportState] = useState<
    { kind: "idle" } | { kind: "busy" } | { kind: "ok"; path: string } | { kind: "error"; message: string }
  >({ kind: "idle" });
  const hasAudio = audio_tracks.includes("mic");

  const seek = useCallback(
    (t: number) => {
      const el = audioRef.current;
      if (!el) return;
      el.currentTime = t;
      setNow(t);
      void Promise.resolve(el.play()).catch(() => undefined);
    },
    [],
  );

  const doExport = async () => {
    setExportState({ kind: "busy" });
    try {
      const { path } = await exportSession(session.id);
      setExportState({ kind: "ok", path });
    } catch (e) {
      setExportState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  };

  const fde = metrics?.fde ?? null;

  return (
    <article className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold">{kindLabel(session.kind)} session</h1>
        <p className="text-stone-600 dark:text-stone-400">
          {formatDate(session.created_at)}
          {metrics && ` · ${formatDuration(metrics.duration_s)}`}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={doExport}
            disabled={exportState.kind === "busy"}
            className="rounded bg-blue-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-900 disabled:opacity-60"
          >
            Export to Obsidian
          </button>
          {exportState.kind === "ok" && (
            <p role="status">Exported to {exportState.path}</p>
          )}
          {exportState.kind === "error" && (
            <p role="alert" className="text-red-700 dark:text-red-300">
              Export failed: {exportState.message}
            </p>
          )}
        </div>
        {hasAudio && (
          <audio
            ref={audioRef}
            controls
            preload="metadata"
            src={audioUrl(session.id, "mic")}
            onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
            className="mt-4 w-full"
            aria-label="Session audio"
          />
        )}
      </header>

      {audit?.error && (
        <p role="alert" className="rounded bg-amber-100 p-3 text-amber-950 dark:bg-amber-950 dark:text-amber-100">
          The audit failed: {audit.error}
        </p>
      )}

      {metrics && (
        <section aria-labelledby="metrics-h">
          <h2 id="metrics-h" className="mb-3 text-xl font-semibold">Metrics</h2>
          <ul className="grid gap-3 sm:grid-cols-2">
            {metricCards(metrics).map((c) => (
              <li key={c.label} className="rounded border border-stone-300 p-3 dark:border-stone-700">
                <p className="text-sm font-medium text-stone-700 dark:text-stone-300">{c.label}</p>
                <p className="text-lg font-semibold">{c.value}</p>
                <p className="text-sm text-stone-600 dark:text-stone-400">{c.meaning}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {fde && (
        <section aria-labelledby="fde-h">
          <h2 id="fde-h" className="mb-3 text-xl font-semibold">FDE</h2>
          <ul className="list-disc pl-5">
            <li>
              Clarifying questions before the first proposal:{" "}
              {fde.clarifying_questions_before_proposal ?? "n/a"}
            </li>
            <li>
              Talk ratio (your share of the talking):{" "}
              {fde.talk_ratio === null ? "n/a" : `${Math.round(fde.talk_ratio * 100)}%`}
            </li>
            <li>
              Closed with next steps:{" "}
              {fde.closed_with_next_steps === null ? "n/a" : fde.closed_with_next_steps ? "yes" : "no"}
            </li>
            <li>Risky commitments: {fde.risky_commitments.length}</li>
          </ul>
          {hasAudio || fde.risky_commitments.length > 0 ? (
            <div className="mt-2">
              {fde.risky_commitments.map((ev, i) => (
                <QuoteButton key={i} ev={ev} onSeek={seek} />
              ))}
            </div>
          ) : null}
        </section>
      )}

      <section aria-labelledby="patterns-h">
        <h2 id="patterns-h" className="mb-3 text-xl font-semibold">Patterns</h2>
        {findings.length === 0 ? (
          <p>No patterns found.</p>
        ) : (
          <ul className="space-y-4">
            {findings.map((f) => (
              <li key={f.id} className="rounded border border-stone-300 p-4 dark:border-stone-700">
                <h3 className="font-semibold">{f.title}</h3>
                <p className="text-sm text-stone-600 dark:text-stone-400">
                  {f.category.replace(/_/g, " ")}, severity {f.severity} of 3
                </p>
                <p className="mt-2">{f.explanation}</p>
                {f.suggestion && (
                  <p className="mt-2">
                    <strong>Suggestion:</strong> {f.suggestion}
                  </p>
                )}
                <div className="mt-2">
                  {f.evidence.map((ev, i) => (
                    <QuoteButton key={i} ev={ev} onSeek={seek} />
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {audit && (audit.summary || audit.next_session_goal) && (
        <section aria-labelledby="summary-h" className="space-y-4">
          {audit.summary && (
            <div>
              <h2 id="summary-h" className="mb-2 text-xl font-semibold">Summary</h2>
              <p>{audit.summary}</p>
            </div>
          )}
          {audit.next_session_goal && (
            <div>
              <h2 className="mb-2 text-xl font-semibold">Next session goal</h2>
              <p>{audit.next_session_goal}</p>
            </div>
          )}
        </section>
      )}

      <section aria-labelledby="transcript-h">
        <h2 id="transcript-h" className="mb-3 text-xl font-semibold">Transcript</h2>
        {!transcript || transcript.segments.length === 0 ? (
          <p>No transcript available.</p>
        ) : (
          <ol className="space-y-1">
            {transcript.segments.map((seg, i) => {
              const active = hasAudio && seg.track === "mic" && now >= seg.start && now < seg.end;
              return (
                <li key={i}>
                  <button
                    type="button"
                    onClick={() => seek(seg.start)}
                    aria-current={active ? "true" : undefined}
                    className={`w-full cursor-pointer rounded px-2 py-1 text-left hover:bg-stone-100 dark:hover:bg-stone-900 ${
                      active ? "bg-yellow-200 text-stone-950 dark:bg-yellow-700 dark:text-white" : ""
                    }`}
                  >
                    <span className="mr-2 font-mono text-sm text-stone-600 dark:text-stone-400">
                      [{formatClock(seg.start)}]
                    </span>
                    {seg.track === "system" && <em className="mr-1">(other speaker)</em>}
                    {seg.text}
                  </button>
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </article>
  );
}

export function SessionPage() {
  const { id = "" } = useParams();
  const state = useAsync(() => getSession(id), [id]);
  if (state.status === "loading") return <p>Loading...</p>;
  if (state.status === "error") {
    const notFound = state.error instanceof ApiError && state.error.status === 404;
    return (
      <p role="alert" className="text-red-700 dark:text-red-300">
        {notFound ? "Session not found." : `Could not load session: ${state.error.message}`}
      </p>
    );
  }
  return <Detail data={state.data} />;
}
