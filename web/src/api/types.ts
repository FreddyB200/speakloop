// Types mirroring docs/schemas/*.json (snake_case, as served by the API).

export type TrackId = "mic" | "system";

export type SessionKind =
  | "discovery"
  | "pressure"
  | "deep_dive"
  | "think_aloud"
  | "behavioral"
  | "demo"
  | "free"
  | "shadowing"
  | "retell_432";

export type FindingCategory =
  | "grammar"
  | "vocabulary"
  | "naturalness"
  | "pronunciation"
  | "fluency"
  | "structure"
  | "technical_accuracy"
  | "customer_judgment";

export interface Track {
  id: TrackId;
  role: "speaker" | "interlocutor";
  audio_path: string | null;
}

export interface Session {
  id: string;
  created_at: string;
  kind: SessionKind;
  scenario_id: string | null;
  notes: string | null;
  tracks: Track[];
}

export interface Evidence {
  start: number;
  end: number;
  quote: string;
  track: TrackId;
}

export interface Pause {
  start: number;
  end: number;
}

export interface FdeMetrics {
  clarifying_questions_before_proposal: number | null;
  talk_ratio: number | null;
  closed_with_next_steps: boolean | null;
  risky_commitments: Evidence[];
}

export interface Metrics {
  session_id: string;
  speaker_track: TrackId;
  duration_s: number;
  word_count: number;
  wpm_mean: number;
  wpm_windows: number[];
  wpm_cv: number | null;
  long_pause_threshold_s: number;
  long_pauses: Pause[];
  filler_counts: Record<string, number>;
  fillers_per_100w: number;
  repetitions: number;
  false_starts: number;
  mattr: number | null;
  response_latencies_s: number[] | null;
  fde: FdeMetrics | null;
}

export interface Finding {
  id: string;
  session_id: string;
  category: FindingCategory;
  title: string;
  explanation: string;
  suggestion: string | null;
  evidence: Evidence[];
  severity: 1 | 2 | 3;
  source: "metrics" | "audit";
}

export interface AuditSummary {
  summary: string | null;
  next_session_goal: string | null;
  proposal_time_s: number | null;
  dropped_quotes: number;
  discarded_findings: number;
  rubric_version: string | null;
  error: string | null;
}

export interface Word {
  start: number;
  end: number;
  text: string;
  track: TrackId;
  probability: number | null;
}

export interface Segment {
  start: number;
  end: number;
  text: string;
  track: TrackId;
  words: Word[];
}

export interface Transcript {
  session_id: string;
  language: string | null;
  backend: string;
  model: string;
  prompt: string | null;
  segments: Segment[];
}

// API payloads (contract v0)

export interface Health {
  ok: boolean;
  version: string;
}

export interface DoctorCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface Doctor {
  checks: DoctorCheck[];
}

export interface SessionListItem {
  id: string;
  created_at: string;
  kind: SessionKind;
  scenario_id: string | null;
  duration_s: number | null;
  wpm_mean: number | null;
  fillers_per_100w: number | null;
  findings_count: number;
  has_audio: boolean;
  audit_error: string | null;
}

export interface SessionDetail {
  session: Session;
  metrics: Metrics | null;
  findings: Finding[];
  audit: AuditSummary | null;
  transcript: Transcript | null;
  audio_tracks: string[];
}

export type JobStatus =
  | "queued"
  | "transcribing"
  | "analyzing"
  | "auditing"
  | "saving"
  | "done"
  | "error";

export interface Job {
  job_id: string;
  status: JobStatus;
  session_id: string | null;
  error: string | null;
  audit_error: string | null;
}

export interface Settings {
  obsidian_dir: string | null;
  glossary: string[];
  model_size: string;
  language: string;
}
