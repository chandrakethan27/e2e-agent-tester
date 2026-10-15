"use client";
import { motion } from "framer-motion";
import type { AgentState, Link } from "@/lib/state";

const PHASES = ["intake", "build", "assess", "crossexam", "synthesis"];
const W = 1200, H = 560, COL = W / PHASES.length;
const COLOR: Record<string, string> = { pending: "#3a4570", running: "#4cc9f0", done: "#5ee3a1", failed: "#ff5d73", skipped: "#555d7c" };
const LABEL = (n: string) => n.replace("-agent", "").replace("-", " ");

function layout(agents: AgentState[]) {
  const pos: Record<string, { x: number; y: number }> = {};
  PHASES.forEach((phase, col) => {
    const group = agents.filter((a) => a.phase === phase);
    group.forEach((a, i) => {
      pos[a.name] = { x: col * COL + COL / 2, y: 110 + ((i + 0.5) * (H - 150)) / Math.max(group.length, 1) };
    });
  });
  return pos;
}

export default function AgentMap({ agents, links, phases }: { agents: AgentState[]; links: Link[]; phases: Record<string, string> }) {
  const pos = layout(agents);
  const hub = { x: W / 2, y: 34 };
  const curve = (a: { x: number; y: number }, b: { x: number; y: number }, lift = 60) =>
    `M${a.x},${a.y} Q${(a.x + b.x) / 2},${Math.min(a.y, b.y) - lift} ${b.x},${b.y}`;

  return (
    <svg className="map" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Agents working on the evaluation">
      <defs>
        <filter id="glow"><feGaussianBlur stdDeviation="5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      {PHASES.map((p, i) => (
        <g key={p}>
          <rect x={i * COL + 6} y={70} width={COL - 12} height={H - 80} rx={16} fill={phases[p] === "running" ? "#12234a" : "#0f1730"} stroke={phases[p] === "running" ? "#4cc9f0" : "#26325a"} />
          <text x={i * COL + COL / 2} y={92} textAnchor="middle" fill="#8f9bc7" fontSize={13} style={{ textTransform: "uppercase", letterSpacing: 1 }}>{p === "crossexam" ? "cross-exam" : p}</text>
        </g>
      ))}

      {/* orchestrator hub */}
      <motion.circle cx={hub.x} cy={hub.y} r={20} fill="#6c5ce7" filter="url(#glow)" animate={{ r: [20, 23, 20] }} transition={{ repeat: Infinity, duration: 2.4 }} />
      <text x={hub.x + 32} y={hub.y + 5} fill="#cfd6ff" fontSize={13}>orchestrator</text>

      {/* orchestrator → agent lines, pulses while running */}
      {agents.map((a) => {
        const p = pos[a.name];
        const path = `M${hub.x},${hub.y} L${p.x},${p.y}`;
        return (
          <g key={`l-${a.name}`}>
            <path d={path} stroke={COLOR[a.status]} strokeOpacity={a.status === "pending" ? 0.15 : 0.45} strokeWidth={1.5} fill="none" />
            {a.status === "running" && (
              <circle r={4} fill="#4cc9f0" filter="url(#glow)">
                <animateMotion dur="1.8s" repeatCount="indefinite" path={path} />
              </circle>
            )}
          </g>
        );
      })}

      {/* skeptic challenges and agent questions */}
      {links.map((l, i) => {
        const a = pos[l.from], b = pos[l.to];
        if (!a || !b) return null;
        const d = curve(a, b, 70);
        const color = l.kind === "challenge" ? "#ffb454" : "#c77dff";
        return (
          <g key={`k-${i}`}>
            <path d={d} stroke={color} strokeWidth={1.8} strokeDasharray="6 5" fill="none" opacity={0.85} />
            <circle r={4.5} fill={color}><animateMotion dur="2.6s" repeatCount="indefinite" path={d} /></circle>
          </g>
        );
      })}

      {/* agent nodes */}
      {agents.map((a) => {
        const p = pos[a.name];
        const c = COLOR[a.status];
        return (
          <motion.g key={a.name} initial={false} animate={{ opacity: a.status === "pending" || a.status === "skipped" ? 0.55 : 1 }} transform={`translate(${p.x} ${p.y})`}>
            {a.status === "running" && <motion.circle r={34} fill="none" stroke={c} strokeWidth={2} animate={{ r: [30, 46], opacity: [0.7, 0] }} transition={{ repeat: Infinity, duration: 1.6 }} />}
            <motion.circle r={28} fill="#0b1020" stroke={c} strokeWidth={3} animate={{ scale: a.status === "running" ? [1, 1.07, 1] : 1 }} transition={{ repeat: a.status === "running" ? Infinity : 0, duration: 1.6 }} filter={a.status === "running" ? "url(#glow)" : undefined} />
            <text textAnchor="middle" dy={6} fontSize={20} fill={c}>{a.status === "done" ? "✓" : a.status === "failed" ? "✕" : a.status === "running" ? "●" : a.status === "skipped" ? "–" : "·"}</text>
            <text textAnchor="middle" y={50} fontSize={13} fill="#e8ecff">{LABEL(a.name)}</text>
            {a.status === "failed" && <text textAnchor="middle" y={66} fontSize={11} fill="#ff5d73">failed</text>}
          </motion.g>
        );
      })}
    </svg>
  );
}
