import type {
  ClarificationRequest,
  QueryAcceptedResponse,
  QueryRequest,
  ResultResponse,
  SessionCreateResponse
} from "./types";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const fakeToken = "fake";

export class ApiRequestError extends Error {
  status: number;
  code: string | null;

  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit, authToken?: string | null): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
      ...(init?.headers ?? {})
    }
  });
  if (!response.ok) {
    let message = `Request failed: ${response.status}`;
    let code: string | null = null;
    try {
      const payload = await response.json();
      message = payload?.error?.message ?? message;
      code = payload?.error?.code ?? null;
    } catch {
      // Keep the generic status message when a non-contract error body is returned.
    }
    throw new ApiRequestError(response.status, message, code);
  }
  return response.json() as Promise<T>;
}

export async function createSession(
  tenantId: string,
  authToken?: string | null
): Promise<SessionCreateResponse> {
  return request<SessionCreateResponse>("/api/session", {
    method: "POST",
    body: JSON.stringify({ tenant_id: tenantId })
  }, authToken);
}

export async function deleteSession(
  sessionId: string,
  authToken?: string | null
): Promise<void> {
  await request(`/api/session/${encodeURIComponent(sessionId)}`, {
    method: "DELETE"
  }, authToken);
}

export async function submitQuery(
  payload: QueryRequest,
  authToken?: string | null
): Promise<QueryAcceptedResponse> {
  return request<QueryAcceptedResponse>("/api/query", {
    method: "POST",
    body: JSON.stringify(payload)
  }, authToken);
}

export async function postClarification(
  payload: ClarificationRequest,
  authToken?: string | null
): Promise<void> {
  await request("/api/clarification", {
    method: "POST",
    body: JSON.stringify(payload)
  }, authToken);
}

export async function fetchResult(
  turnId: string,
  authToken?: string | null
): Promise<ResultResponse> {
  return request<ResultResponse>(`/api/result/${turnId}`, undefined, authToken);
}

export async function postFeedback(payload: {
  session_id: string;
  turn_id: string;
  rating: -1;
}, authToken?: string | null): Promise<void> {
  await request("/api/feedback", {
    method: "POST",
    body: JSON.stringify(payload)
  }, authToken);
}

export async function postTelemetry(
  payload: { event: string; outcome: string; session_id?: string },
  authToken?: string | null
): Promise<void> {
  await request("/api/telemetry", {
    method: "POST",
    body: JSON.stringify(payload)
  }, authToken);
}

export function pipelineSocketUrl(sessionId: string, authToken: string | null = fakeToken): string {
  return socketUrl(
    `/ws/pipeline?session_id=${encodeURIComponent(sessionId)}&token=${encodeURIComponent(authToken ?? "")}`
  );
}

export function audioSocketUrl(sessionId: string, authToken: string | null = fakeToken): string {
  return socketUrl(
    `/ws/audio?session_id=${encodeURIComponent(sessionId)}&token=${encodeURIComponent(authToken ?? "")}`
  );
}

export function ttsSocketUrl(sessionId: string, turnId: string, authToken: string | null = fakeToken): string {
  return socketUrl(
    `/ws/tts?session_id=${encodeURIComponent(sessionId)}&turn_id=${encodeURIComponent(turnId)}&token=${encodeURIComponent(authToken ?? "")}`
  );
}

function socketUrl(path: string): string {
  const url = new URL(apiUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = path.split("?")[0];
  url.search = path.includes("?") ? path.slice(path.indexOf("?")) : "";
  return url.toString();
}
