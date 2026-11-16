import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionPage } from "../pages/SessionPage";
import { SessionsPage } from "../pages/SessionsPage";
import { detail, jsonResponse, listItems } from "./fixtures";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(routes: Record<string, () => Response>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const h = routes[url];
      return Promise.resolve(h ? h() : jsonResponse({ detail: "not found" }, 404));
    }),
  );
}

function renderSession() {
  return render(
    <MemoryRouter initialEntries={["/sessions/20260105-093000-a1b2"]}>
      <Routes>
        <Route path="/sessions/:id" element={<SessionPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const SESSION_URL = "/api/sessions/20260105-093000-a1b2";

describe("SessionsPage", () => {
  it("lists sessions with an audit warning badge", async () => {
    stubFetch({ "/api/sessions": () => jsonResponse(listItems) });
    render(<MemoryRouter><SessionsPage /></MemoryRouter>);
    expect(await screen.findByText("130 wpm")).toBeInTheDocument();
    expect(screen.getByText("Discovery")).toBeInTheDocument();
    expect(screen.getAllByText("Audit failed")).toHaveLength(1);
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it("shows an empty state explaining how to create a session", async () => {
    stubFetch({ "/api/sessions": () => jsonResponse([]) });
    render(<MemoryRouter><SessionsPage /></MemoryRouter>);
    expect(await screen.findByText("No sessions yet.")).toBeInTheDocument();
    expect(screen.getByText("speakloop audit file.m4a")).toBeInTheDocument();
  });
});

describe("SessionPage", () => {
  it("renders metrics, patterns and transcript", async () => {
    stubFetch({ [SESSION_URL]: () => jsonResponse(detail()) });
    renderSession();
    expect(await screen.findByRole("heading", { name: "Metrics" })).toBeInTheDocument();
    expect(screen.getByText("130 wpm")).toBeInTheDocument();
    expect(screen.getByText("Average words per minute.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Missing article" })).toBeInTheDocument();
    expect(screen.getByText("A clear synthetic summary.")).toBeInTheDocument();
    expect(screen.getByText("Ask more questions.")).toBeInTheDocument();
    expect(screen.getByText("We call the API daily.")).toBeInTheDocument();
    expect(screen.getByText("[00:03]")).toBeInTheDocument();
  });

  it("hides the player when there is no audio", async () => {
    stubFetch({ [SESSION_URL]: () => jsonResponse(detail(false)) });
    const { container } = renderSession();
    await screen.findByRole("heading", { name: "Metrics" });
    expect(container.querySelector("audio")).toBeNull();
  });

  it("seeks and plays when a quote is clicked", async () => {
    stubFetch({ [SESSION_URL]: () => jsonResponse(detail()) });
    const play = vi
      .spyOn(HTMLMediaElement.prototype, "play")
      .mockImplementation(() => Promise.resolve());
    const { container } = renderSession();
    await userEvent.click(await screen.findByRole("button", { name: /deploy pipeline.+01:05/ }));
    const audio = container.querySelector("audio") as HTMLAudioElement;
    expect(audio.currentTime).toBe(65);
    expect(play).toHaveBeenCalled();
    play.mockRestore();
  });

  it("shows the export path on success", async () => {
    stubFetch({
      [SESSION_URL]: () => jsonResponse(detail()),
      [`${SESSION_URL}/export`]: () => jsonResponse({ path: "/vault/x.md" }),
    });
    renderSession();
    await userEvent.click(await screen.findByRole("button", { name: "Export to Obsidian" }));
    expect(await screen.findByText("Exported to /vault/x.md")).toBeInTheDocument();
  });

  it("shows the export error", async () => {
    stubFetch({
      [SESSION_URL]: () => jsonResponse(detail()),
      [`${SESSION_URL}/export`]: () => jsonResponse({ detail: "No Obsidian folder" }, 400),
    });
    renderSession();
    await userEvent.click(await screen.findByRole("button", { name: "Export to Obsidian" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Export failed: No Obsidian folder"),
    );
  });

  it("shows not found on 404", async () => {
    stubFetch({});
    renderSession();
    expect(await screen.findByText("Session not found.")).toBeInTheDocument();
  });
});
