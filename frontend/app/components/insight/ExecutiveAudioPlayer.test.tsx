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
    expect(screen.getByText("Executive Briefing Audio")).toBeInTheDocument();
    // No voiceUrl → no <audio> element
    expect(document.querySelector("audio")).toBeNull();
  });

  it("renders an audio element when voiceUrl is provided", () => {
    vi.stubGlobal("speechSynthesis", {
      cancel: vi.fn(),
      speak: vi.fn(),
    });

    render(
      <ExecutiveAudioPlayer
        textToSpeak="Test briefing"
        voiceUrl="http://localhost/audio.mp3"
      />
    );
    expect(screen.getByText("Morning Voice Podcast Summary")).toBeInTheDocument();
    // With voiceUrl the component mounts an <audio> element
    const audio = document.querySelector("audio");
    expect(audio).not.toBeNull();
    expect(audio?.getAttribute("src")).toBe("http://localhost/audio.mp3");
  });
});
