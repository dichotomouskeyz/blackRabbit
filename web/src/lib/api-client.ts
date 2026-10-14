// Typed API client over the api/ HTTP contract (frontend-shell INV-001/002a/004/006/008a).
// Never sends sponsor_id/site_id (INV-004); handles every status + null fields (BND-001).

export type CapabilityStatus = "implemented" | "scaffolded" | "blocked";

export interface CapabilityRow {
  capability: string;
  endpoint: string;
  status: CapabilityStatus;
  blocked_reason: string | null;
  gate: string | null;
}

// The structured 409 body shape from api/capabilities.py:
// {error, capability, status, blocked_reason, gate}
export interface CapabilityUnavailableBody {
  error: "capability_unavailable";
  capability: string;
  status: CapabilityStatus;
  blocked_reason: string | null;
  gate: string | null;
}

export interface ApiOk<T> {
  ok: true;
  status: number;
  data: T;
}

export interface ApiErr {
  ok: false;
  status: number;
  // Structured server body when present (409/422), else a synthetic shape.
  body: unknown;
}

export type ApiResult<T> = ApiOk<T> | ApiErr;

export interface SessionSummary {
  id: string;
  status: string;
  compound: string | null;
  started_at: string | null;
  closed_at: string | null;
  created_at: string | null;
}

// Optional GET /sessions filters (session-query SQ-001). participant_id is a
// filter only; the response never includes it (SQ-004).
export interface SessionFilters {
  session_id?: string;
  participant_id?: string;
  status?: string;
  compound?: string;
  created_from?: string;
  created_before?: string;
  limit?: number;
}

const SESSION_FILTER_KEYS: (keyof SessionFilters)[] = [
  "session_id",
  "participant_id",
  "status",
  "compound",
  "created_from",
  "created_before",
  "limit",
];

// "?a=1&b=2" for the filters that are set, or "" when none are (SQ-005).
export function sessionFilterQuery(filters: SessionFilters | undefined): string {
  if (!filters) return "";
  const params = new URLSearchParams();
  for (const key of SESSION_FILTER_KEYS) {
    const value = filters[key];
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text !== "") params.set(key, text);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

// A pluggable transport so tests can stub the network. Defaults to fetch.
export type Transport = (
  path: string,
  init?: RequestInit,
) => Promise<Response>;

export interface ApiClient {
  getCapabilities(): Promise<ApiResult<CapabilityRow[]>>;
  getHealth(): Promise<ApiResult<{ status: string; version: string; contract_version: string }>>;
  listSessions(filters?: SessionFilters): Promise<ApiResult<{ sessions: SessionSummary[] }>>;
  getSessionStatus(sessionId: string): Promise<ApiResult<unknown>>;
  getVocab(): Promise<ApiResult<{ compounds: string[]; dose_units: string[] }>>;
  voidSession(
    sessionId: string,
    reason: string,
  ): Promise<ApiResult<{ session_id: string; status: string; voided_at: string }>>;
  createSession(fields: Record<string, unknown>): Promise<ApiResult<{ session_id: string }>>;
  // Generic call used by the dispatcher for gated tools — hits the fixed endpoint.
  call(method: string, path: string, body?: unknown): Promise<ApiResult<unknown>>;
}

// Tenancy is injected server-side (operator-ui INV-001). The client/route must
// never forward these keys even if a caller mistakenly supplies them (INV-004).
const TENANCY_KEYS = ["sponsor_id", "site_id"];

// The create_session allow-list mirrors the operator-ui contract; tenancy is
// excluded by construction so no outbound body can carry it (INV-004).
// Field names match api/app.py CreateSessionRequest.
const CREATE_SESSION_ALLOW_LIST = [
  "compound",
  "capture_source",
  "participant_id",
  "compound_dose",
  "compound_dose_unit",
  "protocol_arm",
  "room_id",
  "eeg_sensor_form",
  "eeg_electrode_system",
  "eeg_electrode_type",
  "hrv_electrode_placement",
  "hrv_electrode_type",
  "eda_electrode_placement",
  "eda_electrode_type",
  "eda_skin_prep",
];

function stripTenancy(fields: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fields)) {
    if (TENANCY_KEYS.includes(k)) continue;
    out[k] = v;
  }
  return out;
}

