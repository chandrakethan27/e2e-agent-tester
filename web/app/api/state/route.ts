import { NextRequest, NextResponse } from "next/server";
import { listRuns, loadRun } from "@/lib/state";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const run = await loadRun(req.nextUrl.searchParams.get("run"));
  return NextResponse.json({ run, runs: await listRuns() }, { headers: { "Cache-Control": "no-store" } });
}
