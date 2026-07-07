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
  from_cache: false
};

const mediumResult = {
  ...result,
  turn_id: "turn-medium",
  confidence_tier: "Medium",
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
  port = { onmessage: null as any };
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
  close = vi.fn().mockResolvedValue(undefined);
  suspend = vi.fn().mockResolvedValue(undefined);
  
  static instances: MockAudioContext[] = [];
  
  constructor() {
    MockAudioContext.instances.push(this);
  }
}

describe("HomePage", () => {
  let sessionCalls = 0;
  let feedbackCalls = 0;
  let telemetryCalls: any[] = [];

  beforeEach(() => {
    window.sessionStorage.clear();
    FakeWebSocket.instances = [];
    MockAudioContext.instances = [];
    MockAudioWorkletNode.instances = [];
    sessionCalls = 0;
    feedbackCalls = 0;
    telemetryCalls = [];
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    vi.stubGlobal("AudioContext", MockAudioContext);
    vi.stubGlobal("webkitAudioContext", MockAudioContext);
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
          return jsonResponse({ turn_id: "turn-1", status: "processing" }, 202);
        }
        if (url.endsWith("/api/clarification")) {
          return jsonResponse({ status: "received", turn_id: "turn-1" });
        }
        if (url.endsWith("/api/result/turn-1")) {
          return jsonResponse(result);
        }
        if (url.endsWith("/api/result/turn-medium")) {
          return jsonResponse(mediumResult);
        }
        if (url.endsWith("/api/feedback")) {
          feedbackCalls += 1;
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
          telemetryCalls.push(init?.body);
          return jsonResponse({ status: "recorded" });
        }
        return jsonResponse({}, 404);
      })
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
    expect(screen.getByText("Session active")).toBeInTheDocument();
  });

  it("keeps transcript editable and renders clarification from the pipeline event", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show revenue by region" } });
    expect(input).toHaveValue("Show revenue by region");

    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({
      type: "clarification_request",
      turn_id: "turn-1",
      question: "Which revenue metric did you mean?",
      options: ["Gross revenue", "Net revenue", "Recognized revenue"],
      timeout_seconds: 30
    });

    expect(await screen.findByText("Which revenue metric did you mean?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Net revenue" })).toBeInTheDocument();
    expect(screen.getByText("30s remaining")).toBeInTheDocument();

    await emitPipeline({
      type: "clarification_timeout_warning",
      turn_id: "turn-1",
      seconds_remaining: 10
    });
    expect(await screen.findByText("10s remaining")).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "Fake voice" }));

    await waitFor(() => expect(audioSocket()).toBeTruthy());
    await waitFor(() => expect(input).toHaveValue("Show revenue by region"));
    expect(await screen.findByText("Raw transcript: Show revenue by region")).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole("button", { name: "None of these - let me rephrase" }));

    expect(await screen.findByText("Clarification escaped. Edit your question and submit again.")).toBeInTheDocument();
    expect(screen.queryByText("Result")).not.toBeInTheDocument();
  });

  it("shows a result after result_ready and handles duplicate feedback as a notice", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });

    expect(await screen.findByText("Result")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Thumbs down" }));
    expect(await screen.findByText("Feedback recorded for threshold tuning.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Feedback recorded" }));
    expect(await screen.findByText("Feedback already recorded for this query.")).toBeInTheDocument();
  });

  it("renders four stable status cells including local fake mode", async () => {
    render(<HomePage />);
    expect(await screen.findByText("local fake mode")).toBeInTheDocument();
    expect(screen.getByText("Session active")).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByText("Session active")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    // Notice must mention denial.
    await waitFor(() =>
      expect(screen.getByText(/denied|permission/i)).toBeInTheDocument()
    );
    // Text input must remain enabled (not blocked by pipelineInFlight).
    const input = screen.getByLabelText("Ask a data question");
    expect(input).not.toBeDisabled();
    // recordingState must stay idle (pipelineStage also shows 'idle'; both are expected).
    expect(screen.getAllByText("idle").length).toBeGreaterThanOrEqual(1);
    
    // Assert telemetry POST
    expect(telemetryCalls.length).toBeGreaterThan(0);
    const lastCall = JSON.parse(telemetryCalls[telemetryCalls.length - 1]);
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
    await waitFor(() => expect(screen.getByText("Session active")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    // After permission is granted the UI enters connecting.
    await waitFor(() => expect(screen.getByText("connecting")).toBeInTheDocument());
    
    // Assert telemetry POST
    expect(telemetryCalls.length).toBeGreaterThan(0);
    const lastCall = JSON.parse(telemetryCalls[telemetryCalls.length - 1]);
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
    await waitFor(() => expect(screen.getByText("Session active")).toBeInTheDocument());

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
    fireEvent.click(screen.getByRole("button", { name: "Fake voice" }));

    await waitFor(() => expect(audioSocket()).toBeTruthy());
    await waitFor(() => expect(input).toHaveValue("Show revenue by region"));
    expect(
      await screen.findByText("Raw transcript: Show revenue by region")
    ).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByText("Session active")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    // Wait for the WS to be opened and AudioWorklet to start
    await waitFor(() => expect(audioSocket()).toBeTruthy());
    await waitFor(() => expect(MockAudioContext.instances).toHaveLength(1));
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
    await waitFor(() => expect(screen.getByText("Session active")).toBeInTheDocument());

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
    await waitFor(() => expect(screen.getByText("Session active")).toBeInTheDocument());
    const input = screen.getByLabelText("Ask a data question");

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await waitFor(() => expect(audioSocket()).toBeTruthy());
    
    const ws = audioSocket()!;
    ws.send = vi.fn();

    fireEvent.click(screen.getByRole("button", { name: "Stop recording" }));
    
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ type: "stop_recording" }));
    
    // Simulate final transcript
    act(() => {
      ws.emit({ type: "final_transcript", text: "Show revenue by region", confidence: 0.97, is_final: true });
    });

    await waitFor(() => expect(input).toHaveValue("Show revenue by region"));
    expect(screen.getAllByText("idle").length).toBeGreaterThanOrEqual(1);
  });

  it("WS error during recording shows notice and returns to idle", async () => {
    const fakeStream = { getTracks: () => [] };
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    await waitFor(() => expect(screen.getByText("Session active")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));
    await waitFor(() => expect(audioSocket()).toBeTruthy());
    
    const ws = audioSocket()!;
    act(() => {
      ws.onerror?.();
    });

    await waitFor(() => expect(screen.getByText(/unavailable|error/i)).toBeInTheDocument());
    expect(screen.getAllByText("idle").length).toBeGreaterThanOrEqual(1);
  });

  it("prevents audio echo by routing through a zero-gain node before the destination", async () => {
    const fakeStream = { getTracks: () => [] };
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockResolvedValue(fakeStream) },
      writable: true,
      configurable: true
    });

    render(<HomePage />);
    await waitFor(() => expect(screen.getByText("Session active")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Start recording" }));

    await waitFor(() => expect(audioSocket()).toBeTruthy());
    await waitFor(() => expect(MockAudioWorkletNode.instances).toHaveLength(1));
    
    const context = MockAudioContext.instances[0];
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
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });

    expect(await screen.findByText("Result")).toBeInTheDocument();
    
    // The dropdown should be initialized with the LLM's recommended chart type ("bar")
    const dropdown = screen.getByLabelText("Chart Type:") as HTMLSelectElement;
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

    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-1" });

    expect(await screen.findByText("Result")).toBeInTheDocument();
    
    const downloadBtn = screen.getByRole("button", { name: "Download CSV" });
    fireEvent.click(downloadBtn);

    expect(URL.createObjectURL).toHaveBeenCalled();
    // Verify it created a Blob with the expected CSV format
    const blobArg = (URL.createObjectURL as any).mock.calls[0][0];
    expect(blobArg).toBeInstanceOf(Blob);
    
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.readAsText(blobArg);
    });
    
    expect(text).toContain("customer_segment,total_net_revenue");
    expect(text).toContain('"Enterprise",1240000');

    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
  });

  it("renders a caveat warning when confidence tier is Medium", async () => {
    render(<HomePage />);
    const input = await screen.findByLabelText("Ask a data question");
    fireEvent.change(input, { target: { value: "Show net revenue by customer segment" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await emitPipeline({ type: "result_ready", turn_id: "turn-medium" });

    expect(await screen.findByText("Medium")).toBeInTheDocument();
    expect(
      screen.getByText("I'm moderately confident — the query joined tables I'm less familiar with. Review the SQL before actioning.")
    ).toBeInTheDocument();
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