function pickAllowList(
  fields: Record<string, unknown>,
  allow: string[],
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of allow) {
    if (key in fields && fields[key] !== undefined) out[key] = fields[key];
  }
  return out;
}

async function readBody(res: Response): Promise<unknown> {
  const ct = res.headers.get("content-type") ?? "";
  const text = await res.text();
  if (text.length === 0) return {};
  try {
    return JSON.parse(text);
  } catch {
    // JSON content-type that won't parse → {}; anything else keeps the raw text.
    return ct.includes("application/json") ? {} : { raw: text };
  }
}

export function createApiClient(opts?: { transport?: Transport; baseUrl?: string }): ApiClient {
  const transport: Transport = opts?.transport ?? ((path, init) => fetch(path, init));
  const baseUrl = opts?.baseUrl ?? "";

  function url(path: string): string {
    if (!baseUrl) return path;
    return `${baseUrl.replace(/\/$/, "")}${path}`;
  }

  // Core request that never throws on a non-2xx; resolves to a structured
  // ApiResult and fails closed on transport errors / unknown shapes (BND-001).
  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<ApiResult<T>> {
    const init: RequestInit = { method: method.toUpperCase() };
    if (body !== undefined && method.toUpperCase() !== "GET") {
      init.body = JSON.stringify(body);
      init.headers = { "content-type": "application/json" };
    }
    let res: Response;
    try {
      res = await transport(url(path), init);
    } catch {
      // Transport-level failure (unreachable) → fail closed as a synthetic 503.
      return { ok: false, status: 503, body: { error: "backend_unavailable" } };
    }
    const parsed = await readBody(res);
    if (res.ok) {
      return { ok: true, status: res.status, data: parsed as T };
    }
    return { ok: false, status: res.status, body: parsed };
  }

  return {
    async getCapabilities(): Promise<ApiResult<CapabilityRow[]>> {
      const res = await request<{ capabilities?: CapabilityRow[] } | CapabilityRow[]>(
        "GET",
        "/capabilities",
      );
      if (!res.ok) return res;
      const data = res.data as { capabilities?: CapabilityRow[] } | CapabilityRow[];
      const rows = Array.isArray(data) ? data : (data.capabilities ?? []);
      return { ok: true, status: res.status, data: rows };
    },

    getHealth() {
      return request<{ status: string; version: string; contract_version: string }>(
        "GET",
        "/health",
      );
    },

    listSessions(filters?: SessionFilters) {
      return request<{ sessions: SessionSummary[] }>("GET", `/sessions${sessionFilterQuery(filters)}`);
    },

    getSessionStatus(sessionId: string) {
      return request<unknown>("GET", `/sessions/${sessionId}/status`);
    },

    voidSession(sessionId: string, reason: string) {
      return request<{ session_id: string; status: string; voided_at: string }>(
        "POST",
        `/sessions/${encodeURIComponent(sessionId)}/void`,
        { reason },
      );
    },

    getVocab() {
      return request<{ compounds: string[]; dose_units: string[] }>("GET", "/vocab");
    },

    createSession(fields: Record<string, unknown>) {
      // Strip tenancy then keep only the allow-list fields (INV-004 / INV-003).
      const body = pickAllowList(stripTenancy(fields), CREATE_SESSION_ALLOW_LIST);
      return request<{ session_id: string }>("POST", "/sessions", body);
    },

    call(method: string, path: string, body?: unknown) {
      const safeBody =
        body && typeof body === "object"
          ? stripTenancy(body as Record<string, unknown>)
          : body;
      return request<unknown>(method, path, safeBody);
    },
  };
}
