"use client";
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import AgentMap from "@/components/AgentMap";
import type { RunState } from "@/lib/state";

const SEV = ["critical", "high", "medium", "low", "info"];

function elapsed(start: string, end: number) {
  const s = Math.max(0, Math.floor((end - new Date(start).getTime()) / 1000));
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

export default function Page() {
  const [run, setRun] = useState<RunState | null | undefined>(undefined);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("run") ?? "";
    let alive = true;
    const tick = async () => {
      try {
        const res = await fetch(`/api/state?run=${encodeURIComponent(wanted)}`, { cache: "no-store" });
        const data = await res.json();
        if (alive) setRun(data.run);
      } catch { /* keep the last state; the server may be restarting */ }
    };
    tick();
    const poll = setInterval(tick, 1500);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => { alive = false; clearInterval(poll); clearInterval(clock); };
  }, []);

  if (run === undefined) return <main className="wrap"><p className="meta">Connecting…</p></main>;
  if (run === null) return <main className="wrap"><h1>Waiting for a run…</h1><p className="meta">Start one in Claude Code with <code>/evaluate &lt;repo-url&gt;</code>. This page updates by itself.</p></main>;

  const finished = run.phases.finalize === "done";
  const findings = [...run.findings].sort((a, b) => SEV.indexOf(a.severity) - SEV.indexOf(b.severity));
  const live = !finished && Object.values(run.phases).some((s) => s === "running");

  return (
    <main className="wrap">
      <header>
        <p className="meta">{live ? "● live" : finished ? "finished" : "waiting"} · profile <b>{run.profile}</b> · depth <b>{run.depth}</b> · {elapsed(run.createdAt, now)}</p>
        <h1>{run.source}</h1>
        <p className="meta">Run <code>{run.runId}</code>{run.recon?.projectType ? ` · ${run.recon.projectType}` : ""}{run.recon?.languages?.length ? ` · ${run.recon.languages.join(", ")}` : ""}</p>
      </header>

      {run.notice && <div className={`card notice ${run.notice.level === "PARTIAL" ? "partial" : ""}`}><b>{run.notice.level}</b> — {run.notice.text}</div>}

      {(run.briefing?.summary || run.recon?.summary) && (
        <section className="card">
          <b>What this repo is</b>
          <p>{run.briefing?.summary ?? run.recon?.summary}</p>
          {run.briefing?.plan?.length ? (<><b>How it will be tested</b><ul className="clean">{run.briefing.plan.map((p, i) => <li key={i}>{p}</li>)}</ul></>) : null}
          {run.briefing?.cannotTest?.length ? (<p className="meta">Cannot be tested: {run.briefing.cannotTest.join("; ")}</p>) : null}
        </section>
      )}

      <div className="timeline">
        {Object.entries(run.phases).map(([p, s]) => <div key={p} className={`phase ${s}`}>{p === "crossexam" ? "cross-exam" : p} · {s}</div>)}
      </div>

      <div className="grid">
        <section className="card"><AgentMap agents={run.agents} links={run.links} phases={run.phases} /></section>
        <section className="card">
          <b>Findings ({findings.length})</b>
          <AnimatePresence initial={false}>
            {findings.map((f) => (
              <motion.div key={f.id} className={`finding ${f.status === "dropped" ? "dim" : ""}`} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0 }} layout>
                <span className={`sev ${f.severity}`}>{f.severity}</span>
                <span>{f.title}<br /><span className="meta">{f.id} · {f.status}</span></span>
              </motion.div>
            ))}
          </AnimatePresence>
          {!findings.length && <p className="meta">No findings yet.</p>}
        </section>
      </div>

      {run.scores?.verdict && (
        <motion.section className="card verdict" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <div><span className="meta">Verdict</span><br /><b className="big">{run.scores.verdict}</b></div>
          <div><span className="meta">Score</span><br /><b className="big">{run.scores.overall ?? "—"}</b>/100</div>
          <div><span className="meta">Coverage</span><br /><b className="big">{run.scores.coverage_pct ?? "—"}%</b></div>
          {run.reportReady && <a className="btn" href={`/api/report?run=${encodeURIComponent(run.runId)}`} target="_blank" rel="noreferrer">Open full report</a>}
        </motion.section>
      )}
    </main>
  );
}
