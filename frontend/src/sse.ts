/**
 * Pure SSE parser over a ReadableStream (plan §7.4: no EventSource).
 *
 * Mirrors the framing `app.events.format_sse` writes on the backend: an
 * `event:` line, a `data:` line, a blank line, with `: comment\n\n` blocks for
 * the connected and keep-alive markers. Handles chunks split mid-line and
 * multiple blocks delivered in one chunk by buffering until a full
 * `\n\n`-terminated block is available.
 */

export interface ParsedSSEEvent {
  event: string;
  data: string;
}

export function parseSSEBlock(block: string): ParsedSSEEvent | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }
  if (!event) return null;
  return { event, data: dataLines.join("\n") };
}

export async function* parseSSEStream(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<ParsedSSEEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (value) {
        buffer += decoder.decode(value, { stream: true });
      }
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseSSEBlock(block);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
      if (done) return;
    }
  } finally {
    reader.releaseLock();
  }
}
