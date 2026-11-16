import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, audioUrl, exportSession, getSession, listSessions, reportUrl } from "../api/client";
import { jsonResponse } from "./fixtures";

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("builds URLs", () => {
    expect(audioUrl("abc", "mic")).toBe("/api/sessions/abc/audio/mic");
    expect(reportUrl("abc")).toBe("/api/sessions/abc/report.md");
  });

  it("requests the sessions list", async () => {
    const f = vi.fn().mockResolvedValue(jsonResponse([]));
    vi.stubGlobal("fetch", f);
    await expect(listSessions()).resolves.toEqual([]);
    expect(f).toHaveBeenCalledWith("/api/sessions", undefined);
  });

  it("raises ApiError with status on 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "nope" }, 404)));
    const err = await getSession("x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).message).toBe("nope");
  });

  it("posts export", async () => {
    const f = vi.fn().mockResolvedValue(jsonResponse({ path: "/o/x.md" }));
    vi.stubGlobal("fetch", f);
    await expect(exportSession("abc")).resolves.toEqual({ path: "/o/x.md" });
    expect(f).toHaveBeenCalledWith("/api/sessions/abc/export", { method: "POST" });
  });
});
