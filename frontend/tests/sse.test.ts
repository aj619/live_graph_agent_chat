import { describe, expect, it } from "vitest";
import { parseSSEBlock, parseSSEStream } from "../src/sse";

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let index = 0;
  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]));
        index += 1;
      } else {
        controller.close();
      }
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const events: { event: string; data: string }[] = [];
  for await (const event of parseSSEStream(stream)) {
    events.push(event);
  }
  return events;
}

describe("parseSSEBlock", () => {
  it("returns null for a comment-only block", () => {
    expect(parseSSEBlock(": keep-alive")).toBeNull();
  });

  it("parses one event and data line", () => {
    expect(parseSSEBlock('event: chat.token\ndata: {"token":"hi"}')).toEqual({
      event: "chat.token",
      data: '{"token":"hi"}',
    });
  });
});

describe("parseSSEStream", () => {
  it("parses multiple events delivered in a single chunk", async () => {
    const events = await collect(streamFromChunks(["event: a\ndata: 1\n\nevent: b\ndata: 2\n\n"]));
    expect(events).toEqual([
      { event: "a", data: "1" },
      { event: "b", data: "2" },
    ]);
  });

  it("parses one event split mid-line across chunks", async () => {
    const events = await collect(
      streamFromChunks(["event: chat.to", 'ken\ndata: {"tok', 'en":"x"}\n\n']),
    );
    expect(events).toEqual([{ event: "chat.token", data: '{"token":"x"}' }]);
  });

  it("skips connected and keep-alive comment blocks", async () => {
    const events = await collect(
      streamFromChunks([": connected\n\nevent: a\ndata: 1\n\n: keep-alive\n\n"]),
    );
    expect(events).toEqual([{ event: "a", data: "1" }]);
  });
});
