/** Center column: Cytoscape canvas, incremental updates keeping positions (plan §7.1, §7.2, §7.3). */

import cytoscape from "cytoscape";
import { useEffect, useRef, useState } from "react";
import { computeHighlightClasses } from "../graphHighlight";
import type { Highlight } from "../state";
import type { GraphSnapshot } from "../types";

interface GraphViewProps {
  graph: GraphSnapshot;
  highlight: Highlight;
  onReload: () => void;
}

const STYLE: cytoscape.StylesheetStyle[] = [
  {
    selector: "node",
    style: {
      label: "data(name)",
      "background-color": "#4f6df5",
      color: "#1b1f27",
      "font-size": 10,
      "text-valign": "bottom",
      "text-margin-y": 6,
      width: 28,
      height: 28,
    },
  },
  {
    selector: "edge",
    style: {
      label: "data(name)",
      "font-size": 9,
      width: 2,
      "line-color": "#9aa5b1",
      "target-arrow-color": "#9aa5b1",
      "target-arrow-shape": "triangle",
      "curve-style": "bezier",
      "text-rotation": "autorotate",
    },
  },
  {
    selector: ".highlighted",
    style: {
      "background-color": "#ffb020",
      "line-color": "#ffb020",
      "target-arrow-color": "#ffb020",
      "border-width": 3,
      "border-color": "#ff8c00",
    },
  },
  {
    selector: ".dimmed",
    style: {
      opacity: 0.25,
    },
  },
];

export function GraphView({ graph, highlight, onReload }: GraphViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const hasLaidOutRef = useRef(false);
  const [selectedFact, setSelectedFact] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({ container: containerRef.current, style: STYLE, wheelSensitivity: 0.2 });
    cy.on("mouseover", "edge", (event) => setSelectedFact(event.target.data("fact") ?? null));
    cy.on("mouseout", "edge", () => setSelectedFact(null));
    cy.on("tap", "edge", (event) => setSelectedFact(event.target.data("fact") ?? null));
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    const nextNodeIds = new Set(graph.nodes.map((node) => node.id));
    const nextEdgeIds = new Set(graph.edges.map((edge) => edge.id));
    cy.batch(() => {
      cy.edges().forEach((edge) => {
        if (!nextEdgeIds.has(edge.id())) edge.remove();
      });
      cy.nodes().forEach((node) => {
        if (!nextNodeIds.has(node.id())) node.remove();
      });

      for (const node of graph.nodes) {
        const existing = cy.getElementById(node.id);
        if (existing.length > 0) {
          existing.data("name", node.name);
          continue;
        }
        const extent = cy.extent();
        cy.add({
          group: "nodes",
          data: { id: node.id, name: node.name },
          position: {
            x: extent.x1 + Math.random() * (extent.x2 - extent.x1 || 400),
            y: extent.y1 + Math.random() * (extent.y2 - extent.y1 || 400),
          },
        });
      }

      for (const edge of graph.edges) {
        const existing = cy.getElementById(edge.id);
        if (existing.length > 0) {
          existing.data({ name: edge.name, fact: edge.fact });
          continue;
        }
        cy.add({
          group: "edges",
          data: {
            id: edge.id,
            source: edge.source_id,
            target: edge.target_id,
            name: edge.name,
            fact: edge.fact,
          },
        });
      }
    });

    // Only the very first load runs a full layout. Later updates place new
    // nodes within the current viewport (above) without moving nodes that
    // already had a position (plan §7.2 acceptance: positions are kept).
    if (!hasLaidOutRef.current && cy.nodes().length > 0) {
      hasLaidOutRef.current = true;
      cy.layout({ name: "cose", animate: false }).run();
      cy.fit(undefined, 40);
    }
  }, [graph]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const classes = computeHighlightClasses(
      highlight,
      cy.nodes().map((n) => n.id()),
      cy.edges().map((e) => e.id()),
    );
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const cls = classes.nodes[node.id()];
        node.toggleClass("highlighted", cls === "highlighted");
        node.toggleClass("dimmed", cls === "dimmed");
      });
      cy.edges().forEach((edge) => {
        const cls = classes.edges[edge.id()];
        edge.toggleClass("highlighted", cls === "highlighted");
        edge.toggleClass("dimmed", cls === "dimmed");
      });
    });
  }, [highlight, graph]);

  return (
    <section className="panel graph-view" aria-label="Knowledge graph">
      <div className="graph-view__toolbar">
        <h2>Graph</h2>
        <div className="graph-view__actions">
          <button type="button" onClick={() => cyRef.current?.fit(undefined, 40)}>
            Fit
          </button>
          <button
            type="button"
            onClick={() => {
              cyRef.current?.layout({ name: "cose", animate: false }).run();
              cyRef.current?.fit(undefined, 40);
            }}
          >
            Re-layout
          </button>
          <button type="button" onClick={onReload}>
            Reload snapshot
          </button>
        </div>
      </div>
      <div ref={containerRef} className="graph-view__canvas" />
      {selectedFact && <p className="graph-view__fact">{selectedFact}</p>}
    </section>
  );
}
