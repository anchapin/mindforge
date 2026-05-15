/**
 * SkillEditor — YAML editor with live validation + DAG preview (#49).
 *
 * Intentionally simple. We use a plain <textarea> instead of Monaco /
 * CodeMirror so we don't pull a multi-MB editor dep into the bundle for
 * a feature whose primary need is "show validation errors as the user
 * types". The DAG preview is a small SVG, not react-flow — same reason.
 *
 * Validation is debounced and POSTed to /api/skills/validate. The
 * response includes the parsed graph so the preview can render even
 * when the YAML has issues that would block save.
 */

import { useEffect, useMemo, useState } from "react";
import {
  validateSkillYaml,
  type SkillValidationResult,
  type SkillGraphPreview,
} from "../lib/api";

interface SkillEditorProps {
  initialYaml?: string;
  /**
   * Called when the user clicks Save AND the YAML is currently valid.
   * The parent decides whether to POST to /api/skills (create) or
   * /api/skills/{id} (update).
   */
  onSave?: (yamlContent: string) => Promise<void> | void;
}

const DEFAULT_YAML = `name: my-new-skill
description: Briefly describe what this skill does.
category: misc
trigger:
  type: keyword
  keywords:
    - example
execution_graph:
  nodes:
    - id: start
      agent: researcher
      goal: Gather context for the task.
    - id: draft
      agent: cmo
      goal: Draft an output for human review.
      requires_approval: true
  edges:
    - from: start
      to: draft
      condition: start.success
`;

