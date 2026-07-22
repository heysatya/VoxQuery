import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExecutiveAudioPlayer } from "./ExecutiveAudioPlayer";

describe("ExecutiveAudioPlayer", () => {
  it("renders correctly with custom title and state", () => {
    // Stub SpeechSynthesis
    vi.stubGlobal("speechSynthesis", {
      cancel: vi.fn(),
      speak: vi.fn(),
      pause: vi.fn(),
      resume: vi.fn(),
    });

    render(<ExecutiveAudioPlayer textToSpeak="Test briefing" />);
    expect(screen.getByText("Morning Voice Podcast Summary")).toBeInTheDocument();
  });
});
