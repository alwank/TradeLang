import { NextResponse, type NextRequest } from "next/server";

function port(value: string | undefined, fallback: number) {
  if (value === undefined) return fallback;
  const parsed = Number(value);
  return /^\d+$/.test(value) && parsed >= 1 && parsed <= 65535 ? parsed : null;
}

export function proxy(request: NextRequest) {
  const webPort = port(process.env.TRADELANG_WEB_PORT, 3000);
  const apiPort = port(process.env.TRADELANG_API_PORT, 8000);
  if (webPort === null || apiPort === null || apiPort === webPort) {
    return new NextResponse(null, { status: 503 });
  }
  if (request.headers.get("host") !== `127.0.0.1:${webPort}`) {
    return new NextResponse(null, { status: 404 });
  }
  const target = new URL(`http://127.0.0.1:${apiPort}`);
  const { pathname, search } = request.nextUrl;
  target.pathname = pathname === "/api/health" ? "/health" : pathname;
  target.search = search;
  return NextResponse.rewrite(target);
}

export const config = { matcher: ["/api/health", "/api/v1/:path*"] };
