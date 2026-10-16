/**
 * Opens GET /api/events with a streaming fetch reader and dispatches each
 * parsed SSE block to `onEvent` (plan §7.2, §7.4). Reconnects with
 * exponential backoff when the stream ends or errors. `onOpen` fires after
 * every successful connect (including reconnects), so callers can re-fetch
 * state that may have been missed while disconnected.
 */

import { useEffect, useRef } from "react";
import { parseSSEStream } from "./sse";

export type EventHandler = (type: string, data: unknown) => void;

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;

export function useEventStream(onEvent: EventHandler, onOpen?: () => void): void {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;

  useEffect(() => {
    let cancelled = false;
    let abortController: AbortController | null = null;

    async function connectOnce(): Promise<void> {
      abortController = new AbortController();
      const response = await fetch("/api/events", { signal: abortController.signal });
      if (!response.ok || !response.body) {
        throw new Error(`event stream failed with status ${response.status}`);
      }
      onOpenRef.current?.();
      for await (const { event, data } of parseSSEStream(response.body)) {
        if (cancelled) return;
        let parsed: unknown;
        try {
          parsed = data ? JSON.parse(data) : undefined;
        } catch {
          continue;
        }
        onEventRef.current(event, parsed);
      }
    }

    async function loop(): Promise<void> {
      let backoff = INITIAL_BACKOFF_MS;
      while (!cancelled) {
        try {
          await connectOnce();
          backoff = INITIAL_BACKOFF_MS;
        } catch {
          // Connection failed or ended; fall through to the backoff below.
        }
        if (cancelled) return;
        await new Promise((resolve) => setTimeout(resolve, backoff));
        backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
      }
    }

    void loop();

    return () => {
      cancelled = true;
      abortController?.abort();
    };
  }, []);
}
