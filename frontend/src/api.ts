/** REST client over relative /api paths (plan §7.4: fetch only, no axios, no hard-coded host). */

import type {
  ChatResponse,
  ConfigResponse,
  Document,
  DocumentListResponse,
  GraphSnapshot,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail?: unknown }).detail;
      if (typeof detail === "string" && detail) return detail;
    }
  } catch {
    // Body was not JSON; fall through to the status text.
  }
  return response.statusText || `request failed with status ${response.status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function getConfig(): Promise<ConfigResponse> {
  return request<ConfigResponse>("/config");
}

export function listDocuments(): Promise<DocumentListResponse> {
  return request<DocumentListResponse>("/documents");
}

export function uploadDocument(file: File): Promise<Document> {
  const body = new FormData();
  body.append("file", file);
  return request<Document>("/documents", { method: "POST", body });
}

export function deleteDocument(id: string): Promise<void> {
  return request<void>(`/documents/${id}`, { method: "DELETE" });
}

export function getGraph(): Promise<GraphSnapshot> {
  return request<GraphSnapshot>("/graph");
}

export function sendChat(message: string): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}
