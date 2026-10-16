/** Pure reducer for documents, graph, chat messages and highlight IDs (plan §7.1–§7.3). */

import type {
  ChatDoneEvent,
  ChatErrorEvent,
  ChatSourcesEvent,
  ChatTokenEvent,
  Document,
  DocumentStatusEvent,
  GraphSnapshot,
} from "./types";

export interface ChatSources {
  nodeIds: string[];
  edgeIds: string[];
  docIds: string[];
  nodes: { id: string; name: string }[];
  facts: string[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  done: boolean;
  error?: string;
  sources?: ChatSources;
}

export interface Highlight {
  nodeIds: ReadonlySet<string>;
  edgeIds: ReadonlySet<string>;
}

export interface AppState {
  documents: Document[];
  graph: GraphSnapshot;
  messages: ChatMessage[];
  highlight: Highlight;
}

export const EMPTY_HIGHLIGHT: Highlight = { nodeIds: new Set(), edgeIds: new Set() };

export const initialState: AppState = {
  documents: [],
  graph: { nodes: [], edges: [] },
  messages: [],
  highlight: EMPTY_HIGHLIGHT,
};

export type Action =
  | { type: "documents/loaded"; documents: Document[] }
  | { type: "documents/added"; document: Document }
  | { type: "documents/removed"; id: string }
  | { type: "documents/status"; payload: DocumentStatusEvent }
  | { type: "graph/loaded"; graph: GraphSnapshot }
  | { type: "chat/userMessage"; chatId: string; text: string }
  | { type: "chat/sources"; payload: ChatSourcesEvent }
  | { type: "chat/token"; payload: ChatTokenEvent }
  | { type: "chat/done"; payload: ChatDoneEvent }
  | { type: "chat/error"; payload: ChatErrorEvent }
  | { type: "chat/highlightEdge"; edgeId: string }
  | { type: "chat/clearHighlight" };

function assistantMessageId(chatId: string): string {
  return `${chatId}:assistant`;
}

function updateMessage(
  messages: ChatMessage[],
  id: string,
  update: (message: ChatMessage) => ChatMessage,
): ChatMessage[] {
  const index = messages.findIndex((message) => message.id === id);
  if (index === -1) return messages;
  const next = [...messages];
  next[index] = update(next[index]);
  return next;
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "documents/loaded":
      return { ...state, documents: action.documents };

    case "documents/added":
      return { ...state, documents: [action.document, ...state.documents] };

    case "documents/removed":
      return { ...state, documents: state.documents.filter((doc) => doc.id !== action.id) };

    case "documents/status": {
      const { payload } = action;
      const index = state.documents.findIndex((doc) => doc.id === payload.id);
      if (index === -1) return state;
      const next = [...state.documents];
      next[index] = {
        ...next[index],
        status: payload.status,
        error: payload.error,
        chunks_done: payload.chunks_done,
        chunks_total: payload.chunks_total,
      };
      return { ...state, documents: next };
    }

    case "graph/loaded":
      return { ...state, graph: action.graph };

    case "chat/userMessage": {
      const userMessage: ChatMessage = {
        id: `${action.chatId}:user`,
        role: "user",
        text: action.text,
        done: true,
      };
      const assistantMessage: ChatMessage = {
        id: assistantMessageId(action.chatId),
        role: "assistant",
        text: "",
        done: false,
      };
      return { ...state, messages: [...state.messages, userMessage, assistantMessage] };
    }

    case "chat/sources": {
      const { payload } = action;
      const sources: ChatSources = {
        nodeIds: payload.node_ids,
        edgeIds: payload.edge_ids,
        docIds: payload.doc_ids,
        nodes: payload.nodes,
        facts: payload.facts,
      };
      return {
        ...state,
        messages: updateMessage(state.messages, assistantMessageId(payload.chat_id), (m) => ({
          ...m,
          sources,
        })),
        highlight: { nodeIds: new Set(payload.node_ids), edgeIds: new Set(payload.edge_ids) },
      };
    }

    case "chat/token": {
      const { payload } = action;
      return {
        ...state,
        messages: updateMessage(state.messages, assistantMessageId(payload.chat_id), (m) => ({
          ...m,
          text: m.text + payload.token,
        })),
      };
    }

    case "chat/done": {
      const { payload } = action;
      return {
        ...state,
        messages: updateMessage(state.messages, assistantMessageId(payload.chat_id), (m) => ({
          ...m,
          done: true,
        })),
      };
    }

    case "chat/error": {
      const { payload } = action;
      return {
        ...state,
        messages: updateMessage(state.messages, assistantMessageId(payload.chat_id), (m) => ({
          ...m,
          done: true,
          error: payload.message,
        })),
      };
    }

    case "chat/highlightEdge":
      return { ...state, highlight: { nodeIds: new Set(), edgeIds: new Set([action.edgeId]) } };

    case "chat/clearHighlight":
      return { ...state, highlight: EMPTY_HIGHLIGHT };
  }
}
