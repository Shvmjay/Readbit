// Minimal typed fetch client. All requests are same-origin (proxied to the API by Next.js rewrites), carry the
// session cookie automatically, and send the CSRF header required for state-changing requests.
import type { ApiErrorBody } from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  retryable: boolean;
  details?: Record<string, unknown>;

  constructor(status: number, body: ApiErrorBody | undefined, fallback: string) {
    super(body?.message || fallback);
    this.status = status;
    this.code = body?.code || "network_failure";
    this.retryable = body?.retryable ?? status >= 500;
    this.details = body?.details;
  }
}

type Json = Record<string, unknown> | unknown[] | null;

async function request<T>(method: string, path: string, body?: Json | FormData, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "X-Readbit-CSRF": "1" };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, { method, headers, body: payload, credentials: "same-origin", ...init });
  } catch {
    throw new ApiError(0, { code: "network_failure", message: "You appear to be offline. Check your connection and try again.", retryable: true }, "Network error");
  }
  const text = await res.text();
  let data: unknown = undefined;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const errBody = (data as { error?: ApiErrorBody } | undefined)?.error;
    throw new ApiError(res.status, errBody, `Request failed (${res.status})`);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: Json) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: Json) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: Json) => request<T>("PATCH", path, body ?? {}),
  del: <T>(path: string, body?: Json) => request<T>("DELETE", path, body),
  upload: <T>(path: string, form: FormData) => request<T>("POST", path, form),
  text: async (path: string) => {
    const res = await fetch(`/api/v1${path}`, { credentials: "same-origin" });
    if (!res.ok) throw new ApiError(res.status, undefined, "Download failed");
    return res.text();
  },
};

/** Upload with progress events (fetch has no upload progress). */
export function uploadWithProgress<T>(file: File, onProgress: (pct: number) => void): Promise<{ status: number; data: T }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/v1/books/upload");
    xhr.setRequestHeader("X-Readbit-CSRF", "1");
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      let data: unknown = undefined;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve({ status: xhr.status, data: data as T });
      else reject(new ApiError(xhr.status, (data as { error?: ApiErrorBody })?.error, "Upload failed"));
    };
    xhr.onerror = () => reject(new ApiError(0, { code: "network_failure", message: "The upload was interrupted. Check your connection and retry.", retryable: true }, "Network"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export function track(name: string, properties: Record<string, string | number | boolean> = {}, bookId?: string) {
  // Fire-and-forget, content-free analytics. Failures never affect the UI.
  request("POST", "/events", { name, properties, book_id: bookId ?? null }).catch(() => undefined);
}
