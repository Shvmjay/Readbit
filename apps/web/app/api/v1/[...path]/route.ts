// Runtime reverse proxy: the browser only ever talks to this origin, so auth cookies stay first-party.
// Unlike next.config rewrites (resolved at build time), API_URL is read per request, so one image runs anywhere.
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const FORWARD_REQUEST_HEADERS = ["content-type", "cookie", "x-readbit-csrf", "x-request-id", "origin", "accept", "accept-language", "content-length"];
const FORWARD_RESPONSE_HEADERS = ["content-type", "content-disposition", "x-request-id", "cache-control", "retry-after"];

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const base = (process.env.API_URL || "http://localhost:8000").replace(/\/$/, "");
  const target = `${base}/api/v1/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  for (const h of FORWARD_REQUEST_HEADERS) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  const fwd = req.headers.get("x-forwarded-for");
  headers.set("x-forwarded-for", fwd ? fwd.split(",")[0]!.trim() : "unknown");
  const hasBody = !["GET", "HEAD"].includes(req.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? req.body : undefined,
      redirect: "manual",
      cache: "no-store",
      // @ts-expect-error -- required by Node fetch when streaming a request body
      duplex: "half",
    });
  } catch {
    return Response.json(
      { error: { code: "ai_provider_unavailable", message: "The Readbit service is temporarily unreachable. Please retry shortly.", retryable: true } },
      { status: 503 },
    );
  }
  const out = new Headers();
  for (const h of FORWARD_RESPONSE_HEADERS) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  for (const c of upstream.headers.getSetCookie()) out.append("set-cookie", c);
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
