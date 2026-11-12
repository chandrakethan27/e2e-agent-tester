"use client";
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import AgentMap from "@/components/AgentMap";
import type { RunState, RunSummary } from "@/lib/state";

const SEV = ["critical", "high", "medium", "low", "info"];
const STALLED_AFTER_MS = 10 * 60 * 1000;

function clock(ms: number) {
  if (!Number.isFinite(ms)) return "—";
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

function ago(ts: string, now: number) {
  const s = Math.max(0, Math.floor((now - new Date(ts).getTime()) / 1000));
  return s < 90 ? `${s}s ago` : `${Math.floor(s / 60)}m ago`;
}

interface StateResponse { run: RunState | null; runs: RunSummary[] }

export default function Page() {
  const [run, setRun] = useState<RunState | null | undefined>(undefined);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [offline, setOffline] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const wanted = new URLSearchParams(window.location.search).get("run") ?? "";
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      let next = 1500;
      try {
        const res = await fetch(`/api/state?run=${encodeURIComponent(wanted)}`, { cache: "no-store", signal: controller.signal });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as StateResponse;
        setRun(data.run);
        setRuns(data.runs);
        setOffline(false);
        if (data.run?.finishedAt) next = 10000; // a finished run changes rarely; keep an eye out for a resume
      } catch {
        if (controller.signal.aborted) return;
        setOffline(true);
        next = 4000;
      }
      timer = setTimeout(tick, next);
    };
    void tick();
    const ticker = setInterval(() => setNow(Date.now()), 1000);
    return () => { controller.abort(); if (timer) clearTimeout(timer); clearInterval(ticker); };
  }, []);

  if (run === undefined) return <main className="wrap"><p className="meta">{offline ? "Cannot reach the live view server — retrying…" : "Connecting…"}</p></main>;
  if (run === null) return <main className="wrap"><h1>Waiting for a run…</h1><p className="meta">Start one in Claude Code with <code>/evaluate &lt;repo-url&gt;</code>. This page updates by itself.</p></main>;

  const finished = Boolean(run.finishedAt) || run.phases.finalize === "done" || run.phases.finalize === "failed";
  const running = !finished && Object.values(run.phases).some((s) => s === "running");
  const lastMs = new Date(run.lastActivityAt || run.createdAt).getTime();
  const stalled = running && now - lastMs > STALLED_AFTER_MS;
  const endMs = finished ? new Date(run.finishedAt || run.lastActivityAt || run.createdAt).getTime() : now;
  const state = offline ? "disconnected — retrying" : finished ? "finished" : stalled ? `no activity for ${clock(now - lastMs)} — may be stalled` : running ? "● live" : "waiting";
  const findings = [...run.findings].sort((a, b) => SEV.indexOf(a.severity) - SEV.indexOf(b.severity));
  const failedAgents = run.agents.filter((a) => a.status === "failed");

  return (
    <main className="wrap">
      <header>
        <p className={`meta ${offline || stalled ? "warn" : ""}`}>{state} · profile <b>{run.profile}</b> · depth <b>{run.depth}</b> · {clock(endMs - new Date(run.createdAt).getTime())}</p>
        <h1>{run.source}</h1>
        <p className="meta">
          Run <code>{run.runId}</code>{run.recon?.projectType ? ` · ${run.recon.projectType}` : ""}{run.recon?.languages?.length ? ` · ${run.recon.languages.join(", ")}` : ""}
          {runs.length > 1 && (
            <> · <label>other runs <select className="picker" value={run.runId} onChange={(e) => { window.location.search = `?run=${encodeURIComponent(e.target.value)}`; }}>
              {runs.map((r) => <option key={r.runId} value={r.runId}>{r.runId}</option>)}
            </select></label></>
          )}
        </p>
      </header>

      {run.notice && <div className={`card notice ${run.notice.level === "PARTIAL" ? "partial" : ""}`} role="status"><b>{run.notice.level}</b> — {run.notice.text}</div>}
      {failedAgents.length > 0 && (
        <div className="card notice partial" role="status">
          <b>Did not complete</b>
          <ul className="clean">{failedAgents.map((a) => <li key={a.name}>{a.name}{a.note ? ` — ${a.note}` : ""}</li>)}</ul>
        </div>
      )}

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
                <span>{f.title}<br /><span className="meta">{f.id} · {f.status}{f.reviewed === false ? " · unreviewed" : ""}</span></span>
              </motion.div>
            ))}
          </AnimatePresence>
          {!findings.length && <p className="meta">No findings yet.</p>}
        </section>
      </div>

      {run.events.length > 0 && (
        <section className="card">
          <b>Activity</b>
          <ul className="feed">
            {[...run.events].reverse().slice(0, 8).map((e, i) => (
              <li key={`${e.ts}-${i}`}><span className="meta">{ago(e.ts, now)}</span> {e.name} → <b>{e.status}</b>{e.note ? <span className="meta"> — {e.note}</span> : null}</li>
            ))}
          </ul>
        </section>
      )}

      {run.scores?.verdict && (
        <motion.section className="card" initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }}>
          <div className="verdict">
            <div><span className="meta">Verdict</span><br /><b className="big">{run.scores.verdict}</b></div>
            <div><span className="meta">Score</span><br /><b className="big">{run.scores.overall ?? "—"}</b>/100</div>
            <div><span className="meta">Coverage</span><br /><b className="big">{run.scores.coverage_pct ?? "—"}%</b></div>
            {run.reportReady && <a className="btn" href={`/runs/${encodeURIComponent(run.runId)}/report.html`} target="_blank" rel="noreferrer">Open full report</a>}
          </div>
          {run.scores.gates.length > 0 && <div className="why gate"><b>Verdict capped by</b><ul className="clean">{run.scores.gates.map((g, i) => <li key={i}>{g}</li>)}</ul></div>}
          {run.scores.caps.length > 0 && <div className="why cap"><b>Limited because</b><ul className="clean">{run.scores.caps.map((g, i) => <li key={i}>{g}</li>)}</ul></div>}
          {run.scores.unreviewed > 0 && <p className="meta">{run.scores.unreviewed} confirmed finding(s) were not cross-examined (unreviewed).</p>}
          {run.scores.untested.length > 0 && (
            <div className="why"><b>Not tested ({run.scores.untested.length})</b>
              <ul className="clean">{run.scores.untested.slice(0, 8).map((u, i) => <li key={i}>{u.what}{u.why ? <span className="meta"> — {u.why}</span> : null}</li>)}</ul>
            </div>
          )}
        </motion.section>
      )}
    </main>
  );
}
