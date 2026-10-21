import type { CaseRecord, Scenario, TraceEvent } from "./types";

// Same origin when served by the API at /console; set VITE_API_BASE for a separate host (Amplify).
const BASE: string = import.meta.env.VITE_API_BASE ?? "";
const KEY: string | undefined = import.meta.env.VITE_API_KEY;

function url(path: string): string {
  if (!KEY) return `${BASE}${path}`;
  return `${BASE}${path}${path.includes("?") ? "&" : "?"}api_key=${encodeURIComponent(KEY)}`;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url(path), {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => call<{ status: string; demo: boolean; queued: number }>("/health"),
  cases: () => call<CaseRecord[]>("/cases"),
  getCase: (id: string) => call<CaseRecord | { case_id: string; status: "NEW" }>(`/cases/${id}`),
  scenarios: () => call<Scenario[]>("/demo/scenarios"),
  runScenario: (id: string) => call<{ case_id: string }>(`/demo/scenarios/${id}/run`, { method: "POST" }),
  reset: () => call<unknown>("/demo/reset", { method: "POST" }),
  request: (utterance: string, user: string) =>
    call<{ case_id: string }>("/requests", { method: "POST", body: JSON.stringify({ utterance, user }) }),
  approve: (id: string, approver: string) =>
    call<CaseRecord>(`/cases/${id}/approve`, { method: "POST", body: JSON.stringify({ approver }) }),
  reject: (id: string, approver: string, reason: string) =>
    call<CaseRecord>(`/cases/${id}/reject`, { method: "POST", body: JSON.stringify({ approver, reason }) }),
  recordings: () => call<string[]>("/recordings"),
};

/** Subscribe to a trace stream. Closes itself after the final DONE so EventSource does not
 * reconnect to a finished case. Returns an unsubscribe function. */
export function streamEvents(path: string, onEvent: (e: TraceEvent) => void, isFinal: (e: TraceEvent) => boolean,
                             onClose?: () => void, closeOnEnd = false): () => void {
  const source = new EventSource(url(path));
  if (closeOnEnd) {
    // Recordings end when the file does; reconnecting would replay them from the start.
    source.onerror = () => {
      source.close();
      onClose?.();
    };
  }
  const handler = (msg: MessageEvent) => {
    const event = JSON.parse(msg.data) as TraceEvent;
    onEvent(event);
    if (isFinal(event)) {
      source.close();
      onClose?.();
    }
  };
  for (const kind of ["PLAN", "TOOL_CALL", "TOOL_RESULT", "REASONING", "POLICY", "APPROVAL", "ACTION", "ERROR",
    "DONE"]) {
    source.addEventListener(kind, handler as EventListener);
  }
  return () => source.close();
}
