// Synthetic data for `VITE_MOCK=1 npm run dev`. Entirely invented.
import type { Doctor, Health, SessionDetail, SessionListItem, Settings } from "./types";

const detail1: SessionDetail = {
  session: {
    id: "20260105-093000-a1b2",
    created_at: "2026-01-05T09:30:00Z",
    kind: "discovery",
    scenario_id: "discovery-call",
    notes: null,
    tracks: [
      { id: "mic", role: "speaker", audio_path: "mic.wav" },
      { id: "system", role: "interlocutor", audio_path: null },
    ],
  },
  metrics: {
    session_id: "20260105-093000-a1b2",
    speaker_track: "mic",
    duration_s: 372,
    word_count: 810,
    wpm_mean: 130.5,
    wpm_windows: [120, 135, 128],
    wpm_cv: 0.123,
    long_pause_threshold_s: 2,
    long_pauses: [{ start: 40, end: 43 }],
    filler_counts: { um: 12, "you know": 4 },
    fillers_per_100w: 3.5,
    repetitions: 4,
    false_starts: 2,
    mattr: 0.712,
    response_latencies_s: [1.5, 2.0, 2.5],
    fde: {
      clarifying_questions_before_proposal: 1,
      talk_ratio: 0.625,
      closed_with_next_steps: false,
      risky_commitments: [
        { start: 125, end: 128, quote: "I guarantee zero downtime", track: "mic" },
      ],
    },
  },
  findings: [
    {
      id: "f1",
      session_id: "20260105-093000-a1b2",
      category: "grammar",
      title: "Missing article",
      explanation: "You often drop 'the' before singular nouns.",
      suggestion: "Say 'the pipeline' instead of 'pipeline'.",
      evidence: [{ start: 65, end: 68, quote: "we deploy pipeline", track: "mic" }],
      severity: 2,
      source: "audit",
    },
    {
      id: "f2",
      session_id: "20260105-093000-a1b2",
      category: "customer_judgment",
      title: "Promised a date too early",
      explanation: "A delivery date was committed before scoping the work.",
      suggestion: "Offer a range after discovery.",
      evidence: [{ start: 125, end: 128, quote: "I guarantee zero downtime", track: "mic" }],
      severity: 3,
      source: "audit",
    },
  ],
  audit: {
    summary: "Clear structure, but a few articles are dropped and one promise came early.",
    next_session_goal: "Ask two more questions before proposing.",
    proposal_time_s: 120,
    dropped_quotes: 0,
    discarded_findings: 0,
    rubric_version: "v1",
    error: null,
  },
  transcript: {
    session_id: "20260105-093000-a1b2",
    language: "en",
    backend: "fake",
    model: "mock",
    prompt: null,
    segments: [
      { start: 3, end: 8, text: "We call the API daily.", track: "mic", words: [] },
      { start: 12, end: 15, text: "Tell me more.", track: "system", words: [] },
      { start: 65, end: 68, text: "we deploy pipeline", track: "mic", words: [] },
      { start: 125, end: 128, text: "I guarantee zero downtime", track: "mic", words: [] },
    ],
  },
  audio_tracks: ["mic"],
};

const detail2: SessionDetail = {
  session: {
    id: "20260106-101500-c3d4",
    created_at: "2026-01-06T10:15:00Z",
    kind: "free",
    scenario_id: null,
    notes: null,
    tracks: [{ id: "mic", role: "speaker", audio_path: null }],
  },
  metrics: {
    ...detail1.metrics!,
    session_id: "20260106-101500-c3d4",
    duration_s: 90,
    fde: null,
    response_latencies_s: null,
  },
  findings: [],
  audit: {
    summary: null,
    next_session_goal: null,
    proposal_time_s: null,
    dropped_quotes: 0,
    discarded_findings: 0,
    rubric_version: null,
    error: "Audit backend unavailable (mock).",
  },
  transcript: {
    session_id: "20260106-101500-c3d4",
    language: "en",
    backend: "fake",
    model: "mock",
    prompt: null,
    segments: [{ start: 1, end: 6, text: "This is a short synthetic practice.", track: "mic", words: [] }],
  },
  audio_tracks: [],
};

export const mockDetails: Record<string, SessionDetail> = {
  [detail1.session.id]: detail1,
  [detail2.session.id]: detail2,
};

export const mockList: SessionListItem[] = [detail2, detail1].map((d) => ({
  id: d.session.id,
  created_at: d.session.created_at,
  kind: d.session.kind,
  scenario_id: d.session.scenario_id,
  duration_s: d.metrics?.duration_s ?? null,
  wpm_mean: d.metrics?.wpm_mean ?? null,
  fillers_per_100w: d.metrics?.fillers_per_100w ?? null,
  findings_count: d.findings.length,
  has_audio: d.audio_tracks.length > 0,
  audit_error: d.audit?.error ?? null,
}));

export const mockHealth: Health = { ok: true, version: "mock" };
export const mockDoctor: Doctor = {
  checks: [{ name: "mock", ok: true, detail: "Running with mock data" }],
};
export const mockSettings: Settings = {
  obsidian_dir: null,
  glossary: ["Kubernetes", "OAuth"],
  model_size: "small.en",
  language: "en",
};
