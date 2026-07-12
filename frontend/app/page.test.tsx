import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HomePage from "./page";

const session = {
  session_id: "session-1",
  conversation_id: "conversation-1",
  expires_at: "2026-07-01T00:00:00Z"
};

const secondSession = {
  session_id: "session-2",
  conversation_id: "conversation-2",
  expires_at: "2026-07-01T01:00:00Z"
};

const result = {
  turn_id: "turn-1",
  chart_type: "bar",
  chart_rationale: "Showing as bar chart - categorical comparison detected on customer_segment.",
  confidence_tier: "High",
  generated_sql:
    "SELECT customers.customer_segment, SUM(order_items.price * (1 - order_items.discount_rate) + order_items.freight_value) FROM order_items JOIN orders ON order_items.order_id = orders.order_id JOIN customers ON orders.customer_id = customers.customer_id GROUP BY customers.customer_segment LIMIT 100",
  result: {
    columns: ["customer_segment", "total_net_revenue"],
    rows: [["Enterprise", 1240000]],
    row_count: 1
  },
  tts_text: "Enterprise leads net revenue.",
  from_cache: false,
  proactive_questions: [],
  warnings: []
};

const mediumResult = {
  ...result,
  turn_id: "turn-medium",
  confidence_tier: "Medium",
};

const staleResult = {
  ...result,
  turn_id: "turn-a",
  tts_text: "Revenue by region result."
};

const followupResult = {
  ...result,
  turn_id: "turn-b",
  tts_text: "Enterprise customer result."
};

const suggestedResult = {
  ...result,
  turn_id: "turn-suggestions",
  proactive_questions: ["Show enterprise only", "Compare with consumer"]
};

const duplicationWarningResult = {
  ...result,
  turn_id: "turn-duplication",
  warnings: [
    {
      code: "possible_duplication",
      message: "The join returned many rows; duplicate source records may be inflating this result.",
      suggested_sql: "SELECT DISTINCT customers.customer_segment FROM customers"
    }
  ]
};

const csvResult = {
  ...result,
  turn_id: "turn-csv",
  tts_text: "Enterprise, Inc. leads net revenue.",
  result: {
    columns: ["customer_segment", "total_net_revenue"],
    rows: [["Enterprise, Inc.", 1240000], ["SMB", 800000]],
    row_count: 2
  }
};

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
    queueMicrotask(() => this.onopen?.());
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView) {
    if (!this.url.includes("/ws/audio")) {
      return;
    }
    if (typeof data !== "string") {
      this.emit({ type: "interim_transcript", text: "Show revenue", is_final: false });
      return;
    }
    this.emit({
      type: "final_transcript",
      text: "Show revenue by region",
      confidence: 0.97,
      is_final: true
    });
  }

  close(code = 1000) {
    this.onclose?.({ code });
  }

  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

class MockAudioWorkletNode {
  port: { onmessage: ((event: { data: ArrayBuffer }) => void) | null } = { onmessage: null };
  connect = vi.fn();
  disconnect = vi.fn();
  
  static instances: MockAudioWorkletNode[] = [];
  
  constructor() {
    MockAudioWorkletNode.instances.push(this);
  }
}

class MockAudioContext {
  state = "running";
  audioWorklet = {
    addModule: vi.fn().mockResolvedValue(undefined)
  };
  destination = {};
  
  createMediaStreamSource = vi.fn().mockReturnValue({ connect: vi.fn() });
  createGain = vi.fn().mockReturnValue({ gain: { value: 1 }, connect: vi.fn() });
  createAnalyser = vi.fn().mockReturnValue({ 
    fftSize: 256, 
    frequencyBinCount: 128, 
    connect: vi.fn(), 
    getByteFrequencyData: vi.fn() 
  });
  createBufferSource = vi.fn().mockReturnValue({
    buffer: null,
    connect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn()
  });
  createBuffer = vi.fn().mockReturnValue({
    getChannelData: vi.fn().mockReturnValue(new Float32Array(0))
  });
  close = vi.fn().mockResolvedValue(undefined);
  suspend = vi.fn().mockResolvedValue(undefined);
  
