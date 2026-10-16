import { describe, expect, it } from "vitest";
import { computeHighlightClasses } from "../src/graphHighlight";
import { EMPTY_HIGHLIGHT } from "../src/state";

describe("computeHighlightClasses", () => {
  it("returns no classes when nothing is highlighted", () => {
    const result = computeHighlightClasses(EMPTY_HIGHLIGHT, ["n1", "n2"], ["e1"]);
    expect(result.nodes).toEqual({});
    expect(result.edges).toEqual({});
  });

  it("marks only the IDs in chat.sources as highlighted, every other ID as dimmed", () => {
    const highlight = { nodeIds: new Set(["n1"]), edgeIds: new Set(["e1"]) };
    const result = computeHighlightClasses(highlight, ["n1", "n2"], ["e1", "e2"]);
    expect(result.nodes).toEqual({ n1: "highlighted", n2: "dimmed" });
    expect(result.edges).toEqual({ e1: "highlighted", e2: "dimmed" });
  });

  it("dims every node when only edges are highlighted", () => {
    const highlight = { nodeIds: new Set<string>(), edgeIds: new Set(["e1"]) };
    const result = computeHighlightClasses(highlight, ["n1"], ["e1", "e2"]);
    expect(result.nodes).toEqual({ n1: "dimmed" });
    expect(result.edges).toEqual({ e1: "highlighted", e2: "dimmed" });
  });
});
