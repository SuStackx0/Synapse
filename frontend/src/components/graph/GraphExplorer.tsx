"use client";
import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { getGraph, GraphData, GraphNode, GraphEdge } from "@/lib/api";
import { Loader2, ZoomIn, ZoomOut, RotateCcw, Info } from "lucide-react";

const NODE_COLOR: Record<string, string> = {
  File: "#1e3a5f",
  Function: "#1a3a1a",
  Class: "#3a1a3a",
  Module: "#2a2a1a",
};
const NODE_STROKE: Record<string, string> = {
  File: "#00d4ff",
  Function: "#00ff87",
  Class: "#a855f7",
  Module: "#fbbf24",
};

export default function GraphExplorer({ repoId }: { repoId: string }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [data, setData] = useState<GraphData | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown>>();

  useEffect(() => {
    getGraph(repoId).then(setData).finally(() => setLoading(false));
  }, [repoId]);

  useEffect(() => {
    if (!data || !svgRef.current) return;
    const el = svgRef.current;
    const { width, height } = el.getBoundingClientRect();
    d3.select(el).selectAll("*").remove();

    let nodes = data.nodes.filter((n) => filter === "all" || n.type === filter);
    const nodeIds = new Set(nodes.map((n) => n.id));
    let links = data.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));

    const svg = d3.select(el).attr("width", width).attr("height", height);
    const g = svg.append("g");

    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 4])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);
    zoomRef.current = zoom;

    // Defs: glow filter
    const defs = svg.append("defs");
    ["cyan", "green", "purple", "yellow"].forEach((c, i) => {
      const colors = ["#00d4ff", "#00ff87", "#a855f7", "#fbbf24"];
      const filter = defs.append("filter").attr("id", `glow-${c}`);
      filter.append("feGaussianBlur").attr("stdDeviation", "3").attr("result", "coloredBlur");
      const merge = filter.append("feMerge");
      merge.append("feMergeNode").attr("in", "coloredBlur");
      merge.append("feMergeNode").attr("in", "SourceGraphic");
    });

    const sim = d3.forceSimulation(nodes as any)
      .force("link", d3.forceLink(links as any).id((d: any) => d.id).distance(60).strength(0.5))
      .force("charge", d3.forceManyBody().strength(-120))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide(20));

    const link = g.append("g").selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", (d) => {
        if (d.rel === "DEFINES") return "#00d4ff33";
        if (d.rel === "IMPORTS") return "#a855f733";
        return "#00ff8733";
      })
      .attr("stroke-width", 1);

    const node = g.append("g").selectAll("g")
      .data(nodes)
      .join("g")
      .attr("cursor", "pointer")
      .call(
        d3.drag<SVGGElement, GraphNode>()
          .on("start", (event, d: any) => { if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on("drag", (event, d: any) => { d.fx = event.x; d.fy = event.y; })
          .on("end", (event, d: any) => { if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; })
      )
      .on("click", (_, d) => setSelected(d));

    node.append("circle")
      .attr("r", (d) => d.type === "File" ? 10 : d.type === "Class" ? 8 : 6)
      .attr("fill", (d) => NODE_COLOR[d.type] || "#1a1a2e")
      .attr("stroke", (d) => NODE_STROKE[d.type] || "#666")
      .attr("stroke-width", 1.5);

    node.append("text")
      .text((d) => (d.name || "").slice(0, 16))
      .attr("x", 12)
      .attr("y", 4)
      .attr("fill", "#e2e8f0")
      .attr("font-size", "9px")
      .attr("font-family", "JetBrains Mono, monospace")
      .attr("opacity", 0.7);

    sim.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x).attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x).attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => sim.stop();
  }, [data, filter]);

  const resetZoom = () => {
    if (!svgRef.current || !zoomRef.current) return;
    d3.select(svgRef.current).transition().duration(500).call(zoomRef.current.transform, d3.zoomIdentity);
  };

  const zoomBy = (factor: number) => {
    if (!svgRef.current || !zoomRef.current) return;
    d3.select(svgRef.current).transition().duration(200).call(zoomRef.current.scaleBy, factor);
  };

  if (loading) return (
    <div className="flex items-center justify-center h-full">
      <div className="text-center">
        <Loader2 className="w-8 h-8 text-synapse-green animate-spin mx-auto mb-3" />
        <p className="text-synapse-muted font-mono text-sm">Building repo brain...</p>
      </div>
    </div>
  );

  const typeCounts = data?.nodes.reduce((acc, n) => ({ ...acc, [n.type]: (acc[n.type as keyof typeof acc] || 0) + 1 }), {} as Record<string, number>) || {};

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="border-b border-synapse-border px-6 py-3 flex items-center gap-4">
        <div className="flex items-center gap-2">
          {["all", "File", "Function", "Class", "Module"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 rounded text-xs font-mono transition-all ${
                filter === f
                  ? "bg-synapse-green/10 border border-synapse-green/40 text-synapse-green"
                  : "border border-synapse-border text-synapse-muted hover:text-synapse-text"
              }`}
            >
              {f} {f !== "all" && typeCounts[f] ? `(${typeCounts[f]})` : ""}
            </button>
          ))}
        </div>
        <div className="flex-1 text-xs text-synapse-muted font-mono">
          {data?.nodes.length} nodes · {data?.edges.length} edges
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => zoomBy(1.3)} className="p-1.5 text-synapse-muted hover:text-synapse-text border border-synapse-border rounded"><ZoomIn className="w-3.5 h-3.5" /></button>
          <button onClick={() => zoomBy(0.7)} className="p-1.5 text-synapse-muted hover:text-synapse-text border border-synapse-border rounded"><ZoomOut className="w-3.5 h-3.5" /></button>
          <button onClick={resetZoom} className="p-1.5 text-synapse-muted hover:text-synapse-text border border-synapse-border rounded"><RotateCcw className="w-3.5 h-3.5" /></button>
        </div>
      </div>

      {/* Legend */}
      <div className="px-6 py-2 border-b border-synapse-border flex items-center gap-6 text-xs font-mono">
        {Object.entries(NODE_STROKE).map(([type, color]) => (
          <div key={type} className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full border" style={{ background: NODE_COLOR[type], borderColor: color }} />
            <span className="text-synapse-muted">{type}</span>
          </div>
        ))}
      </div>

      {/* Graph */}
      <div className="flex-1 relative overflow-hidden">
        <svg ref={svgRef} className="w-full h-full" />

        {/* Node info panel */}
        {selected && (
          <div className="absolute right-4 top-4 w-64 bg-synapse-surface border border-synapse-border rounded-xl p-4">
            <div className="flex items-center gap-2 mb-3">
              <div className="w-3 h-3 rounded-full border" style={{ background: NODE_COLOR[selected.type], borderColor: NODE_STROKE[selected.type] }} />
              <span className="text-xs font-mono text-synapse-muted uppercase">{selected.type}</span>
              <button onClick={() => setSelected(null)} className="ml-auto text-synapse-muted text-lg leading-none">&times;</button>
            </div>
            <p className="text-synapse-text font-mono text-sm font-semibold mb-1 break-all">{selected.name}</p>
            {selected.file_path && <p className="text-synapse-muted text-xs font-mono break-all">{selected.file_path}</p>}
            {selected.lineno && <p className="text-synapse-muted text-xs font-mono">Line {selected.lineno}</p>}
          </div>
        )}
      </div>
    </div>
  );
}
