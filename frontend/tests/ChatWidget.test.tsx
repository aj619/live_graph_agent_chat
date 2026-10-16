import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatWidget } from "../src/components/ChatWidget";
import type { ChatMessage } from "../src/state";

describe("ChatWidget", () => {
  it("renders an injected <script> tag as plain text, not as markup", () => {
    const injected = "<script>window.__pwned = true;</script>";
    const messages: ChatMessage[] = [
      { id: "c1:assistant", role: "assistant", text: injected, done: true },
    ];

    render(
      <ChatWidget
        messages={messages}
        sending={false}
        onSend={vi.fn()}
        onSelectFact={vi.fn()}
        onClearHighlight={vi.fn()}
      />,
    );

    expect(screen.getByText(injected)).toBeInTheDocument();
    expect(document.querySelectorAll("script")).toHaveLength(0);
  });
});
