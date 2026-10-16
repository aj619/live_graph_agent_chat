import { describe, expect, it } from "vitest";
import { initialState, reducer } from "../src/state";
import type { Document } from "../src/types";

const doc: Document = {
  id: "d1",
  filename: "a.pdf",
  status: "processing",
  error: null,
  chunks_total: null,
  chunks_done: 0,
  created_at: "2026-01-01T00:00:00Z",
};

describe("reducer: documents", () => {
  it("loads documents", () => {
    const state = reducer(initialState, { type: "documents/loaded", documents: [doc] });
    expect(state.documents).toEqual([doc]);
  });

  it("adds a document", () => {
    const state = reducer(initialState, { type: "documents/added", document: doc });
    expect(state.documents).toEqual([doc]);
  });

  it("removes a document", () => {
    const loaded = reducer(initialState, { type: "documents/loaded", documents: [doc] });
    const state = reducer(loaded, { type: "documents/removed", id: "d1" });
    expect(state.documents).toEqual([]);
  });

  it("applies a document.status update's progress onto the matching document", () => {
    const loaded = reducer(initialState, { type: "documents/loaded", documents: [doc] });
    const state = reducer(loaded, {
      type: "documents/status",
      payload: { id: "d1", status: "done", error: null, chunks_done: 3, chunks_total: 3 },
    });
    expect(state.documents[0]).toMatchObject({ status: "done", chunks_done: 3, chunks_total: 3 });
  });

  it("ignores a document.status update for an unknown id", () => {
    const state = reducer(initialState, {
      type: "documents/status",
      payload: { id: "missing", status: "done", error: null, chunks_done: 1, chunks_total: 1 },
    });
    expect(state).toBe(initialState);
  });
});

describe("reducer: graph", () => {
  it("loads a graph snapshot", () => {
    const graph = { nodes: [{ id: "n1", name: "A" }], edges: [] };
    const state = reducer(initialState, { type: "graph/loaded", graph });
    expect(state.graph).toEqual(graph);
  });
});

describe("reducer: chat", () => {
  it("starts a turn with a user message and a pending assistant message", () => {
    const state = reducer(initialState, { type: "chat/userMessage", chatId: "c1", text: "hi" });
    expect(state.messages).toEqual([
      { id: "c1:user", role: "user", text: "hi", done: true },
      { id: "c1:assistant", role: "assistant", text: "", done: false },
    ]);
  });

  it("attaches sources to the assistant message and sets the highlight", () => {
    const started = reducer(initialState, { type: "chat/userMessage", chatId: "c1", text: "hi" });
    const state = reducer(started, {
      type: "chat/sources",
      payload: {
        chat_id: "c1",
        node_ids: ["n1"],
        edge_ids: ["e1"],
        doc_ids: ["d1"],
        nodes: [{ id: "n1", name: "A" }],
        facts: ["A relates to B"],
      },
    });
    expect(state.messages[1].sources?.facts).toEqual(["A relates to B"]);
    expect(state.highlight.nodeIds.has("n1")).toBe(true);
    expect(state.highlight.edgeIds.has("e1")).toBe(true);
  });

  it("appends streamed tokens in order to the assistant message", () => {
    const started = reducer(initialState, { type: "chat/userMessage", chatId: "c1", text: "hi" });
    const first = reducer(started, { type: "chat/token", payload: { chat_id: "c1", token: "He" } });
    const state = reducer(first, { type: "chat/token", payload: { chat_id: "c1", token: "llo" } });
    expect(state.messages[1].text).toBe("Hello");
  });

  it("marks the assistant message done on chat.done", () => {
    const started = reducer(initialState, { type: "chat/userMessage", chatId: "c1", text: "hi" });
    const state = reducer(started, { type: "chat/done", payload: { chat_id: "c1" } });
    expect(state.messages[1].done).toBe(true);
  });

  it("marks the assistant message with an error on chat.error", () => {
    const started = reducer(initialState, { type: "chat/userMessage", chatId: "c1", text: "hi" });
    const state = reducer(started, {
      type: "chat/error",
      payload: { chat_id: "c1", message: "Something went wrong." },
    });
    expect(state.messages[1]).toMatchObject({ done: true, error: "Something went wrong." });
  });

  it("highlights a single edge from a fact click, clearing any node highlight", () => {
    const state = reducer(initialState, { type: "chat/highlightEdge", edgeId: "e1" });
    expect(state.highlight.edgeIds.has("e1")).toBe(true);
    expect(state.highlight.nodeIds.size).toBe(0);
  });

  it("clears the highlight", () => {
    const highlighted = reducer(initialState, { type: "chat/highlightEdge", edgeId: "e1" });
    const state = reducer(highlighted, { type: "chat/clearHighlight" });
    expect(state.highlight.edgeIds.size).toBe(0);
    expect(state.highlight.nodeIds.size).toBe(0);
  });
});
