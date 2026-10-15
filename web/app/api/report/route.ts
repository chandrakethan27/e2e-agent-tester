import { NextRequest } from "next/server";
import { reportHtml } from "@/lib/state";

export const dynamic = "force-dynamic";

// Served sandboxed with a locked-down CSP: the report embeds repo-derived text.
export async function GET(req: NextRequest) {
  const html = await reportHtml(req.nextUrl.searchParams.get("run") ?? "");
  if (!html) return new Response("report not ready", { status: 404 });
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src data:" } });
}
