/** Pure selector: maps chat.sources IDs to node and edge highlight classes (plan §7.3). */

import type { Highlight } from "./state";

export type HighlightClass = "highlighted" | "dimmed";

export interface HighlightClasses {
  nodes: Record<string, HighlightClass>;
  edges: Record<string, HighlightClass>;
}

export function computeHighlightClasses(
  highlight: Highlight,
  allNodeIds: readonly string[],
  allEdgeIds: readonly string[],
): HighlightClasses {
  const active = highlight.nodeIds.size > 0 || highlight.edgeIds.size > 0;
  const nodes: Record<string, HighlightClass> = {};
  const edges: Record<string, HighlightClass> = {};
  if (!active) return { nodes, edges };

  for (const id of allNodeIds) {
    nodes[id] = highlight.nodeIds.has(id) ? "highlighted" : "dimmed";
  }
  for (const id of allEdgeIds) {
    edges[id] = highlight.edgeIds.has(id) ? "highlighted" : "dimmed";
  }
  return { nodes, edges };
}
