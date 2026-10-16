/**
 * Right column: message list, input, streamed reply, source facts (plan §7.1).
 * Plain-text rendering only — message text and facts are never parsed as HTML,
 * so an injected `<script>` in a document or answer renders as visible text.
 */

import { useState, type FormEvent } from "react";
import type { ChatMessage } from "../state";

interface ChatWidgetProps {
  messages: ChatMessage[];
  sending: boolean;
  onSend: (text: string) => void;
  onSelectFact: (edgeId: string) => void;
  onClearHighlight: () => void;
}

export function ChatWidget({
  messages,
  sending,
  onSend,
  onSelectFact,
  onClearHighlight,
}: ChatWidgetProps) {
  const [draft, setDraft] = useState("");

  function handleSubmit(event: FormEvent): void {
    event.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    onSend(text);
    setDraft("");
  }

  return (
    <section className="panel chat-widget" aria-label="Chat">
      <h2>Chat</h2>
      <div className="chat-widget__messages">
        {messages.map((message) => (
          <div key={message.id} className={`chat-message chat-message--${message.role}`}>
            <p className="chat-message__text">{message.text}</p>
            {message.error && <p className="chat-message__error">{message.error}</p>}
            {message.sources && message.sources.facts.length > 0 && (
              <ul className="chat-message__sources">
                {message.sources.facts.map((fact, index) => {
                  const edgeId = message.sources?.edgeIds[index];
                  return (
                    <li key={edgeId ?? index}>
                      <button
                        type="button"
                        className="chat-message__source-button"
                        onClick={() => (edgeId ? onSelectFact(edgeId) : onClearHighlight())}
                      >
                        {fact}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        ))}
        {messages.length === 0 && <p className="chat-widget__empty">Ask a question about your documents.</p>}
      </div>
      <form className="chat-widget__form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask a question..."
          disabled={sending}
        />
        <button type="submit" disabled={sending || !draft.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
