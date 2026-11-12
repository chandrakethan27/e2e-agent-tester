import { promises as fs } from "fs";
import path from "path";

export type Status = "pending" | "running" | "done" | "failed" | "skipped";
const STATUSES: readonly Status[] = ["pending", "running", "done", "failed", "skipped"];
export const PHASES = ["intake", "build", "assess", "crossexam", "synthesis", "finalize"] as const;

export interface AgentState {
  name: string; phase: string; status: Status; note?: string;
  startedAt?: string; finishedAt?: string; updatedAt?: string;
}
export interface Link { from: string; to: string; kind: "challenge" | "question"; label: string }
export interface FindingState { id: string; agent: string; severity: string; title: string; status: string; reviewed?: boolean }
export interface EventItem { ts: string; kind: string; name: string; status: string; note?: string }
export interface Untested { agent: string; what: string; why: string }
export interface RunScores {
  verdict?: string; overall?: number | null; coverage_pct?: number; mode?: string;
  gates: string[]; caps: string[]; untested: Untested[]; unreviewed: number;
}
export interface RunSummary { runId: string; createdAt: string }
export interface RunState {
  runId: string;
  source: string;
  profile: string;
  depth: string;
  createdAt: string;
  finishedAt?: string;
  lastActivityAt: string;
  phases: Record<string, Status>;
  agents: AgentState[];
  links: Link[];
  findings: FindingState[];
  events: EventItem[];
  recon?: { summary?: string; projectType?: string; languages?: string[] };
  briefing?: { summary?: string; plan?: string[]; cannotTest?: string[] };
  runtimeStatus?: string;
  notice?: { level: "NOT RUN" | "STATIC ONLY" | "PARTIAL"; text: string };
  scores?: RunScores;
  reportReady: boolean;
}

const RUNS_DIR = process.env.RUNS_DIR ?? path.join(process.cwd(), "..", "runs");

// Which phase each agent belongs to; the orchestrator spawns them in this order.
export const AGENT_PHASE: Record<string, string> = {
  "recon-agent": "intake", "runner-agent": "build",
  "functional-tester": "assess", "suite-runner": "assess", "perf-agent": "assess",
  "security-agent": "assess", "architecture-agent": "assess", "viability-agent": "assess",
  "skeptic-agent": "crossexam", "use-case-strategist": "synthesis", "report-writer": "synthesis",
};

type Json = Record<string, unknown>;
const isRecord = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);
const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const toStatus = (v: unknown): Status => STATUSES.find((s) => s === v) ?? "pending";

async function readJson(file: string): Promise<unknown> {
  try { return JSON.parse(await fs.readFile(file, "utf-8")) as unknown; } catch { return undefined; }
}
async function readRecord(file: string): Promise<Json | undefined> {
  const value = await readJson(file);
  return isRecord(value) ? value : undefined;
}
async function jsonFiles(dir: string): Promise<string[]> {
  try { return (await fs.readdir(dir)).filter((f) => f.endsWith(".json")).sort(); } catch { return []; }
}

export const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;
export const isSafeId = (id: string | null | undefined): id is string => typeof id === "string" && SAFE_ID.test(id);

