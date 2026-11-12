"use client";
import { motion, useReducedMotion } from "framer-motion";
import type { AgentState, Link, Status } from "@/lib/state";

const PHASES = ["intake", "build", "assess", "crossexam", "synthesis"];
const W = 1200, ROW = 96, TOP = 128;
const COL = W / PHASES.length;
// Pending and skipped nodes are dashed instead of faded, so their strokes keep >= 3:1 contrast on the panel background.
const COLOR: Record<Status, string> = { pending: "#8a96c8", running: "#4cc9f0", done: "#5ee3a1", failed: "#ff6b81", skipped: "#9aa3c7" };
const LABEL = (n: string) => n.replace("-agent", "").replace(/-/g, " ");
const GLYPH: Record<Status, string> = { done: "✓", failed: "✕", running: "●", skipped: "–", pending: "·" };

function layout(agents: AgentState[]) {
  const pos: Record<string, { x: number; y: number }> = {};
  let rows = 1;
  PHASES.forEach((phase, col) => {
    const group = agents.filter((a) => a.phase === phase);
    rows = Math.max(rows, group.length);
    group.forEach((a, i) => { pos[a.name] = { x: col * COL + COL / 2, y: TOP + i * ROW }; });
  });
  return { pos, height: Math.max(560, TOP + rows * ROW + 20) };
}

export default function AgentMap({ agents, links, phases }: { agents: AgentState[]; links: Link[]; phases: Record<string, string> }) {
  const calm = useReducedMotion() ?? false;
  const { pos, height: H } = layout(agents);
  const hub = { x: W / 2, y: 34 };
  const busy = agents.some((a) => a.status === "running");
  const curve = (a: { x: number; y: number }, b: { x: number; y: number }, lift = 60) =>
    `M${a.x},${a.y} Q${(a.x + b.x) / 2},${Math.min(a.y, b.y) - lift} ${b.x},${b.y}`;
  const done = agents.filter((a) => a.status === "done").length;
  const running = agents.filter((a) => a.status === "running").map((a) => LABEL(a.name));

  return (
    <>
      <svg className="map" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Agent map: ${done} of ${agents.length} agents done${running.length ? `, running: ${running.join(", ")}` : ""}`}>
        <defs>
          <filter id="glow"><feGaussianBlur stdDeviation="5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
        </defs>
        {PHASES.map((p, i) => (
          <g key={p}>
            <rect x={i * COL + 6} y={70} width={COL - 12} height={H - 80} rx={16} fill={phases[p] === "running" ? "#12234a" : "#0f1730"} stroke={phases[p] === "running" ? "#4cc9f0" : "#26325a"} />
            <text x={i * COL + COL / 2} y={92} textAnchor="middle" fill="#a3aed8" fontSize={14} style={{ textTransform: "uppercase", letterSpacing: 1 }}>{p === "crossexam" ? "cross-exam" : p}</text>
          </g>
        ))}

        {/* orchestrator hub: pulses only while something is running */}
        {busy && !calm
          ? <motion.circle cx={hub.x} cy={hub.y} r={20} fill="#6c5ce7" filter="url(#glow)" animate={{ r: [20, 23, 20] }} transition={{ repeat: Infinity, duration: 2.4 }} />
          : <circle cx={hub.x} cy={hub.y} r={20} fill="#6c5ce7" />}
        <text x={hub.x + 32} y={hub.y + 5} fill="#cfd6ff" fontSize={14}>orchestrator</text>

        {/* orchestrator → agent lines; a dot travels along the line of a running agent */}
        {agents.map((a) => {
          const p = pos[a.name];
          if (!p) return null;
          const line = `M${hub.x},${hub.y} L${p.x},${p.y}`;
          return (
            <g key={`l-${a.name}`}>
              <path d={line} stroke={COLOR[a.status]} strokeOpacity={a.status === "pending" ? 0.25 : 0.5} strokeWidth={1.5} fill="none" />
              {a.status === "running" && !calm && (
                <circle r={4} fill="#4cc9f0" filter="url(#glow)"><animateMotion dur="1.8s" repeatCount="indefinite" path={line} /></circle>
              )}
            </g>
          );
        })}

        {/* skeptic challenges (outstanding only) and open agent questions */}
        {links.map((l, i) => {
          const a = pos[l.from], b = pos[l.to];
          if (!a || !b) return null;
          const d = curve(a, b, 70);
          const color = l.kind === "challenge" ? "#ffb454" : "#c77dff";
          return (
            <g key={`k-${i}`}>
              <path d={d} stroke={color} strokeWidth={1.8} strokeDasharray="6 5" fill="none" opacity={0.9} />
              {!calm && <circle r={4.5} fill={color}><animateMotion dur="2.6s" repeatCount="indefinite" path={d} /></circle>}
            </g>
          );
        })}

        {/* agent nodes */}
        {agents.map((a) => {
          const p = pos[a.name];
          if (!p) return null;
          const c = COLOR[a.status];
          const pulse = a.status === "running" && !calm;
          return (
            <g key={a.name} transform={`translate(${p.x} ${p.y})`}>
              {pulse && <motion.circle r={34} fill="none" stroke={c} strokeWidth={2} animate={{ r: [30, 46], opacity: [0.7, 0] }} transition={{ repeat: Infinity, duration: 1.6 }} />}
              <circle r={28} fill="#0b1020" stroke={c} strokeWidth={3} strokeDasharray={a.status === "pending" || a.status === "skipped" ? "5 4" : undefined} filter={a.status === "running" ? "url(#glow)" : undefined} />
              <text textAnchor="middle" dy={7} fontSize={20} fill={c}>{GLYPH[a.status]}</text>
              <text textAnchor="middle" y={48} fontSize={14} fill="#e8ecff">{LABEL(a.name)}</text>
              {a.status === "failed" && <text textAnchor="middle" y={63} fontSize={12} fill="#ff6b81">failed</text>}
            </g>
          );
        })}
      </svg>

      {/* The same information as text: readable on a phone and for screen readers. */}
      <ul className="agent-list" aria-label="Agent status">
        {agents.map((a) => (
          <li key={a.name} className={`agent ${a.status}`}>
            <span className="glyph" aria-hidden="true">{GLYPH[a.status]}</span>
            <span><b>{LABEL(a.name)}</b> <span className="meta">{a.status}{a.note ? ` — ${a.note}` : ""}</span></span>
          </li>
        ))}
      </ul>
      <p className="sr-only" aria-live="polite">{running.length ? `Running: ${running.join(", ")}.` : "No agent is running."} {done} of {agents.length} agents done.</p>
    </>
  );
}
