import type { SessionDetail, SessionListItem } from "../api/types";

export const listItems: SessionListItem[] = [
  {
    id: "20260105-093000-a1b2",
    created_at: "2026-01-05T09:30:00Z",
    kind: "discovery",
    scenario_id: null,
    duration_s: 372,
    wpm_mean: 130.5,
    fillers_per_100w: 3.5,
    findings_count: 2,
    has_audio: true,
    audit_error: null,
  },
  {
    id: "20260106-101500-c3d4",
    created_at: "2026-01-06T10:15:00Z",
    kind: "free",
    scenario_id: null,
    duration_s: 90,
    wpm_mean: 120,
    fillers_per_100w: 1,
    findings_count: 0,
    has_audio: false,
    audit_error: "backend down",
  },
];

export function detail(withAudio = true): SessionDetail {
  return {
    session: {
      id: "20260105-093000-a1b2",
      created_at: "2026-01-05T09:30:00Z",
      kind: "discovery",
      scenario_id: null,
      notes: null,
      tracks: [{ id: "mic", role: "speaker", audio_path: null }],
    },
    metrics: {
      session_id: "20260105-093000-a1b2",
      speaker_track: "mic",
      duration_s: 372,
      word_count: 810,
      wpm_mean: 130.5,
      wpm_windows: [],
      wpm_cv: 0.123,
      long_pause_threshold_s: 2,
      long_pauses: [],
      filler_counts: {},
      fillers_per_100w: 3.5,
      repetitions: 4,
      false_starts: 2,
      mattr: 0.712,
      response_latencies_s: null,
      fde: null,
    },
    findings: [
      {
        id: "f1",
        session_id: "20260105-093000-a1b2",
        category: "grammar",
        title: "Missing article",
        explanation: "You often drop 'the'.",
        suggestion: "Say 'the pipeline'.",
        evidence: [{ start: 65, end: 68, quote: "we deploy pipeline", track: "mic" }],
        severity: 2,
        source: "audit",
      },
    ],
    audit: {
      summary: "A clear synthetic summary.",
      next_session_goal: "Ask more questions.",
      proposal_time_s: null,
      dropped_quotes: 0,
      discarded_findings: 0,
      rubric_version: "v1",
      error: null,
    },
    transcript: {
      session_id: "20260105-093000-a1b2",
      language: "en",
      backend: "fake",
      model: "m",
      prompt: null,
      segments: [
        { start: 3, end: 8, text: "We call the API daily.", track: "mic", words: [] },
        { start: 65, end: 68, text: "we deploy pipeline", track: "mic", words: [] },
      ],
    },
    audio_tracks: withAudio ? ["mic"] : [],
  };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