export async function listRuns(): Promise<RunSummary[]> {
  const out: RunSummary[] = [];
  let ids: string[] = [];
  try { ids = await fs.readdir(RUNS_DIR); } catch { ids = []; }
  for (const id of ids) {
    if (!isSafeId(id)) continue;
    const run = await readRecord(path.join(RUNS_DIR, id, "run.json"));
    if (run) out.push({ runId: id, createdAt: str(run.created_at) ?? "" });
  }
  return out.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

async function readEvents(dir: string): Promise<EventItem[]> {
  let text = "";
  try { text = await fs.readFile(path.join(dir, "events.jsonl"), "utf-8"); } catch { return []; }
  const events: EventItem[] = [];
  for (const line of text.split("\n").slice(-200)) {
    try {
      const e: unknown = JSON.parse(line);
      if (isRecord(e) && str(e.ts) && str(e.name)) {
        events.push({ ts: str(e.ts) as string, kind: str(e.kind) ?? "", name: str(e.name) as string, status: str(e.status) ?? "", note: str(e.note) });
      }
    } catch { /* a half-written last line */ }
  }
  return events.slice(-40);
}

function parseScores(raw: Json | undefined): RunScores | undefined {
  if (!raw) return undefined;
  const counts = isRecord(raw.counts) ? raw.counts : {};
  const untested: Untested[] = [];
  if (Array.isArray(raw.untested)) {
    for (const u of raw.untested) {
      if (isRecord(u) && str(u.what)) untested.push({ agent: str(u.agent) ?? "", what: str(u.what) as string, why: str(u.why) ?? "" });
    }
  }
  const overall = raw.overall === null ? null : num(raw.overall);
  return {
    verdict: str(raw.verdict), overall, coverage_pct: num(raw.coverage_pct), mode: str(raw.mode),
    gates: strs(raw.gates), caps: strs(raw.caps), untested, unreviewed: num(counts.unreviewed) ?? 0,
  };
}

export async function loadRun(requested?: string | null): Promise<RunState | null> {
  const runs = await listRuns();
  const configured = process.env.DEFAULT_RUN_ID;
  const fallback = isSafeId(configured) ? configured : runs[0]?.runId;
  const runId = isSafeId(requested) ? requested : fallback;
  if (!runId) return null;
  const dir = path.join(RUNS_DIR, runId);
  const run = await readRecord(path.join(dir, "run.json"));
  if (!run) return null;
  const facts = path.join(dir, "blackboard", "facts");
  const recon = await readRecord(path.join(facts, "recon.json"));
  const runtime = await readRecord(path.join(facts, "runtime.json"));
  const briefing = await readRecord(path.join(facts, "briefing.json"));
  const scores = parseScores(await readRecord(path.join(dir, "scores.json")));
  const ledger = (await readRecord(path.join(dir, "finding-status.json"))) ?? {};
  const events = await readEvents(dir);

  const runPhases = isRecord(run.phases) ? run.phases : {};
  const phases: Record<string, Status> = {};
  for (const p of PHASES) phases[p] = toStatus(runPhases[p]);
  const runAgents = isRecord(run.agents) ? run.agents : {};
  const runSkipped = isRecord(run.skipped) ? run.skipped : {};

  const agents: AgentState[] = Object.keys(AGENT_PHASE).map((name) => {
    const a = runAgents[name];
    const rec = isRecord(a) ? a : undefined;
    const status = rec ? toStatus(rec.status) : runSkipped[name] !== undefined ? "skipped" : "pending";
    return {
      name, phase: AGENT_PHASE[name], status, note: str(rec?.note),
      startedAt: str(rec?.started_at), finishedAt: str(rec?.finished_at), updatedAt: str(rec?.updated_at),
    };
  });

  const findings: FindingState[] = [];
  for (const f of await jsonFiles(path.join(dir, "blackboard", "findings"))) {
    const item = await readRecord(path.join(dir, "blackboard", "findings", f));
    const id = str(item?.id);
    if (!item || !id) continue;
    const ledgerEntry = ledger[id];
    const entry: Json = isRecord(ledgerEntry) ? ledgerEntry : {};
    findings.push({
      id, agent: str(item.agent) ?? "", severity: str(entry.severity) ?? str(item.severity) ?? "info",
      title: str(item.title) ?? id, status: str(entry.status) ?? "open", reviewed: entry.reviewed === false ? false : undefined,
    });
  }

  // A challenge curve is only shown while it is outstanding (the finding is still disputed).
  const links: Link[] = [];
  const challenges = await readRecord(path.join(facts, "skeptic-challenges.json"));
  for (const c of Array.isArray(challenges?.challenges) ? (challenges?.challenges as unknown[]) : []) {
    const fid = isRecord(c) ? str(c.finding_id) : undefined;
    const target = findings.find((f) => f.id === fid);
    if (fid && target && target.status === "disputed") links.push({ from: "skeptic-agent", to: target.agent, kind: "challenge", label: fid });
  }
  for (const m of await jsonFiles(path.join(dir, "blackboard", "messages"))) {
    const msg = await readRecord(path.join(dir, "blackboard", "messages", m));
    if (msg && str(msg.from) && str(msg.to) && str(msg.status) === "open") {
      links.push({ from: str(msg.from) as string, to: str(msg.to) as string, kind: "question", label: str(msg.id) ?? "question" });
    }
  }

  const failed = agents.filter((a) => a.status === "failed");
  const runtimeStatus = str(runtime?.status);
  const buildDecided = phases.build === "done" || phases.build === "failed" || phases.build === "skipped";
  let notice: RunState["notice"];
  if (runtimeStatus === "static-only" || (phases.build === "skipped" && runtimeStatus !== "running")) {
    notice = { level: "STATIC ONLY", text: "You chose a static review: the project was not run, so functional, performance and reliability were not tested." };
  } else if (buildDecided && runtimeStatus !== "running") {
    notice = { level: "NOT RUN", text: "The project was NOT run — this is a static review only." };
  } else if (failed.length) {
    notice = { level: "PARTIAL", text: `Some checks did not complete: ${failed.map((a) => a.name).join(", ")}.` };
  }

  const stamps = [str(run.created_at) ?? "", ...agents.map((a) => a.updatedAt ?? ""), ...events.map((e) => e.ts)].filter(Boolean);
  const lastActivityAt = stamps.sort().at(-1) ?? "";
  const reportReady = await fs.access(path.join(dir, "report.html")).then(() => true, () => false);
  return {
    runId, source: str((isRecord(run.source) ? run.source : {}).raw) ?? "", profile: str(run.profile) ?? "", depth: str(run.depth) ?? "",
    createdAt: str(run.created_at) ?? "", finishedAt: str(run.finished_at), lastActivityAt, phases, agents, links, findings, events,
    recon: recon && { summary: str(recon.summary), projectType: str(recon.project_type), languages: strs(recon.languages) },
    briefing: briefing && { summary: str(briefing.summary), plan: strs(briefing.plan), cannotTest: strs(briefing.cannot_test) },
    runtimeStatus, notice, scores, reportReady,
  };
}

const MAX_FILE_BYTES = 20 * 1024 * 1024;

/** A file of one run that the report may link to: the report itself, evidence, or the repo. Nothing else, nothing outside the run. */
export async function runFile(runId: string, rel: string[]): Promise<{ data: Buffer; name: string } | null> {
  if (!isSafeId(runId) || rel.length === 0) return null;
  if (rel.some((p) => p === "" || p === "." || p === ".." || p.includes("\0") || p.includes("\\"))) return null;
  const joined = rel.join("/");
  if (!(joined === "report.html" || joined.startsWith("blackboard/evidence/") || joined.startsWith("repo/"))) return null;
  try {
    const base = await fs.realpath(path.join(RUNS_DIR, runId));
    const target = await fs.realpath(path.join(base, ...rel));
    if (!target.startsWith(base + path.sep)) return null;
    const stat = await fs.stat(target);
    if (!stat.isFile() || stat.size > MAX_FILE_BYTES) return null;
    return { data: await fs.readFile(target), name: path.basename(target) };
  } catch { return null; }
}
