import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  deleteDocument,
  getConfig,
  getGraph,
  listDocuments,
  sendChat,
  uploadDocument,
} from "../src/api";

function mockFetchOnce(status: number, body: unknown): void {
  const ok = status >= 200 && status < 300;
  const response = {
    ok,
    status,
    statusText: "status",
    json: () => Promise.resolve(body),
  } as unknown as Response;
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("api", () => {
  it("getConfig requests the relative /api/config path", async () => {
    mockFetchOnce(200, { max_documents: 5, max_file_size_mb: 1, allowed_extensions: ["pdf"] });
    const result = await getConfig();
    expect(fetch).toHaveBeenCalledWith("/api/config", undefined);
    expect(result.max_documents).toBe(5);
  });

  it("listDocuments requests /api/documents", async () => {
    mockFetchOnce(200, { documents: [] });
    await listDocuments();
    expect(fetch).toHaveBeenCalledWith("/api/documents", undefined);
  });

  it("uploadDocument posts multipart form data to /api/documents", async () => {
    mockFetchOnce(201, { id: "d1" });
    const file = new File(["hello"], "a.pdf", { type: "application/pdf" });
    await uploadDocument(file);
    const call = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0];
    expect(call[0]).toBe("/api/documents");
    expect((call[1] as RequestInit).method).toBe("POST");
    expect((call[1] as RequestInit).body).toBeInstanceOf(FormData);
  });

  it("deleteDocument sends DELETE to /api/documents/{id} and resolves with nothing for 204", async () => {
    mockFetchOnce(204, undefined);
    const result = await deleteDocument("d1");
    expect(fetch).toHaveBeenCalledWith("/api/documents/d1", { method: "DELETE" });
    expect(result).toBeUndefined();
  });

  it("getGraph requests /api/graph", async () => {
    mockFetchOnce(200, { nodes: [], edges: [] });
    await getGraph();
    expect(fetch).toHaveBeenCalledWith("/api/graph", undefined);
  });

  it("sendChat posts the message as JSON to /api/chat", async () => {
    mockFetchOnce(202, { chat_id: "c1" });
    const result = await sendChat("hello?");
    const call = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0];
    expect(call[0]).toBe("/api/chat");
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({ message: "hello?" });
    expect(result.chat_id).toBe("c1");
  });

  it("maps a non-2xx response to an ApiError carrying the server's detail", async () => {
    mockFetchOnce(409, { detail: "The maximum number of documents has been reached." });
    await expect(listDocuments()).rejects.toMatchObject({
      status: 409,
      message: "The maximum number of documents has been reached.",
    });
  });

  it("falls back to the status text when the error body is not JSON", async () => {
    const response = {
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: () => Promise.reject(new Error("not json")),
    } as unknown as Response;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    await expect(getConfig()).rejects.toBeInstanceOf(ApiError);
  });
});
