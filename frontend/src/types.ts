/** Types for every REST body and SSE event payload (plan §6.1, §6.2, §7.4). */

export type DocumentStatus = "processing" | "done" | "failed" | "interrupted";

export interface Document {
  id: string;
  filename: string;
  status: DocumentStatus;
  error: string | null;
  chunks_total: number | null;
  chunks_done: number;
  created_at: string;
}

export interface DocumentListResponse {
  documents: Document[];
}

export interface ConfigResponse {
  max_documents: number;
  max_file_size_mb: number;
  allowed_extensions: string[];
}

export interface GraphNode {
  id: string;
  name: string;
}

export interface GraphEdge {
  id: string;
  name: string;
  fact: string;
  source_id: string;
  target_id: string;
}

export interface GraphSnapshot {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface ChatResponse {
  chat_id: string;
}

export interface DocumentStatusEvent {
  id: string;
  status: DocumentStatus;
  error: string | null;
  chunks_done: number;
  chunks_total: number | null;
}

export interface GraphChangedEvent {
  doc_id: string;
}

export interface ChatSourcesEvent {
  chat_id: string;
  node_ids: string[];
  edge_ids: string[];
  doc_ids: string[];
  nodes: { id: string; name: string }[];
  facts: string[];
}

export interface ChatTokenEvent {
  chat_id: string;
  token: string;
}

export interface ChatDoneEvent {
  chat_id: string;
}

export interface ChatErrorEvent {
  chat_id: string;
  message: string;
}
