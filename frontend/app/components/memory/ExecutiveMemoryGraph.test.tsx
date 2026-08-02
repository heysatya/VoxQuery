import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExecutiveMemoryGraph } from "./ExecutiveMemoryGraph";

describe("ExecutiveMemoryGraph", () => {
  it("renders the empty state when there is no session", () => {
    render(<ExecutiveMemoryGraph sessionId={null} />);
    expect(screen.getByText("Your conversation trail will appear here.")).toBeInTheDocument();
  });

  it("renders the conversation trail while loading history", () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise(() => undefined)));
    render(<ExecutiveMemoryGraph sessionId="test-session" authToken="fake-token" />);
    expect(screen.getByText("Conversation trail")).toBeInTheDocument();
  });
});
