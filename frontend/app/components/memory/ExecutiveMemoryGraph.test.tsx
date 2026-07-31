import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExecutiveMemoryGraph } from "./ExecutiveMemoryGraph";

describe("ExecutiveMemoryGraph", () => {
  const mockAuth = {
    mode: "fake" as const,
    ready: true,
    signedIn: true,
    getToken: async () => "fake-token",
  };

  it("renders empty state when sessionId is null", () => {
    render(<ExecutiveMemoryGraph sessionId={null} auth={mockAuth} />);
    expect(
      screen.getByText(
        "Ask a question to get started — I'll keep track of what you've covered as you go."
      )
    ).toBeInTheDocument();
  });

  it("renders loading state initially", async () => {
    // Mock the global fetch
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            session_id: "test-session",
            nodes: [{ id: "n1", label: "Query 1", type: "query", turn_index: 1 }],
            edges: [],
          }),
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ExecutiveMemoryGraph sessionId="test-session" auth={mockAuth} />);
    expect(screen.getByText("What we've covered")).toBeInTheDocument();
  });
});
