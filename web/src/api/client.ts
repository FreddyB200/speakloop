import {
  mockDetails,
  mockDoctor,
  mockHealth,
  mockList,
  mockSettings,
} from "./mock";
import type {
  Doctor,
  Health,
  Job,
  SessionDetail,
  SessionListItem,
  Settings,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const MOCK = import.meta.env.VITE_MOCK === "1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`.trim();
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // keep the status message
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

export const sessionUrl = (id: string): string =>
  `/api/sessions/${encodeURIComponent(id)}`;
export const audioUrl = (id: string, track: string): string =>
  `${sessionUrl(id)}/audio/${encodeURIComponent(track)}`;
export const reportUrl = (id: string): string => `${sessionUrl(id)}/report.md`;

export function getHealth(): Promise<Health> {
  return MOCK ? Promise.resolve(mockHealth) : request("/api/health");
}

export function getDoctor(): Promise<Doctor> {
  return MOCK ? Promise.resolve(mockDoctor) : request("/api/doctor");
}

export function listSessions(): Promise<SessionListItem[]> {
  return MOCK ? Promise.resolve(mockList) : request("/api/sessions");
}

export function getSession(id: string): Promise<SessionDetail> {
  if (MOCK) {
    const d = mockDetails[id];
    return d
      ? Promise.resolve(d)
      : Promise.reject(new ApiError(404, "Session not found"));
  }
  return request(sessionUrl(id));
}

export function getJob(jobId: string): Promise<Job> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export function exportSession(id: string): Promise<{ path: string }> {
  if (MOCK) return Promise.resolve({ path: `/mock/obsidian/${id}.md` });
  return request(`${sessionUrl(id)}/export`, { method: "POST" });
}

export function getSettings(): Promise<Settings> {
  return MOCK ? Promise.resolve(mockSettings) : request("/api/settings");
}

export function updateSettings(settings: Settings): Promise<Settings> {
  return request("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
}
