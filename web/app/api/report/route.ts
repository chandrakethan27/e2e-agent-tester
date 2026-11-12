import type { NextRequest } from "next/server";
import { isSafeId } from "@/lib/state";

export const dynamic = "force-dynamic";

// Kept for old links: the report now lives at /runs/<id>/report.html so its relative evidence links resolve.
export async function GET(req: NextRequest) {
  const id = req.nextUrl.searchParams.get("run");
  if (!isSafeId(id)) return new Response("report not ready", { status: 404 });
  return new Response(null, { status: 307, headers: { Location: `/runs/${encodeURIComponent(id)}/report.html` } });
}
