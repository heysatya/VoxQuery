import { describe, expect, it } from "vitest";
import {
  getStatusLabel,
  mapVoiceToRecordingState,
  notice,
  parseAudioEvent,
  parsePipelineEvent,
  transitionVoiceState,
  turnPhaseFromPipelineStage
} from "./interactionState";

describe("interaction state", () => {
  it("uses explicit voice capture states while preserving legacy recording states", () => {
    let state = transitionVoiceState("idle", "request_permission");
    expect(state).toBe("permission_requesting");
    expect(mapVoiceToRecordingState(state)).toBe("connecting");

    state = transitionVoiceState(state, "permission_granted");
    expect(state).toBe("connecting");

    state = transitionVoiceState(state, "connected");
    expect(state).toBe("listening");
    expect(mapVoiceToRecordingState(state)).toBe("recording");

    state = transitionVoiceState(state, "stop_requested");
    expect(state).toBe("stopping");
    expect(mapVoiceToRecordingState(state)).toBe("processing");

    state = transitionVoiceState(state, "transcript_ready");
    expect(state).toBe("reviewing");
    expect(mapVoiceToRecordingState(state)).toBe("idle");
  });

  it("maps backend pipeline stages to explicit turn phases", () => {
    expect(turnPhaseFromPipelineStage("rag_retrieval")).toBe("retrieving_context");
    expect(turnPhaseFromPipelineStage("sql_generation")).toBe("generating_sql");
    expect(turnPhaseFromPipelineStage("sql_validation")).toBe("validating_sql");
    expect(turnPhaseFromPipelineStage("snowflake_executing")).toBe("executing");
    expect(turnPhaseFromPipelineStage("rendering")).toBe("preparing_answer");
  });

  it("carries notice severity as first-class state", () => {
    expect(notice("Careful", "warning")).toEqual({ message: "Careful", severity: "warning" });
    expect(notice("Plain")).toEqual({ message: "Plain", severity: "info" });
  });

  it("accepts valid pipeline events and rejects malformed envelopes", () => {
    expect(
      parsePipelineEvent(JSON.stringify({
        type: "pipeline_progress",
        turn_id: "turn-1",
        stage: "sql_generation",
        elapsed_ms: 20
      }))
    ).toEqual({
      type: "pipeline_progress",
      turn_id: "turn-1",
      stage: "sql_generation",
      elapsed_ms: 20
    });

    expect(parsePipelineEvent(JSON.stringify({ type: "pipeline_progress", stage: "sql_generation" }))).toBeNull();
    expect(parsePipelineEvent("not-json")).toBeNull();
  });

  it("keeps result_ready tolerant because the UI fetches the full result by turn id", () => {
    expect(parsePipelineEvent(JSON.stringify({ type: "result_ready", turn_id: "turn-1" }))).toEqual({
      type: "result_ready",
      turn_id: "turn-1",
      confidence_tier: undefined,
      chart_type: undefined,
      chart_rationale: undefined,
      result_json: undefined,
      proactive_questions: undefined,
      from_cache: undefined
    });
  });

  it("validates audio events before transcript state can change", () => {
    expect(
      parseAudioEvent(JSON.stringify({
        type: "final_transcript",
        text: "Show revenue",
        confidence: 0.91,
        is_final: true
      }))
    ).toEqual({
      type: "final_transcript",
      text: "Show revenue",
      confidence: 0.91,
      is_final: true
    });

    expect(parseAudioEvent(JSON.stringify({ type: "final_transcript", text: "Missing confidence" }))).toBeNull();
  });

  describe("getStatusLabel derives status from explicit lifecycle state", () => {
    it("returns reviewing label when voiceState is reviewing", () => {
      expect(getStatusLabel("reviewing", "idle", "idle")).toBe(
        "Review your transcript before submitting"
      );
    });

    it("returns capture error label", () => {
      expect(getStatusLabel("capture_error", "idle", "idle")).toBe(
        "Voice capture failed — use text input"
      );
    });

    it("returns clarification_required label", () => {
      expect(getStatusLabel("idle", "clarification_required", "idle")).toBe(
        "Clarification needed before executing"
      );
    });

    it("returns recoverable_error label", () => {
      expect(getStatusLabel("idle", "recoverable_error", "idle")).toBe(
        "Something went wrong — try rephrasing"
      );
    });

    it("returns fatal_error label", () => {
      expect(getStatusLabel("idle", "fatal_error", "idle")).toBe(
        "Query failed — check the backend connection"
      );
    });

    it("returns tts failed label when completed but tts failed", () => {
      expect(getStatusLabel("idle", "completed", "failed")).toBe(
        "Voice playback failed — text answer is shown"
      );
    });

    it("returns result ready when completed and tts ended", () => {
      expect(getStatusLabel("idle", "completed", "ended")).toBe("Result ready");
    });

    it("returns Ready as the baseline idle state", () => {
      expect(getStatusLabel("idle", "idle", "idle")).toBe("Ready");
    });

    it("gives voice state priority over turn state", () => {
      // Even if a turn error exists, a voice capture in progress takes precedence.
      expect(getStatusLabel("listening", "fatal_error", "idle")).toBe("Recording...");
    });
  });
});


