import { afterEach, describe, expect, it, vi } from "vitest";
import { createSession, pipelineSocketUrl, submitQuery, audioSocketUrl } from "./api";

describe("api token relay", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("adds bearer tokens to REST requests when provided", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      new Response(
        JSON.stringify({
          session_id: "session-1",
          conversation_id: "conversation-1",
          expires_at: "2026-07-01T00:00:00Z"
        }),
        { status: 201, headers: { "Content-Type": "application/json" } }
      )
    );
    vi.stubGlobal("fetch", fetchMock);

    await createSession("tenant-1", "clerk-token");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/session",
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: "Bearer clerk-token"
        })
      })
    );
  });

  it("keeps REST requests credential-free when no token is provided", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify({ turn_id: "turn-1", status: "processing" }), {
        status: 202,
        headers: { "Content-Type": "application/json" }
      })
    );
    vi.stubGlobal("fetch", fetchMock);

    await submitQuery({
      session_id: "session-1",
      parent_turn_id: null,
      submitted_text: "Show net revenue by customer segment",
      input_modality: "text",
      raw_transcript: null,
      stt_confidence: null,
      transcript_edited: false
    });

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.headers).not.toHaveProperty("Authorization");
  });

  it("relays encoded tokens through WebSocket query params", () => {
    const token = "header.payload+/signature=";

    expect(pipelineSocketUrl("session-1", token)).toContain(
      `token=${encodeURIComponent(token)}`
    );
    expect(audioSocketUrl("session-1", token)).toContain(`token=${encodeURIComponent(token)}`);
  });
});
