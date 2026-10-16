/** Three-column layout wiring the event stream, reducer, and components (plan §7.1, §7.2). */

import { useCallback, useEffect, useReducer, useState } from "react";
import * as api from "./api";
import { ApiError } from "./api";
import { ChatWidget } from "./components/ChatWidget";
import { FileList } from "./components/FileList";
import { GraphView } from "./components/GraphView";
import { checkUpload, rejectionMessage } from "./limits";
import { initialState, reducer } from "./state";
import type {
  ChatDoneEvent,
  ChatErrorEvent,
  ChatSourcesEvent,
  ChatTokenEvent,
  ConfigResponse,
  DocumentStatusEvent,
  GraphChangedEvent,
} from "./types";
import { useEventStream } from "./useEventStream";

export function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const reloadDocuments = useCallback(() => {
    api
      .listDocuments()
      .then((res) => dispatch({ type: "documents/loaded", documents: res.documents }))
      .catch(() => undefined);
  }, []);

  const reloadGraph = useCallback(() => {
    api
      .getGraph()
      .then((graph) => dispatch({ type: "graph/loaded", graph }))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => undefined);
    reloadDocuments();
    reloadGraph();
  }, [reloadDocuments, reloadGraph]);

  const handleEvent = useCallback(
    (type: string, data: unknown) => {
      switch (type) {
        case "document.status":
          dispatch({ type: "documents/status", payload: data as DocumentStatusEvent });
          break;
        case "graph.changed":
          void (data as GraphChangedEvent);
          reloadGraph();
          break;
        case "chat.sources":
          dispatch({ type: "chat/sources", payload: data as ChatSourcesEvent });
          break;
        case "chat.token":
          dispatch({ type: "chat/token", payload: data as ChatTokenEvent });
          break;
        case "chat.done":
          dispatch({ type: "chat/done", payload: data as ChatDoneEvent });
          setSending(false);
          break;
        case "chat.error":
          dispatch({ type: "chat/error", payload: data as ChatErrorEvent });
          setSending(false);
          break;
      }
    },
    [reloadGraph],
  );

  // On reconnect, events may have been missed while disconnected, so reload
  // both the document list and the graph snapshot (plan §7.2).
  const handleOpen = useCallback(() => {
    reloadDocuments();
    reloadGraph();
  }, [reloadDocuments, reloadGraph]);

  useEventStream(handleEvent, handleOpen);

  function handleUpload(file: File): void {
    setUploadError(null);
    if (config) {
      const check = checkUpload(file, config, state.documents.length);
      if (!check.ok && check.reason) {
        setUploadError(rejectionMessage(check.reason));
        return;
      }
    }
    api
      .uploadDocument(file)
      .then((document) => dispatch({ type: "documents/added", document }))
      .catch((err: unknown) => {
        setUploadError(err instanceof ApiError ? err.message : "Upload failed.");
      });
  }

  function handleDelete(id: string): void {
    api
      .deleteDocument(id)
      .then(() => {
        dispatch({ type: "documents/removed", id });
        reloadGraph();
      })
      .catch(() => undefined);
  }

  function handleSend(text: string): void {
    setSending(true);
    api
      .sendChat(text)
      .then(({ chat_id }) => dispatch({ type: "chat/userMessage", chatId: chat_id, text }))
      .catch(() => setSending(false));
  }

  return (
    <div className="app-layout">
      <FileList
        documents={state.documents}
        config={config}
        uploadError={uploadError}
        onUpload={handleUpload}
        onDelete={handleDelete}
      />
      <GraphView graph={state.graph} highlight={state.highlight} onReload={reloadGraph} />
      <ChatWidget
        messages={state.messages}
        sending={sending}
        onSend={handleSend}
        onSelectFact={(edgeId) => dispatch({ type: "chat/highlightEdge", edgeId })}
        onClearHighlight={() => dispatch({ type: "chat/clearHighlight" })}
      />
    </div>
  );
}
