import { promises as fs } from "fs";
import path from "path";

export type Status = "pending" | "running" | "done" | "failed" | "skipped";

export interface AgentState { name: string; phase: string; status: Status; note?: string; updatedAt?: string }
export interface Link { from: string; to: string; kind: "challenge" | "question"; label: string }
export interface FindingState { id: string; agent: string; severity: string; title: string; status: string }
export interface RunState {
  runId: string;
  source: string;
  profile: string;
  depth: string;
  createdAt: string;
  phases: Record<string, Status>;
  agents: AgentState[];
  links: Link[];
  findings: FindingState[];
  recon?: { summary?: string; projectType?: string; languages?: string[] };
  briefing?: { summary?: string; plan?: string[]; cannotTest?: string[] };
  runtimeStatus?: string;
  notice?: { level: string; text: string };
  scores?: { verdict?: string; overall?: number; coverage_pct?: number; gates?: string[] };
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

async function readJson<T>(file: string): Promise<T | undefined> {
  try { return JSON.parse(await fs.readFile(file, "utf-8")) as T; } catch { return undefined; }
}

async function readDir(dir: string): Promise<string[]> {
  try { return await fs.readdir(dir); } catch { return []; }
}

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

export async function listRuns(): Promise<{ runId: string; createdAt: string }[]> {
  const out: { runId: string; createdAt: string }[] = [];
  for (const id of await readDir(RUNS_DIR)) {
    const run = await readJson<{ created_at?: string }>(path.join(RUNS_DIR, id, "run.json"));
    if (run) out.push({ runId: id, createdAt: run.created_at ?? "" });
  }
  return out.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export async function loadRun(requested?: string | null): Promise<RunState | null> {
  const runs = await listRuns();
  const runId = requested && SAFE_ID.test(requested) ? requested : process.env.DEFAULT_RUN_ID && SAFE_ID.test(process.env.DEFAULT_RUN_ID) ? process.env.DEFAULT_RUN_ID : runs[0]?.runId;
  if (!runId) return null;
  const dir = path.join(RUNS_DIR, runId);
  const run = await readJson<any>(path.join(dir, "run.json"));
  if (!run) return null;
  const facts = path.join(dir, "blackboard", "facts");
  const recon = await readJson<any>(path.join(facts, "recon.json"));
  const runtime = await readJson<any>(path.join(facts, "runtime.json"));
  const briefing = await readJson<any>(path.join(facts, "briefing.json"));
  const scores = await readJson<any>(path.join(dir, "scores.json"));
  const statusMap = (await readJson<Record<string, { status: string }>>(path.join(dir, "finding-status.json"))) ?? {};

  const agents: AgentState[] = Object.keys(AGENT_PHASE).map((name) => {
    const a = run.agents?.[name];
    const skipped = run.skipped?.[name] !== undefined;
    return { name, phase: AGENT_PHASE[name], status: (a?.status ?? (skipped ? "skipped" : "pending")) as Status, note: a?.note, updatedAt: a?.updated_at };
  });

  const findings: FindingState[] = [];
  for (const f of await readDir(path.join(dir, "blackboard", "findings"))) {
    const item = await readJson<any>(path.join(dir, "blackboard", "findings", f));
    if (item?.id) findings.push({ id: item.id, agent: item.agent, severity: item.severity, title: item.title, status: statusMap[item.id]?.status ?? "open" });
  }

  const links: Link[] = [];
  const challenges = await readJson<{ challenges?: any[] }>(path.join(facts, "skeptic-challenges.json"));
  for (const c of challenges?.challenges ?? []) {
    const owner = findings.find((f) => f.id === c.finding_id)?.agent;
    if (owner) links.push({ from: "skeptic-agent", to: owner, kind: "challenge", label: c.finding_id });
  }
  for (const m of await readDir(path.join(dir, "blackboard", "messages"))) {
    const msg = await readJson<any>(path.join(dir, "blackboard", "messages", m));
    if (msg?.from && msg?.to) links.push({ from: msg.from, to: msg.to, kind: "question", label: msg.id ?? "question" });
  }

  const failed = agents.filter((a) => a.status === "failed");
  let notice: RunState["notice"];
  if (run.phases?.build === "done" && runtime?.status !== "running") {
    notice = { level: "NOT RUN", text: "The project was NOT run — this is a static review only." };
  } else if (failed.length) {
    notice = { level: "PARTIAL", text: `Some checks did not complete: ${failed.map((a) => a.name).join(", ")}.` };
  }

  const reportReady = await fs.access(path.join(dir, "report.html")).then(() => true, () => false);
  return {
    runId, source: run.source?.raw ?? "", profile: run.profile, depth: run.depth, createdAt: run.created_at,
    phases: run.phases, agents, links, findings,
    recon: recon && { summary: recon.summary, projectType: recon.project_type, languages: recon.languages },
    briefing: briefing && { summary: briefing.summary, plan: briefing.plan, cannotTest: briefing.cannot_test },
    runtimeStatus: runtime?.status, notice,
    scores: scores && { verdict: scores.verdict, overall: scores.overall, coverage_pct: scores.coverage_pct, gates: scores.gates },
    reportReady,
  };
}

export async function reportHtml(runId: string): Promise<string | null> {
  if (!SAFE_ID.test(runId)) return null;
  try { return await fs.readFile(path.join(RUNS_DIR, runId, "report.html"), "utf-8"); } catch { return null; }
}