export function SkillEditor({ initialYaml, onSave }: SkillEditorProps) {
  const [yamlContent, setYamlContent] = useState(initialYaml ?? DEFAULT_YAML);
  const [validation, setValidation] = useState<SkillValidationResult | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Debounce validation so we don't hammer the backend on every keystroke
  useEffect(() => {
    const handle = setTimeout(async () => {
      setIsValidating(true);
      try {
        const result = await validateSkillYaml(yamlContent);
        setValidation(result);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setValidation({ valid: false, errors: [msg], graph: null });
      } finally {
        setIsValidating(false);
      }
    }, 400);
    return () => clearTimeout(handle);
  }, [yamlContent]);

  const handleSave = async () => {
    if (!validation?.valid || !onSave) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      await onSave(yamlContent);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      {/* Editor pane */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">YAML</h2>
          <ValidationBadge validation={validation} isValidating={isValidating} />
        </div>
        <textarea
          aria-label="Skill YAML"
          spellCheck={false}
          value={yamlContent}
          onChange={(e) => setYamlContent(e.target.value)}
          className="h-96 w-full rounded border border-zinc-700 bg-zinc-950 p-3 font-mono text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none"
        />
        {validation && validation.errors.length > 0 && (
          <ul
            role="alert"
            className="space-y-1 rounded border border-red-700 bg-red-900/20 p-3 text-sm text-red-300"
          >
            {validation.errors.map((err, i) => (
              <li key={i}>• {err}</li>
            ))}
          </ul>
        )}
        {saveError && (
          <div role="alert" className="rounded border border-red-700 bg-red-900/20 p-3 text-sm text-red-300">
            Save failed: {saveError}
          </div>
        )}
        <div className="flex gap-2">
          <button
            onClick={handleSave}
            disabled={!validation?.valid || isSaving || !onSave}
            className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:opacity-50"
          >
            {isSaving ? "Saving…" : "Save skill"}
          </button>
        </div>
      </div>

      {/* Preview pane */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold">Graph preview</h2>
        <DagPreview graph={validation?.graph ?? null} />
      </div>
    </div>
  );
}

function ValidationBadge({
  validation,
  isValidating,
}: {
  validation: SkillValidationResult | null;
  isValidating: boolean;
}) {
  if (isValidating) {
    return (
      <span className="rounded bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
        Validating…
      </span>
    );
  }
  if (validation === null) {
    return null;
  }
  if (validation.valid) {
    return (
      <span className="rounded bg-green-900/40 px-2 py-0.5 text-xs text-green-300">
        ✓ Valid
      </span>
    );
  }
  return (
    <span className="rounded bg-red-900/40 px-2 py-0.5 text-xs text-red-300">
      ✗ {validation.errors.length} error{validation.errors.length === 1 ? "" : "s"}
    </span>
  );
}

/**
 * Minimal SVG DAG renderer. Lays nodes out left-to-right by topological
 * order (roots first). No fancy spring physics — just enough to spot
 * the shape of the graph.
 */
function DagPreview({ graph }: { graph: SkillGraphPreview | null }) {
  const layout = useMemo(() => layoutDag(graph), [graph]);

  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="rounded border border-dashed border-zinc-700 p-6 text-center text-sm text-zinc-500">
        No graph to preview yet.
      </div>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      className="w-full rounded border border-zinc-700 bg-zinc-950"
      role="img"
      aria-label="Skill execution graph preview"
    >
      {/* Edges */}
      {graph.edges.map((edge, i) => {
        const from = layout.positions[edge.from];
        const to = layout.positions[edge.to];
        if (!from || !to) return null;
        return (
          <line
            key={i}
            x1={from.x + 60}
            y1={from.y + 20}
            x2={to.x}
            y2={to.y + 20}
            stroke="#6366f1"
            strokeWidth={1.5}
            markerEnd="url(#arrow)"
          />
        );
      })}

      {/* Arrowhead marker */}
      <defs>
        <marker
          id="arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#6366f1" />
        </marker>
      </defs>

      {/* Nodes */}
      {graph.nodes.map((node) => {
        const pos = layout.positions[node.id];
        if (!pos) return null;
        const isApproval = node.requires_approval === true;
        return (
          <g key={node.id} transform={`translate(${pos.x}, ${pos.y})`}>
            <rect
              width={120}
              height={40}
              rx={4}
              fill={isApproval ? "#3f1d1d" : "#1f2937"}
              stroke={isApproval ? "#dc2626" : "#52525b"}
              strokeWidth={1.5}
            />
            <text
              x={60}
              y={18}
              textAnchor="middle"
              fontSize="11"
              fontFamily="monospace"
              fill="#e4e4e7"
            >
              {node.id}
            </text>
            <text
              x={60}
              y={32}
              textAnchor="middle"
              fontSize="9"
              fill="#a1a1aa"
            >
              {node.agent ?? "?"}
              {isApproval ? " 🔒" : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

interface LayoutResult {
  positions: Record<string, { x: number; y: number }>;
  width: number;
  height: number;
}

/**
 * Topological layer assignment — each node sits in the column equal to
 * its longest-path distance from any root. Within a column, nodes are
 * stacked vertically. Cycles are broken arbitrarily so we still render
 * something even when validate flagged them.
 */
function layoutDag(graph: SkillGraphPreview | null): LayoutResult {
  if (!graph || graph.nodes.length === 0) {
    return { positions: {}, width: 200, height: 100 };
  }

  const COL_W = 180;
  const ROW_H = 70;
  const PADDING = 20;

  const indegree: Record<string, number> = {};
  const outgoing: Record<string, string[]> = {};
  for (const n of graph.nodes) {
    indegree[n.id] = 0;
    outgoing[n.id] = [];
  }
  for (const e of graph.edges) {
    if (e.to in indegree) indegree[e.to] = (indegree[e.to] ?? 0) + 1;
    if (e.from in outgoing) outgoing[e.from].push(e.to);
  }

  // Layer = longest path from any root. BFS from indegree-0 nodes.
  const layer: Record<string, number> = {};
  const queue: string[] = [];
  for (const n of graph.nodes) {
    if (indegree[n.id] === 0) {
      layer[n.id] = 0;
      queue.push(n.id);
    }
  }
  while (queue.length) {
    const id = queue.shift()!;
    for (const next of outgoing[id] ?? []) {
      const candidate = (layer[id] ?? 0) + 1;
      if (candidate > (layer[next] ?? -1)) {
        layer[next] = candidate;
        queue.push(next);
      }
    }
  }
  // Assign cycle-trapped nodes to layer 0 so they render somewhere
  for (const n of graph.nodes) {
    if (layer[n.id] === undefined) layer[n.id] = 0;
  }

  // Group by layer, stack within layer
  const byLayer: Record<number, string[]> = {};
  for (const n of graph.nodes) {
    const l = layer[n.id];
    (byLayer[l] = byLayer[l] ?? []).push(n.id);
  }

  const positions: Record<string, { x: number; y: number }> = {};
  let maxRow = 0;
  for (const lStr of Object.keys(byLayer)) {
    const l = Number(lStr);
    const ids = byLayer[l];
    ids.forEach((id, row) => {
      positions[id] = { x: PADDING + l * COL_W, y: PADDING + row * ROW_H };
      if (row > maxRow) maxRow = row;
    });
  }

  const maxLayer = Math.max(...Object.values(layer));
  return {
    positions,
    width: PADDING * 2 + (maxLayer + 1) * COL_W,
    height: PADDING * 2 + (maxRow + 1) * ROW_H,
  };
}
