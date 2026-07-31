import type {
  ClarificationRequest,
  ExecutiveBriefingData,
  MemoryGraphData,
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

export async function fetchAuthenticatedBlob(
  path: string,
  apiUrlOverride?: string,
  authToken?: string | null
): Promise<Blob> {
  const targetUrl = apiUrlOverride || apiUrl;
  const response = await fetch(`${targetUrl}${path}`, {
    headers: authToken ? { Authorization: `Bearer ${authToken}` } : {}
  });
  if (!response.ok) {
    throw new ApiRequestError(response.status, `Request failed with status ${response.status}`, null);
  }
  return response.blob();
}

async function request<T>(path: string, init?: RequestInit, authToken?: string | null): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        ...(init?.headers ?? {})
      }
    });
  } catch (error) {
    // This catches network-level errors like offline, DNS resolution failure, or CORS rejection
    throw new ApiRequestError(0, "A network error occurred. Please check your internet connection and ensure the server is reachable.", "network_error");
  }

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    let code: string | null = null;
    
    // Provide sensible human-readable defaults for common HTTP error codes
    if (response.status >= 500 && response.status < 600) {
      message = "The server is currently unreachable or experiencing issues. Please try again later.";
    } else if (response.status === 404) {
      message = "The requested resource could not be found.";
    } else if (response.status === 401 || response.status === 403) {
      message = "You do not have permission to perform this action. Please check your login status.";
    } else if (response.status === 429) {
      message = "Too many requests. Please wait a moment before trying again.";
    }

    try {
      const payload = await response.json();
      message = payload?.error?.message ?? message;
      code = payload?.error?.code ?? null;
    } catch {
      // Keep the fallback message when a non-contract error body (e.g. raw HTML from a 502) is returned.
    }
    console.error(`[API Request Error] path=${path} status=${response.status} code=${code} message="${message}"`);
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
    body: JSON.stringify({})
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
  rating: -1 | 1;
}, authToken?: string | null): Promise<void> {
  await request("/api/feedback", {
    method: "POST",
    body: JSON.stringify(payload)
  }, authToken);
}

export async function fetchAdminFeedback(
  limit: number = 50,
  offset: number = 0,
  authToken?: string | null
): Promise<{ data: any[] }> {
  return request<{ data: any[] }>(`/api/admin/feedback?limit=${limit}&offset=${offset}`, undefined, authToken);
}

export async function fetchAdminGlossary(
  authToken?: string | null
): Promise<{ data: any[] }> {
  return request<{ data: any[] }>("/api/admin/glossary", undefined, authToken);
}

export async function postAdminGlossary(
  payload: { tenant_id: string; metric_synonyms: Record<string, string>; table_synonyms: Record<string, string> },
  authToken?: string | null
): Promise<void> {
  await request("/api/admin/glossary", {
    method: "POST",
    body: JSON.stringify(payload)
  }, authToken);
}

export async function fetchAdminWorkspaces(authToken?: string | null): Promise<{ data: any[] }> {
  return request<{ data: any[] }>("/api/admin/workspaces", undefined, authToken);
}

export async function fetchAdminStats(authToken?: string | null): Promise<any> {
  return request<any>("/api/admin/stats", undefined, authToken);
}

export async function fetchGlossaryPreview(
  tenantId: string, text: string, authToken?: string | null
): Promise<{ original: string; rewritten: string; detected_metrics: string[]; detected_tables: string[] }> {
  return request(`/api/admin/glossary/preview?tenant_id=${encodeURIComponent(tenantId)}&text=${encodeURIComponent(text)}`, undefined, authToken);
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

export async function fetchWorkspaceWidgets(authToken?: string | null): Promise<any[]> {
  return request<any[]>("/api/workspace/widgets", { method: "GET" }, authToken);
}

export async function pinWorkspaceWidget(
  payload: { turn_id: string; title: string; layout_x?: number; layout_y?: number; layout_w?: number; layout_h?: number },
  authToken?: string | null
) {
  return request<any>("/api/workspace/widgets", { method: "POST", body: JSON.stringify(payload) }, authToken);
}

export async function deleteWorkspaceWidget(widgetId: string, authToken?: string | null): Promise<any> {
  return request<any>(`/api/workspace/widgets/${widgetId}`, { method: "DELETE" }, authToken);
}

export async function updateWorkspaceWidgetLayout(
  widgetId: string,
  layout: { x: number; y: number; w: number; h: number },
  authToken?: string | null
): Promise<any> {
  return request<any>(
    `/api/workspace/widgets/${widgetId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        layout_x: layout.x,
        layout_y: layout.y,
        layout_w: layout.w,
        layout_h: layout.h,
      }),
    },
    authToken
  );
}

export function pipelineSocketUrl(sessionId: string): string {
  return socketUrl(
    `/ws/pipeline?session_id=${encodeURIComponent(sessionId)}`
  );
}

export function audioSocketUrl(sessionId: string): string {
  return socketUrl(
    `/ws/audio?session_id=${encodeURIComponent(sessionId)}`
  );
}

export function ttsSocketUrl(sessionId: string, turnId: string): string {
  return socketUrl(
    `/ws/tts?session_id=${encodeURIComponent(sessionId)}&turn_id=${encodeURIComponent(turnId)}`
  );
}

export async function fetchBriefing(authToken?: string | null): Promise<ExecutiveBriefingData> {
  return request<ExecutiveBriefingData>("/api/briefing", {}, authToken);
}

export async function fetchMemoryGraph(
  sessionId: string,
  authToken?: string | null
): Promise<MemoryGraphData> {
  return request<MemoryGraphData>(`/api/memory-graph/${encodeURIComponent(sessionId)}`, {}, authToken);
}

export async function fetchDrilldown(
  turnId: string,
  authToken?: string | null
): Promise<Record<string, any>[]> {
  return request<Record<string, any>[]>(`/api/drilldown/${encodeURIComponent(turnId)}`, {}, authToken);
}

export async function fetchVersion(authToken?: string | null): Promise<{ git_sha: string; version: string }> {
  return request<{ git_sha: string; version: string }>("/api/version", {}, authToken);
}

function socketUrl(path: string): string {
  const url = new URL(apiUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = path.split("?")[0];
  url.search = path.includes("?") ? path.slice(path.indexOf("?")) : "";
  return url.toString();
}