  static instances: MockAudioContext[] = [];
  
  constructor() {
    MockAudioContext.instances.push(this);
  }
}

type TestWindow = Window & {
  AudioContext: typeof MockAudioContext;
  webkitAudioContext: typeof MockAudioContext;
};

describe("HomePage", () => {
  let sessionCalls = 0;
  let feedbackCalls = 0;
  let telemetryCalls: Array<string | undefined> = [];
  let queryBodies: Array<Record<string, unknown>> = [];
  let queryTurnIds: string[] = [];
  let feedbackBodies: Array<Record<string, unknown>> = [];
  let clarificationBodies: Array<Record<string, unknown>> = [];

  beforeEach(() => {
    window.sessionStorage.clear();
    FakeWebSocket.instances = [];
    MockAudioContext.instances = [];
    MockAudioWorkletNode.instances = [];
    sessionCalls = 0;
    feedbackCalls = 0;
    telemetryCalls = [];
    queryBodies = [];
    queryTurnIds = [];
    feedbackBodies = [];
    clarificationBodies = [];
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    vi.stubGlobal("AudioContext", MockAudioContext);
    vi.stubGlobal("webkitAudioContext", MockAudioContext);
    const testWindow = window as unknown as TestWindow;
    testWindow.AudioContext = MockAudioContext;
    testWindow.webkitAudioContext = MockAudioContext;
    vi.stubGlobal("AudioWorkletNode", MockAudioWorkletNode);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/api/session")) {
          sessionCalls += 1;
          return jsonResponse(sessionCalls === 1 ? session : secondSession, 201);
        }
        if (url.endsWith("/api/query")) {
          queryBodies.push(JSON.parse(String(init?.body)));
          return jsonResponse({ turn_id: queryTurnIds.shift() ?? "turn-1", status: "processing" }, 202);
        }
        if (url.endsWith("/api/clarification")) {
          clarificationBodies.push(JSON.parse(String(init?.body)));
          return jsonResponse({ status: "received", turn_id: "turn-1" });
        }
        if (url.endsWith("/api/result/turn-1")) {
          return jsonResponse(result);
        }
        if (url.endsWith("/api/result/turn-medium")) {
          return jsonResponse(mediumResult);
        }
        if (url.endsWith("/api/result/turn-a")) {
          return jsonResponse(staleResult);
        }
        if (url.endsWith("/api/result/turn-b")) {
          return jsonResponse(followupResult);
        }
        if (url.endsWith("/api/result/turn-suggestions")) {
          return jsonResponse(suggestedResult);
        }
        if (url.endsWith("/api/result/turn-duplication")) {
          return jsonResponse(duplicationWarningResult);
        }
        if (url.endsWith("/api/result/turn-csv")) {
          return jsonResponse(csvResult);
        }
        if (url.endsWith("/api/feedback")) {
          feedbackCalls += 1;
          feedbackBodies.push(JSON.parse(String(init?.body)));
          if (feedbackCalls > 1) {
            return jsonResponse(
              {
                error: {
                  code: "feedback_duplicate",
                  message: "Feedback already recorded for this query.",
                  detail: null
                }
              },
              409
            );
          }
          return jsonResponse({ status: "recorded" });
        }
        if (url.endsWith("/api/telemetry")) {
          telemetryCalls.push(typeof init?.body === "string" ? init.body : undefined);
          return jsonResponse({ status: "recorded" });
        }
        // DELETE /api/session/{id} — best-effort session cleanup; return 200 in tests.
        if (url.includes("/api/session/") && init?.method === "DELETE") {
          return jsonResponse({ status: "deleted" });
        }
        return jsonResponse({}, 404);
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    FakeWebSocket.instances = [];
  });

  it("stores only the session id and opens the pipeline stream", async () => {
    render(<HomePage />);
    await waitFor(() => expect(window.sessionStorage.getItem("voxquery_session_id")).toBe("session-1"));
    expect(window.sessionStorage.getItem("conversation_id")).toBeNull();
    await waitFor(() => expect(pipelineSocket()).toBeTruthy());
  });

  it("resumes a stored session id without creating a replacement session", async () => {
    window.sessionStorage.setItem("voxquery_session_id", "stored-session");
    render(<HomePage />);

    await waitFor(() => expect(pipelineSocket()).toBeTruthy());
    expect(pipelineSocket()?.url).toContain("session_id=stored-session");
    expect(sessionCalls).toBe(0);
    expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled();
  });

  it("keeps transcript editable and renders clarification from the pipeline event", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show revenue by region" } });
    expect(input).toHaveValue("Show revenue by region");

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(queryBodies).toHaveLength(1));

    await emitPipeline({
      type: "clarification_request",
      turn_id: "turn-1",
      question: "Which revenue metric did you mean?",
      options: ["Gross revenue", "Net revenue", "Recognized revenue"]
    });

    await screen.findByRole("dialog", { name: "Which revenue metric did you mean?" });
    
    expect(screen.getByRole("button", { name: "Net revenue" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Gross revenue" })).toHaveFocus());
  });

  it("selecting a clarification option posts the resolution and renders the resumed result", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show revenue by region" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(queryBodies).toHaveLength(1));

    await emitPipeline({
      type: "clarification_request",
      turn_id: "turn-1",
      question: "Which revenue metric did you mean?",
      options: ["Gross revenue", "Net revenue", "Recognized revenue"]
    });

    fireEvent.click(await screen.findByRole("button", { name: "Net revenue" }));
    await waitFor(() => expect(clarificationBodies).toHaveLength(1));
    expect(clarificationBodies[0]).toMatchObject({
      session_id: "session-1",
      turn_id: "turn-1",
      selection: "Net revenue",
      resolution_type: "option_selected",
    });

    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });
    expect(await screen.findByText("Enterprise leads net revenue.")).toBeInTheDocument();
  });

  it("starts a new conversation and clears local input state", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    expect(input).toHaveValue("Show net revenue by customer segment");

    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));

    await waitFor(() => expect(window.sessionStorage.getItem("voxquery_session_id")).toBe("session-2"));
    expect(input).toHaveValue("");
    expect(await screen.findByText("New conversation started.")).toBeInTheDocument();
  });

  it("fake voice uses the audio stream and fills an editable transcript", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.click(screen.getByRole("button", { name: "Demo voice" }));

    await waitFor(() => expect(audioSocket()).toBeTruthy());
    await waitFor(() => expect(input).toHaveValue("Show revenue by region"));
  });

  it("submits unedited voice provenance after final transcript review", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.click(screen.getByRole("button", { name: "Demo voice" }));

    await waitFor(() => expect(input).toHaveValue("Show revenue by region"));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(queryBodies).toHaveLength(1));
    expect(queryBodies[0]).toMatchObject({
      submitted_text: "Show revenue by region",
      input_modality: "voice",
      raw_transcript: "Show revenue by region",
      stt_confidence: 0.97,
      transcript_edited: false,
      parent_turn_id: null
    });
  });

  it("submits edited voice text without losing the raw transcript", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.click(screen.getByRole("button", { name: "Demo voice" }));

    await waitFor(() => expect(input).toHaveValue("Show revenue by region"));
    fireEvent.change(input, { target: { value: "Show net revenue by region" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(queryBodies).toHaveLength(1));
    expect(queryBodies[0]).toMatchObject({
      submitted_text: "Show net revenue by region",
      input_modality: "voice",
      raw_transcript: "Show revenue by region",
      stt_confidence: 0.97,
      transcript_edited: true
    });
  });

  it("does not inherit old voice metadata for a fresh text query", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.click(screen.getByRole("button", { name: "Demo voice" }));

    await waitFor(() => expect(input).toHaveValue("Show revenue by region"));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(queryBodies).toHaveLength(1));
    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });
    expect(await screen.findByText("Enterprise leads net revenue.")).toBeInTheDocument();
    expect(screen.getByText(/Chart data alternative:/)).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "Just enterprise customers" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await waitFor(() => expect(queryBodies).toHaveLength(2));
    expect(queryBodies[1]).toMatchObject({
      submitted_text: "Just enterprise customers",
      input_modality: "text",
      raw_transcript: null,
      stt_confidence: null,
      transcript_edited: false,
      parent_turn_id: "turn-1"
    });
  });

  it("ignores late results for an older turn while a follow-up is active", async () => {
    queryTurnIds = ["turn-a", "turn-b"];
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");

    fireEvent.change(input, { target: { value: "Show revenue by region" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(queryBodies).toHaveLength(1));
    await emitPipeline({ type: "result_ready", turn_id: "turn-a" });
    expect(await screen.findByText("Revenue by region result.")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "Just enterprise customers" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(queryBodies).toHaveLength(2));
    expect(queryBodies[1].parent_turn_id).toBe("turn-a");
    await waitFor(() => expect(screen.queryByText("Revenue by region result.")).not.toBeInTheDocument());

    await emitPipeline({ type: "result_ready", turn_id: "turn-a" });
    expect(screen.queryByText("Revenue by region result.")).not.toBeInTheDocument();

    await emitPipeline({ type: "result_ready", turn_id: "turn-b" });
    expect(await screen.findByText("Enterprise customer result.")).toBeInTheDocument();
    expect(screen.getByText("Just enterprise customers")).toBeInTheDocument();
    // ThreadHistory now uses Q-index labels
    expect(screen.getByText("Q1")).toBeInTheDocument();
    expect(screen.getByText("Show revenue by region")).toBeInTheDocument();
  });

  it("keeps a loaded result bound to its submitted question while editing a new draft", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");

    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });

    expect(await screen.findByText("Enterprise leads net revenue.")).toBeInTheDocument();
    expect(screen.getByText("Show net revenue by customer segment")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "Just enterprise customers" } });

    expect(screen.getByText("Show net revenue by customer segment")).toBeInTheDocument();
    expect(screen.queryByText("Just enterprise customers")).not.toBeInTheDocument();
  });

  it("ignores stale pipeline errors for older turns while a newer turn is active", async () => {
    queryTurnIds = ["turn-a", "turn-b"];
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");

    fireEvent.change(input, { target: { value: "Show revenue by region" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(queryBodies).toHaveLength(1));
    await emitPipeline({ type: "result_ready", turn_id: "turn-a" });
    expect(await screen.findByText("Revenue by region result.")).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "Just enterprise customers" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(queryBodies).toHaveLength(2));

    await emitPipeline({
      type: "pipeline_error",
      turn_id: "turn-a",
      code: "internal_error",
      message: "Old turn failed late."
    });
    expect(screen.queryByText("Old turn failed late.")).not.toBeInTheDocument();

    await emitPipeline({ type: "result_ready", turn_id: "turn-b" });
    await screen.findByText("Enterprise customer result.");
    expect(screen.getByText("Just enterprise customers")).toBeInTheDocument();
  });

  it("hides follow-up suggestions when the backend returns an empty list", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });

    expect(await screen.findByText("Enterprise leads net revenue.")).toBeInTheDocument();
    expect(screen.queryByText("Ask a follow-up")).not.toBeInTheDocument();
    expect(screen.queryByText("Show that by quarter")).not.toBeInTheDocument();
    expect(screen.queryByText("Compare this with last month")).not.toBeInTheDocument();
    expect(screen.queryByText("Break it down by customer segment")).not.toBeInTheDocument();
  });

  it("renders exact backend follow-up suggestions without local fallbacks", async () => {
    queryTurnIds = ["turn-suggestions"];
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-suggestions" });

    expect(await screen.findByText("Show enterprise only")).toBeInTheDocument();
    expect(screen.getByText("Compare with consumer")).toBeInTheDocument();
    expect(screen.queryByText("Show that by quarter")).not.toBeInTheDocument();
    expect(screen.queryByText("Compare this with last month")).not.toBeInTheDocument();
    expect(screen.queryByText("Break it down by customer segment")).not.toBeInTheDocument();
  });

  it("renders structured duplication warnings from the backend result", async () => {
    queryTurnIds = ["turn-duplication"];
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-duplication" });

    expect(
      await screen.findByText("The join returned many rows; duplicate source records may be inflating this result.")
    ).toBeInTheDocument();
  });

  it("clarification escape returns to edit flow without a result", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show revenue by region" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({
      type: "clarification_request",
      turn_id: "turn-1",
      question: "Which revenue metric did you mean?",
      options: ["Gross revenue", "Net revenue", "Recognized revenue"],
      timeout_seconds: 30
    });

    expect(await screen.findByText("Which revenue metric did you mean?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "None of these — let me rephrase" }));

    expect(await screen.findByText("Clarification escaped. Edit your question and submit again.")).toBeInTheDocument();
    expect(screen.queryByText("Enterprise leads net revenue.")).not.toBeInTheDocument();
  });

  it("shows a result after result_ready and handles duplicate feedback as a notice", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });

    expect(await screen.findByText("Enterprise leads net revenue.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Flag this result" }));
    expect(await screen.findByText("Feedback recorded for threshold tuning.")).toBeInTheDocument();
    expect(feedbackBodies[0]).toMatchObject({ rating: -1, turn_id: "turn-1" });
    fireEvent.click(screen.getByRole("button", { name: "Feedback recorded" }));
    expect(await screen.findByText("Feedback already recorded for this query.")).toBeInTheDocument();
  });

  it("submits thumbs-up feedback for a completed turn", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });

    expect(await screen.findByText("Enterprise leads net revenue.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark helpful" }));

    expect(await screen.findByText("Feedback recorded for threshold tuning.")).toBeInTheDocument();
    expect(feedbackBodies[0]).toMatchObject({ rating: 1, turn_id: "turn-1" });
  });

  it("renders four stable status cells including local fake mode", async () => {
    render(<HomePage />);
    expect(await screen.findByText("Local fake mode active. No external credentials are required.")).toBeInTheDocument();
    expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled();
  });

  // ------------------------------------------------------------------
  // Slice 1 — microphone permission shell (Gate 4)
  // ------------------------------------------------------------------

  it("mic denied: recordingState stays idle and text input remains enabled", async () => {
    // Stub getUserMedia to reject with NotAllowedError (permission denied).
    const deniedError = Object.assign(new Error("Permission denied"), {
      name: "NotAllowedError"
    });
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockRejectedValue(deniedError) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    // Wait for session to be ready before clicking.
    await waitFor(() => expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    // Notice must mention denial.
    await waitFor(() =>
      expect(screen.getByText(/denied|permission/i)).toBeInTheDocument()
    );
    // Text input must remain enabled (not blocked by pipelineInFlight).
    const input = screen.getByLabelText("Ask a data question");
    expect(input).not.toBeDisabled();
    // recordingState must stay idle (pipelineStage also shows 'idle'; both are expected).
    expect(screen.getByRole("button", { name: "Start recording" })).not.toBeDisabled();
    
    // Assert telemetry POST
    expect(telemetryCalls.length).toBeGreaterThan(0);
    const lastCall = JSON.parse(telemetryCalls.at(-1) ?? "{}");
    expect(lastCall.event).toBe("stt.mic.permission");
    expect(lastCall.outcome).toBe("denied");
  });

  it("mic granted: recordingState transitions to connecting", async () => {
    // Stub getUserMedia to resolve with a minimal fake stream.
    const fakeStream = { getTracks: () => [] };
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    await waitFor(() => expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    // After permission is granted the UI enters connecting, then recording.
    await waitFor(() => expect(screen.getByRole("button", { name: "Stop recording" })).toBeInTheDocument());
    
    // Assert telemetry POST
    expect(telemetryCalls.length).toBeGreaterThan(0);
    const lastCall = JSON.parse(telemetryCalls.at(-1) ?? "{}");
    expect(lastCall.event).toBe("stt.mic.permission");
    expect(lastCall.outcome).toBe("granted");
  });

  it("mic unavailable: shows a safe notice and keeps text input usable", async () => {
    // Remove mediaDevices entirely to simulate an insecure context or old browser.
    Object.defineProperty(navigator, "mediaDevices", {
      value: undefined,
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    await waitFor(() => expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    await waitFor(() =>
      expect(screen.getByText(/unavailable/i)).toBeInTheDocument()
    );
    const input = screen.getByLabelText("Ask a data question");
    expect(input).not.toBeDisabled();
  });

  it("fake voice still works after mic recording feature is added (regression guard)", async () => {
    // Restore working mediaDevices so fake voice path is isolated.
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.click(screen.getByRole("button", { name: "Demo voice" }));

    await waitFor(() => expect(audioSocket()).toBeTruthy());
    await waitFor(() => expect(input).toHaveValue("Show revenue by region"));
  });

  // ------------------------------------------------------------------
  // Slice 2 — PCM capture + binary streaming
  // ------------------------------------------------------------------

  it("'Start recording' opens audio WS and starts AudioWorklet when permission is granted", async () => {
    const fakeStream = { getTracks: () => [] };
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    await waitFor(() => expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    // Wait for the WS to be opened and AudioWorklet to start
    await waitFor(() => expect(audioSocket()).toBeTruthy());
    await waitFor(() => expect(MockAudioContext.instances.length).toBeGreaterThanOrEqual(1));
    expect(MockAudioWorkletNode.instances).toHaveLength(1);
    
    // Assert WS URL contains session and token
    const wsUrl = audioSocket()!.url;
    expect(wsUrl).toContain("session_id=session-1");
    expect(wsUrl).toContain("token=fake");
  });

  it("audio chunks are sent as binary frames over the WS", async () => {
    const fakeStream = { getTracks: () => [] };
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    await waitFor(() => expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    await waitFor(() => expect(audioSocket()).toBeTruthy());
    await waitFor(() => expect(MockAudioWorkletNode.instances).toHaveLength(1));
    
    const worklet = MockAudioWorkletNode.instances[0];
    const ws = audioSocket()!;
    ws.send = vi.fn(); // Mock send

    const testBuffer = new ArrayBuffer(3200);
    act(() => {
      worklet.port.onmessage?.({ data: testBuffer });
    });

    expect(ws.send).toHaveBeenCalledWith(testBuffer);
  });

  it("stop recording sends stop_recording JSON and transitions to idle after final transcript", async () => {
    const fakeStream = { getTracks: () => [] };
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    await waitFor(() => expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled());
    const input = screen.getByLabelText("Ask a data question");

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await waitFor(() => expect(audioSocket()).toBeTruthy());
    
    const ws = audioSocket()!;
    ws.send = vi.fn();

    const stopButton = await screen.findByRole("button", { name: "Stop recording" });
    fireEvent.click(stopButton);
    
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: "stop_recording" }));
    
    // Simulate final transcript
    act(() => {
      ws.emit({ type: "final_transcript", text: "Show revenue by region", confidence: 0.97, is_final: true });
    });

    await waitFor(() => expect(input).toHaveValue("Show revenue by region"));
    await waitFor(() => expect(screen.getByText("Transcript received. Review or edit before submitting.")).toBeInTheDocument());
  });

  it("WS error during recording shows notice and returns to idle", async () => {
    const fakeStream = { getTracks: () => [] };
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    await waitFor(() => expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await waitFor(() => expect(audioSocket()).toBeTruthy());
    
    const ws = audioSocket()!;
    act(() => {
      ws.onerror?.();
    });

    await waitFor(() => expect(screen.getByText(/unavailable|error/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Start recording" })).not.toBeDisabled();
  });

  it("prevents audio echo by routing through a zero-gain node before the destination", async () => {
    const fakeStream = { getTracks: () => [] };
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    await waitFor(() => expect(screen.getByLabelText("Ask a data question")).not.toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    await waitFor(() => expect(audioSocket()).toBeTruthy());
    await waitFor(() => expect(MockAudioWorkletNode.instances).toHaveLength(1));
    
    const context = MockAudioContext.instances[MockAudioContext.instances.length - 1];
    const worklet = MockAudioWorkletNode.instances[0];
    
    expect(context.createGain).toHaveBeenCalled();
    const mockGainNode = context.createGain.mock.results[0].value;
    
    expect(mockGainNode.gain.value).toBe(0);
    expect(worklet.connect).toHaveBeenCalledWith(mockGainNode);
    expect(mockGainNode.connect).toHaveBeenCalledWith(context.destination);
  });

  // ------------------------------------------------------------------
  // Data Visualizer (4.6)
  // ------------------------------------------------------------------

  it("renders a chart override dropdown and responds to selection changes", async () => {
    queryTurnIds = ["turn-1"];
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(queryBodies.length).toBeGreaterThan(0));
    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });

    expect(await screen.findByText("Enterprise leads net revenue.")).toBeInTheDocument();
    
    // The dropdown should be initialized with the LLM's recommended chart type ("bar")
    const dropdown = screen.getByLabelText("Chart Type") as HTMLSelectElement;
    expect(dropdown).toBeInTheDocument();
    expect(dropdown.value).toBe("bar");

    // Change the selection to "table"
    fireEvent.change(dropdown, { target: { value: "table" } });
    expect(dropdown.value).toBe("table");
  });

  it("generates a CSV Blob and triggers a download when Download CSV is clicked", async () => {
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn().mockReturnValue("blob:fake-url");
    URL.revokeObjectURL = vi.fn();
    queryTurnIds = ["turn-csv"];

    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-csv" });

    // Ensure the result is fully loaded by awaiting the tts text
    expect(await screen.findByText("Enterprise, Inc. leads net revenue.")).toBeInTheDocument();
    
    const downloadBtn = screen.getByRole("button", { name: "Download CSV" });
    fireEvent.click(downloadBtn);

    expect(URL.createObjectURL).toHaveBeenCalled();
    const blobArg = vi.mocked(URL.createObjectURL).mock.calls[0][0];
    expect(blobArg).toBeInstanceOf(Blob);
    if (!(blobArg instanceof Blob)) {
      throw new Error("CSV download did not create a Blob.");
    }
    
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.readAsText(blobArg);
    });
    
    // Assert actual newline boundaries
    const lines = text.split("\n");
    expect(lines.length).toBe(3); // Header + 2 data rows
    
    expect(lines[0]).toBe("customer_segment,total_net_revenue");
    expect(lines[1]).toBe('"Enterprise, Inc.",1240000');
    expect(lines[2]).toBe('"SMB",800000');

    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("renders a caveat warning when confidence tier is Medium", async () => {
    queryTurnIds = ["turn-medium"];
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(queryBodies.length).toBeGreaterThan(0));
    await emitPipeline({ type: "result_ready", turn_id: "turn-medium" });

    // Trust panel header shows the tier
    expect(await screen.findByText("Moderate confidence")).toBeInTheDocument();
    // Evidence-derived caveat shown (not hardcoded text)
    expect(
      screen.getByText(/Moderate confidence.*schema match was weaker/i)
    ).toBeInTheDocument();
  });

  // ── Phase 3 tests ──────────────────────────────────────────────────────────

  it("3.1: fake voice enters reviewing state — query is not submitted automatically", async () => {
    render(<HomePage />);
    await screen.findByLabelText("Ask a data question");
    fireEvent.click(screen.getByRole("button", { name: "Demo voice" }));

    // Audio socket delivers final transcript → should show review panel, not submit.
    await waitFor(() => expect(audioSocket()).toBeTruthy());
    // Final transcript triggers reviewing state
    await waitFor(() =>
      expect(screen.queryByLabelText("Editable transcript")).toBeInTheDocument()
    );
    // Query must NOT have been submitted automatically
    expect(queryBodies).toHaveLength(0);
    // Raw transcript is shown above the editor
    expect(screen.getByLabelText("Raw transcript")).toBeInTheDocument();
  });

  it("3.1: Ask VoxQuery in review panel sends the full voice contract", async () => {
    render(<HomePage />);
    await screen.findByLabelText("Ask a data question");
    fireEvent.click(screen.getByRole("button", { name: "Demo voice" }));

    await waitFor(() =>
      expect(screen.queryByLabelText("Editable transcript")).toBeInTheDocument()
    );

    fireEvent.click(screen.getByRole("button", { name: "Ask VoxQuery" }));
    await waitFor(() => expect(queryBodies).toHaveLength(1));
    expect(queryBodies[0]).toMatchObject({
      input_modality: "voice",
      raw_transcript: "Show revenue by region",
      stt_confidence: 0.97,
    });
  });

  it("3.1: editing in the review panel changes submitted text without losing raw transcript", async () => {
    render(<HomePage />);
    await screen.findByLabelText("Ask a data question");
    fireEvent.click(screen.getByRole("button", { name: "Demo voice" }));

    await waitFor(() =>
      expect(screen.queryByLabelText("Editable transcript")).toBeInTheDocument()
    );

    const editor = screen.getByLabelText("Editable transcript");
    fireEvent.change(editor, { target: { value: "Show net revenue by region" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask VoxQuery" }));

    await waitFor(() => expect(queryBodies).toHaveLength(1));
    expect(queryBodies[0]).toMatchObject({
      submitted_text: "Show net revenue by region",
      raw_transcript: "Show revenue by region",
      transcript_edited: true,
    });
  });

  it("3.4: prior turn is compressed and expandable in thread history", async () => {
    queryTurnIds = ["turn-a", "turn-b"];
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");

    // First turn
    fireEvent.change(input, { target: { value: "Show revenue by region" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" } ));
    await emitPipeline({ type: "result_ready", turn_id: "turn-a" });
    await screen.findByText("Revenue by region result.");

    // Second turn
    fireEvent.change(input, { target: { value: "Just enterprise customers" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-b" });
    await screen.findByText("Enterprise customer result.");

    // Prior turn is in the history and compressed (button label contains Q1 and the question)
    const expandBtn = screen.getByRole("button", { name: /Q1/i });
    expect(expandBtn).toHaveAttribute("aria-expanded", "false");

    // The prior turn tts_text should NOT be visible before expanding
    // (it's inside the collapsed AnimatePresence section)

    // Expanding reveals the SQL/result details
    fireEvent.click(expandBtn);
    expect(expandBtn).toHaveAttribute("aria-expanded", "true");

    // After expand, the prior turn metadata is visible (row count, chart type)
    await waitFor(() => {
      // The expanded entry renders metadata including row count
      const rowCountEl = screen.queryByText("1 rows");
      const barViewEl = screen.queryByText("bar view");
      expect(rowCountEl ?? barViewEl).toBeTruthy();
    });

    // Active result remains independent
    expect(screen.getByText("Enterprise customer result.")).toBeInTheDocument();
  });

  it("3.3: pipeline_error renders a failure surface with severity error", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show revenue" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));

    await emitPipeline({
      type: "pipeline_error",
      turn_id: "turn-1",
      code: "internal_error",
      message: "SQL generation failed after 2 attempts.",
    });

    // The message appears in both the dock status and the FailureNotice — at least one must be present.
    await waitFor(() => {
      const els = screen.getAllByText("SQL generation failed after 2 attempts.");
      expect(els.length).toBeGreaterThanOrEqual(1);
    });
  });
});

async function emitPipeline(payload: unknown) {
  await waitFor(() => expect(pipelineSocket()).toBeTruthy());
  act(() => {
    pipelineSocket()?.emit(payload);
  });
}

function pipelineSocket(): FakeWebSocket | undefined {
  return FakeWebSocket.instances.find((socket) => socket.url.includes("/ws/pipeline"));
}

function audioSocket(): FakeWebSocket | undefined {
  return FakeWebSocket.instances.find((socket) => socket.url.includes("/ws/audio"));
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}
