import type {
  ClarificationRequest,
  ExecutiveBriefingData,
  MemoryGraphData,
  QueryAcceptedResponse,
  QueryRequest,
  ResultResponse,
  PinnedAnalysis,
  SessionCreateResponse,
  QueryHistoryPage,
  QueryHistoryDetail,
  TenantAnalytics,
  SystemHealthResponse,
  MemorySummaryResponse,
  ShareLinkCreateRequest,
  ShareLinkCreateResponse,
  SharedResultResponse,
  WorkspaceDetail
} from "./types";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const fakeToken = "fake";
type TokenRefresher = (options?: { skipCache?: boolean }) => Promise<string | null>;
let tokenRefresher: TokenRefresher | null = null;

export function setAuthTokenRefresher(refresher: TokenRefresher | null): void {
  tokenRefresher = refresher;
}

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
  const buildHeaders = (token?: string | null) => {
    const headers = new Headers();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return headers;
  };
  let response = await fetch(`${targetUrl}${path}`, { headers: buildHeaders(authToken) });
  if (response.status === 401 && authToken && tokenRefresher) {
    const refreshedToken = await tokenRefresher({ skipCache: true });
    if (refreshedToken && refreshedToken !== authToken) {
      response = await fetch(`${targetUrl}${path}`, { headers: buildHeaders(refreshedToken) });
    }
  }
  if (!response.ok) {
    throw new ApiRequestError(response.status, `Request failed with status ${response.status}`, null);
  }
  return response.blob();
}

async function request<T>(path: string, init?: RequestInit, authToken?: string | null): Promise<T> {
  const send = async (token?: string | null) => {
    const headers: Record<string, string> = {};

    // Merge any caller-supplied headers into the plain object
    if (init?.headers) {
      if (init.headers instanceof Headers) {
        init.headers.forEach((value, key) => { headers[key] = value; });
      } else if (Array.isArray(init.headers)) {
        for (const [k, v] of init.headers) { headers[k] = v; }
      } else {
        Object.assign(headers, init.headers as Record<string, string>);
      }
    }

    // Default Content-Type (case-insensitive check)
    if (!Object.keys(headers).some((k) => k.toLowerCase() === "content-type")) {
      headers["Content-Type"] = "application/json";
    }

    // Bearer token (only when present)
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    return fetch(`${apiUrl}${path}`, {
      ...init,
      headers
    });
  };
  let response: Response;
  try {
    response = await send(authToken);
    if (response.status === 401 && authToken && tokenRefresher) {
      const refreshedToken = await tokenRefresher({ skipCache: true });
      if (refreshedToken && refreshedToken !== authToken) {
        response = await send(refreshedToken);
      }
    }
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

export async function fetchWorkspaceWidgets(authToken?: string | null): Promise<PinnedAnalysis[]> {
  return request<PinnedAnalysis[]>("/api/workspace/widgets", { method: "GET" }, authToken);
}

export async function pinWorkspaceWidget(
  payload: {
    turn_id: string; title: string; note?: string;
    headline_value?: number | null; headline_label?: string | null;
    layout_x?: number; layout_y?: number; layout_w?: number; layout_h?: number;
  },
  authToken?: string | null
): Promise<PinnedAnalysis> {
  return request<PinnedAnalysis>("/api/workspace/widgets", { method: "POST", body: JSON.stringify(payload) }, authToken);
}

export async function startCheckNow(
  widgetId: string,
  authToken?: string | null
): Promise<{ turn_id: string; status: "processing" }> {
  return request(`/api/workspace/widgets/${widgetId}/check-now`, { method: "POST" }, authToken);
}

export async function updateWorkspaceWidgetNote(
  widgetId: string,
  note: string | null,
  authToken?: string | null
): Promise<any> {
  return request<any>(
    `/api/workspace/widgets/${widgetId}/note`,
    { method: "PATCH", body: JSON.stringify({ note }) },
    authToken
  );
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

export async function fetchPriorSessionSummary(
  currentSessionId?: string,
  authToken?: string | null
): Promise<{ questions: string[] }> {
  const path = currentSessionId
    ? `/api/memory/prior-session-summary?current_session_id=${encodeURIComponent(currentSessionId)}`
    : "/api/memory/prior-session-summary";
  return request<{ questions: string[] }>(path, {}, authToken);
}

export async function fetchAdminHistory(
  page: number = 1,
  pageSize: number = 50,
  search: string = "",
  qualityFlag: string = "",
  confidenceTier: string = "",
  completedOnly: boolean = false,
  authToken?: string | null
): Promise<QueryHistoryPage> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (search) params.append("search", search);
  if (qualityFlag) params.append("quality_flag", qualityFlag);
  if (confidenceTier) params.append("confidence_tier", confidenceTier);
  if (completedOnly) params.append("completed_only", "true");
  return request<QueryHistoryPage>(`/api/admin/history?${params.toString()}`, {}, authToken);
}

export async function fetchAdminHistoryDetail(
  turnId: string,
  authToken?: string | null
): Promise<QueryHistoryDetail> {
  return request<QueryHistoryDetail>(`/api/admin/history/${encodeURIComponent(turnId)}`, {}, authToken);
}

export async function fetchAdminAnalytics(
  days: number = 30,
  authToken?: string | null
): Promise<TenantAnalytics> {
  return request<TenantAnalytics>(`/api/admin/analytics?days=${days}`, {}, authToken);
}

export async function fetchAdminHealth(
  authToken?: string | null
): Promise<SystemHealthResponse> {
  return request<SystemHealthResponse>("/api/admin/health", {}, authToken);
}

export async function fetchMemorySummary(
  authToken?: string | null
): Promise<MemorySummaryResponse> {
  return request<MemorySummaryResponse>("/api/memory/summary", {}, authToken);
}

export async function createShareLink(
  payload: ShareLinkCreateRequest,
  authToken?: string | null
): Promise<ShareLinkCreateResponse> {
  return request<ShareLinkCreateResponse>("/api/share/create", {
    method: "POST",
    body: JSON.stringify(payload)
  }, authToken);
}

export async function fetchSharedResult(
  token: string
): Promise<SharedResultResponse> {
  return request<SharedResultResponse>(`/api/share/${encodeURIComponent(token)}`, {});
}

function socketUrl(path: string): string {
  const url = new URL(apiUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = path.split("?")[0];
  url.search = path.includes("?") ? path.slice(path.indexOf("?")) : "";
  return url.toString();
}
